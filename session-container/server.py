"""Lightweight FastAPI server that runs inside each ACA session container.

One container can host multiple logical identifiers in local mode.
Each identifier maps to isolated workspace and session state.

Endpoints:
    POST /chat/stream — streams SSE events for an agent turn
    POST /upload      — saves a file to /workspace
    GET  /files       — lists files in /workspace with metadata
    POST /reset       — destroys agent + clears workspace (local dev)
    GET  /health      — returns 200
"""

import asyncio
import json
import logging
import mimetypes
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from ag_ui.core.events import BaseEvent, RunErrorEvent
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Agent backend is selectable so the same session container can run either the
# standalone LangGraph Deep Agents backend (the deployed primary harness) or
# the GitHub Copilot SDK agent (local portability check). Both expose an
# identical AgentSession interface (see agent_deepagents).
_AGENT_BACKEND = os.getenv("AGENT_BACKEND", "deepagents").lower()
if _AGENT_BACKEND == "deepagents":
    from agent_deepagents import AgentSession
elif _AGENT_BACKEND == "copilot":
    from agent import AgentSession
else:
    raise RuntimeError("AGENT_BACKEND must be 'deepagents' or 'copilot'")
from tracing import setup_tracing
from workbench_core.trace_logging import setup_trace_logging, trace_event
from workbench_core.request_limits import (
    MAX_EDIT_CONTENT_BYTES,
    MAX_EDIT_FILENAME_CHARS,
    JsonRequestBodyLimitMiddleware,
)
from workbench_core.upload_policy import is_allowed_upload
from workload_auth import WorkloadAuthenticator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Agent backend: %s", _AGENT_BACKEND)
setup_trace_logging()


def _sse_event(event: BaseEvent) -> str:
    """Format an AG-UI event as an SSE data line (same framing as the adapters)."""
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"

# In ACA, this is /workspace. In local dev, default to a directory relative to the project root.
_default_ws = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workspace"))
WORKSPACE = os.getenv("WORKSPACE", _default_ws)
UPLOAD_MANIFEST = ".uploaded_files.json"
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{16}$")
workload_authenticator = WorkloadAuthenticator.from_env()


@asynccontextmanager
async def runtime_lifespan(app: FastAPI):
    """Fail before serving an Entra runtime with incomplete trust configuration."""
    workload_authenticator.config.validate()
    yield


app = FastAPI(title="CSA Workbench Session", lifespan=runtime_lifespan)
app.add_middleware(JsonRequestBodyLimitMiddleware)
setup_tracing(app)


@app.middleware("http")
async def enforce_workload_auth(request: Request, call_next):
    rejection = await workload_authenticator.authenticate(request)
    if rejection is not None:
        return rejection
    return await call_next(request)

def _normalize_session_id(raw_session_id: str | None) -> str:
    if raw_session_id and _SESSION_ID_RE.fullmatch(raw_session_id):
        return raw_session_id
    raise HTTPException(status_code=400, detail="Invalid session identifier")


def _session_workspace(session_id: str) -> str:
    return os.path.join(WORKSPACE, session_id)


def _session_exists(session_id: str) -> bool:
    return session_id in _sessions or Path(_session_workspace(session_id)).exists()


def _require_existing_session(session_id: str) -> None:
    if _session_exists(session_id):
        return
    raise HTTPException(status_code=404, detail="Session not found")


def _get_identifier(request: Request) -> str:
    return _normalize_session_id(request.query_params.get("identifier"))


_USER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_session_users: dict[str, str] = {}


def _get_user(request: Request) -> str:
    """Return the write-once actor binding for this session.

    The forwarding header is only an assertion from the orchestrator. Once a
    session exists it must match the first bound actor exactly; it never replaces
    that actor and a restarted runtime fails closed for an unbound workspace.
    """
    if (workload_authenticator.config.is_entra
            and not getattr(request.state, "workload_authenticated", False)):
        raise HTTPException(status_code=401, detail="Unauthorized")
    raw = (request.headers.get("X-User-Id") or "").strip().lower()
    if raw:
        if not _USER_ID_RE.fullmatch(raw):
            raise HTTPException(status_code=400, detail="Invalid user identifier")
    sid = request.query_params.get("identifier") or ""
    known = _session_users.get(sid)
    if not raw:
        # Existing sessions must never inherit their stored owner when the
        # orchestrator omitted its actor assertion.  Keep this neutral so a
        # caller cannot distinguish a real session from an unknown one.
        if known or _session_exists(sid):
            raise HTTPException(status_code=404, detail="Session not found")
        raise HTTPException(status_code=400, detail="Missing user identifier")
    if known and raw and raw != known:
        raise HTTPException(status_code=404, detail="Session not found")
    if known:
        return known
    if _session_exists(sid):
        # A runtime restart loses the in-memory binding. An old workspace must
        # never become claimable by the next forwarded actor.
        raise HTTPException(status_code=404, detail="Session not found")
    return raw


def _workspace_for_request(request: Request) -> str:
    session_id = _get_identifier(request)
    _get_user(request)
    return _session_workspace(session_id)


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.setdefault(session_id, asyncio.Lock())
    return lock


def _manifest_lock(session_id: str) -> asyncio.Lock:
    lock = _manifest_locks.setdefault(session_id, asyncio.Lock())
    return lock


_sessions: dict[str, AgentSession] = {}
_session_locks: dict[str, asyncio.Lock] = {}
_manifest_locks: dict[str, asyncio.Lock] = {}


async def _get_or_create_session(token: str | None, session_id: str, user_id: str) -> AgentSession:
    """Lazy-init the AgentSession for the given session identifier + user."""
    session = _sessions.get(session_id)
    workspace = _session_workspace(session_id)
    if session is None:
        os.makedirs(workspace, exist_ok=True)
        session = AgentSession(workspace, token=token, session_id=session_id, user_id=user_id)
        await session.__aenter__()
        _sessions[session_id] = session
        logger.info(
            "AgentSession initialised (workspace=%s, user=%s, raw_sdk_log=%s)",
            workspace,
            user_id,
            session.raw_sdk_log_path,
        )
    elif session.user_id != user_id:
        # A binding mismatch is never a renewal signal. Keep the original
        # session intact and reveal neither its owner nor its existence.
        raise HTTPException(status_code=404, detail="Session not found")
    elif token and session.token != token:
        await _destroy_session_locked(session_id)
        session = AgentSession(workspace, token=token, session_id=session_id, user_id=user_id)
        await session.__aenter__()
        _sessions[session_id] = session
        logger.info(
            "AgentSession re-initialised (workspace=%s, user=%s, raw_sdk_log=%s)",
            workspace,
            user_id,
            session.raw_sdk_log_path,
        )
    return session


async def _destroy_session_locked(session_id: str) -> None:
    """Destroy a session; caller must hold the matching session lock."""
    session = _sessions.pop(session_id, None)
    if session is None:
        return
    try:
        await session.__aexit__(None, None, None)
    except Exception:
        logger.warning("Error destroying session", exc_info=True)
    logger.info("Agent session destroyed (id=%s)", session_id)


async def _reset_session_state(session_id: str) -> None:
    import shutil

    lock = _session_lock(session_id)
    async with lock:
        await _destroy_session_locked(session_id)
        ws = Path(_session_workspace(session_id))
        if ws.exists():
            shutil.rmtree(ws)
        _manifest_locks.pop(session_id, None)
    # NOTE: deliberately do NOT pop the session lock from _session_locks. Removing it
    # while a concurrent /chat/stream still holds the same lock object would let the
    # next request create a fresh lock and bypass the "Session is busy" (locked())
    # guard — two turns would then mutate the same workspace. Locks persist for the
    # process lifetime (one per session id; bounded and cheap).


# ── Request models ────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)
    navigation_version: int = Field(default=0, ge=0)


# ── Endpoints ─────────────────────────────────────────────────────────────
@app.post("/session", status_code=201)
async def create_session(request: Request) -> dict:
    session_id = _get_identifier(request)
    if _session_exists(session_id) or session_id in _session_users:
        raise HTTPException(status_code=409, detail="Session already exists")
    user_id = _get_user(request)
    workspace = Path(_session_workspace(session_id))
    workspace.mkdir(parents=True, exist_ok=True)
    _session_users[session_id] = user_id
    _ensure_documents_seeded(str(workspace))
    trace_event("session", "session.created", session_id=session_id, user=user_id, workspace=str(workspace))
    return {"session_id": session_id, "status": "active", "user_id": user_id}


@app.get("/session")
async def get_session(request: Request) -> dict:
    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    _get_user(request)
    workspace = Path(_session_workspace(session_id))
    files = sorted(p.name for p in workspace.iterdir() if p.is_file()) if workspace.exists() else []
    return {
        "session_id": session_id,
        "status": "active",
        "workspace_exists": workspace.exists(),
        "agent_initialized": session_id in _sessions,
        "files": files,
    }


@app.delete("/session", status_code=204)
async def delete_session(request: Request) -> None:
    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    _get_user(request)
    await _reset_session_state(session_id)
    trace_event("session", "session.deleted", session_id=session_id)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """Run a full agent turn, streaming SSE events as they happen."""
    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    # Verify actor ownership before taking the process-local turn lock. A rejected
    # caller must never be able to leave the owner's session artificially busy.
    user_id = _get_user(request)
    lock = _session_lock(session_id)

    # Reject immediately if another turn is already in progress.
    if lock.locked():
        raise HTTPException(status_code=409, detail="Session is busy")

    # Acquire the lock eagerly so no other request can slip through between
    # the locked() check above and the generator starting to iterate.
    await lock.acquire()

    # Token forwarded from the orchestrator via a header (never in the body).
    token = request.headers.get("X-Cogservices-Token") or None

    try:
        chat_timeout = int(os.getenv("CHAT_TIMEOUT_SECONDS", "300"))
    except ValueError:
        chat_timeout = 300

    async def generate():
        try:
            try:
                session = await _get_or_create_session(token=token, session_id=session_id, user_id=user_id)
                trace_event(
                    "session",
                    "agent.prompt_received",
                    session_id=session_id,
                    uploaded_files=sorted(_read_uploaded_manifest(_session_workspace(session_id))),
                    prompt_length=len(req.prompt),
                    prompt_preview=req.prompt[:500],
                )
                async with asyncio.timeout(chat_timeout):
                    async for event in session.send(req.prompt, req.navigation_version):
                        yield event
            except asyncio.TimeoutError:
                logger.warning("Chat stream timed out after %ds", chat_timeout)
                await _destroy_session_locked(session_id)
                yield _sse_event(RunErrorEvent(message=f"Agent turn timed out after {chat_timeout}s"))
            except Exception:
                logger.exception("Chat stream failed")
                await _destroy_session_locked(session_id)
                yield _sse_event(RunErrorEvent(message="Agent turn failed. Please retry."))
        except GeneratorExit:
            pass
        finally:
            lock.release()

    return StreamingResponse(generate(), media_type="text/event-stream")


UPLOAD_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


@app.post("/upload")
async def upload(file: UploadFile, request: Request) -> dict:
    """Save an uploaded file to the workspace directory."""
    from pathlib import PurePosixPath

    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    workspace = _workspace_for_request(request)

    # Sanitize filename — strip path components
    raw_name = file.filename or "upload"
    safe_name = PurePosixPath(raw_name).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not is_allowed_upload(safe_name):
        raise HTTPException(status_code=415, detail="Markdown (.md) files only")

    os.makedirs(workspace, exist_ok=True)
    dest = os.path.join(workspace, safe_name)

    # Verify resolved path is under WORKSPACE (prevent traversal)
    real_dest = os.path.realpath(dest)
    real_workspace = os.path.realpath(workspace)
    if not real_dest.startswith(real_workspace + os.sep) and real_dest != real_workspace:
        raise HTTPException(status_code=400, detail="Invalid file path")

    # Stream file with size limit
    bytes_written = 0
    with open(real_dest, "wb") as f:
        while chunk := await file.read(8192):
            bytes_written += len(chunk)
            if bytes_written > UPLOAD_MAX_BYTES:
                os.remove(real_dest)
                raise HTTPException(status_code=413, detail="File too large (50 MB limit)")
            f.write(chunk)

    logger.info("Uploaded %s (%d bytes)", safe_name, bytes_written)
    trace_event("session", "fs.upload", session_id=session_id, filename=safe_name, size=bytes_written)
    async with _manifest_lock(session_id):
        uploaded = _read_uploaded_manifest(workspace)
        uploaded.add(safe_name)
        try:
            _write_uploaded_manifest(workspace, uploaded)
        except Exception:
            # File is on disk — manifest failure is non-fatal; origin will default to "generated"
            logger.warning("Failed to update upload manifest for %s", safe_name, exc_info=True)
    return {"path": safe_name, "filename": safe_name, "size": bytes_written}


@app.get("/files")
async def list_files(request: Request) -> dict:
    """List all files in the workspace with metadata."""
    from datetime import datetime, timezone
    from pathlib import Path

    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    workspace = Path(_workspace_for_request(request))

    uploaded = _read_uploaded_manifest(str(workspace))
    files = []
    for entry in sorted(workspace.iterdir()):
        if not entry.is_file():
            continue
        # Never surface internal dotfiles (e.g. the upload manifest) as user
        # artifacts — they are not files the user created or sees. (App state now
        # lives in Cosmos, not a workspace file.)
        if entry.name.startswith("."):
            continue
        stat = entry.stat()
        is_markdown = entry.suffix.lower() == ".md"
        md_sibling = workspace / f"{entry.name}.md"
        files.append({
            "filename": entry.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "has_markdown": (is_markdown and entry.name in uploaded) or md_sibling.exists(),
            "origin": "uploaded" if entry.name in uploaded else "generated",
        })

    trace_event("session", "fs.list", session_id=session_id, filenames=[f["filename"] for f in files])
    return {"files": files}


@app.get("/files/content")
async def file_content(filename: str, request: Request) -> dict:
    """Return UTF-8 text content for a workspace file."""
    from pathlib import Path

    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    trace_event("session", "fs.content_request", session_id=session_id, filename=filename)

    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")

    workspace = Path(_workspace_for_request(request)).resolve()
    target = (workspace / filename).resolve()

    if workspace not in target.parents and target != workspace:
        trace_event("session", "fs.content_error", session_id=session_id, filename=filename, status=400, detail="Invalid file path")
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not target.exists() or not target.is_file():
        trace_event("session", "fs.content_error", session_id=session_id, filename=filename, status=404, detail="File not found")
        raise HTTPException(status_code=404, detail="File not found")

    # Keep payload bounded for in-app canvas rendering.
    max_bytes = 2 * 1024 * 1024
    size = target.stat().st_size
    if size > max_bytes:
        trace_event("session", "fs.content_error", session_id=session_id, filename=filename, status=413, detail="File too large")
        raise HTTPException(status_code=413, detail="File too large to preview in canvas")

    raw = target.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        trace_event("session", "fs.content_error", session_id=session_id, filename=filename, status=415, detail="Binary file")
        raise HTTPException(status_code=415, detail="Binary file preview is not supported")

    mime_type = mimetypes.guess_type(target.name)[0] or "text/plain"
    trace_event("session", "fs.content_response", session_id=session_id, filename=target.name, size=size, mime_type=mime_type)
    return {
        "filename": target.name,
        "size": size,
        "mime_type": mime_type,
        "content": content,
    }


class WriteContentBody(BaseModel):
    filename: str = Field(..., max_length=MAX_EDIT_FILENAME_CHARS)
    content: str = Field(..., max_length=MAX_EDIT_CONTENT_BYTES)


@app.put("/files/content")
async def write_file_content(body: WriteContentBody, request: Request) -> dict:
    """Overwrite an EXISTING text artifact in the workspace (in-app edit).

    Scoped to editing existing, non-hidden text files (the canvas edit feature) — never
    creates arbitrary files, never writes outside the workspace or to dotfiles.
    """
    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    filename = (body.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")

    workspace = Path(_workspace_for_request(request)).resolve()
    target = (workspace / filename).resolve()
    if workspace not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if target.name.startswith("."):
        raise HTTPException(status_code=400, detail="Cannot edit internal files")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.suffix.lower() not in {".md", ".txt", ".csv"}:
        raise HTTPException(status_code=415, detail="Only text artifacts are editable")
    if len(body.content.encode("utf-8")) > MAX_EDIT_CONTENT_BYTES:
        raise HTTPException(status_code=413, detail="Content too large")

    target.write_text(body.content, encoding="utf-8")
    trace_event("session", "fs.content_write", session_id=session_id, filename=target.name, size=target.stat().st_size)
    return {"filename": target.name, "size": target.stat().st_size}


@app.post("/reset")
async def reset(request: Request) -> dict:
    """Reset the session: destroy the agent and clean the workspace.

    In production each session gets a fresh container, so this is a no-op.
    In local dev, the single shared container uses this to simulate isolation.
    """
    session_id = _get_identifier(request)
    _require_existing_session(session_id)
    _get_user(request)
    await _reset_session_state(session_id)
    Path(_session_workspace(session_id)).mkdir(parents=True, exist_ok=True)
    trace_event("session", "session.reset", session_id=session_id)
    return {"status": "reset"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _manifest_path(workspace: str) -> str:
    return os.path.join(workspace, UPLOAD_MANIFEST)


def _read_uploaded_manifest(workspace: str) -> set[str]:
    path = _manifest_path(workspace)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
    names = data.get("uploaded_files", [])
    return {n for n in names if isinstance(n, str)}


def _write_uploaded_manifest(workspace: str, names: set[str]) -> None:
    path = _manifest_path(workspace)
    payload = {"uploaded_files": sorted(names)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


_SEED_DOCS_DIR = Path(__file__).parent / "seed_docs"


def _ensure_documents_seeded(workspace: str) -> None:
    """Seed the workspace's provided source documents into a fresh workspace.

    These are Markdown documents the user works *from* (a project brief, meeting
    notes, a 1:1 log, a short reference/SOP). They are registered in the upload
    manifest for agent reading and summarizing, but remain ephemeral session files,
    not durable Engagement artifacts.
    """
    if not _SEED_DOCS_DIR.is_dir():
        # Fail loud (packaging error): the session workspace depends on these.
        logger.warning("Seed documents directory missing: %s", _SEED_DOCS_DIR)
        return
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    manifest = _read_uploaded_manifest(workspace)
    changed = False
    for src in sorted(_SEED_DOCS_DIR.glob("*.md")):
        dest = ws / src.name
        if not dest.exists():
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        if src.name not in manifest:
            manifest.add(src.name)
            changed = True
    if changed:
        _write_uploaded_manifest(workspace, manifest)
