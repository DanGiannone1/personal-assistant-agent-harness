"""FastAPI orchestrator — session CRUD, message streaming, and file upload.

Proxies all AI interactions to isolated session containers via SessionManager.
"""

import asyncio
import logging
import os
import re
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Reuse the session-container's appdb (owner Cosmos doc) and library (Search-index KB) so
# the orchestrator can serve manual Library actions without duplicating that logic.
_SC = Path(__file__).resolve().parent / "session-container"
if str(_SC) not in sys.path:
    sys.path.insert(0, str(_SC))
import appdb  # noqa: E402
import library  # noqa: E402

import artifact_store

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import auth_users
from api_auth import APIAuthenticator, AuthConfig
from auth_users import current_user
from session_manager import SessionManager
from trace_logging import setup_trace_logging, trace_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Globals set during lifespan
# ---------------------------------------------------------------------------
session_manager: SessionManager | None = None
content_processor = None  # ContentProcessor | None
api_authenticator: APIAuthenticator | None = None


def _trace_dir() -> str | None:
    if os.getenv("LOG_TRACE", "").lower() != "true":
        return None
    trace_dir = os.getenv("LOG_TRACE_DIR")
    if not trace_dir:
        return None
    return os.path.abspath(trace_dir)


def _raw_trace_dir() -> str | None:
    if os.getenv("LOG_RAW_SDK_EVENTS", "").lower() != "true":
        return None
    trace_dir = os.getenv("LOG_RAW_SDK_EVENTS_DIR") or os.getenv("LOG_TRACE_DIR")
    if not trace_dir:
        return None
    return os.path.abspath(trace_dir)


def _clear_trace_log_for_new_session() -> None:
    """Best-effort trace reset for local dev debugging.

    In local development the orchestrator and session container both write to the
    same trace file under LOG_TRACE_DIR. Truncating it on new session makes it
    easier to isolate a single browser run while leaving production behavior alone.
    """
    trace_dir = _trace_dir()
    if not trace_dir or os.getenv("POOL_MANAGEMENT_ENDPOINT", "").startswith("https://"):
        return

    path = os.path.join(trace_dir, "trace.jsonl")
    try:
        os.makedirs(trace_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8"):
            pass
    except Exception:
        logger.warning("Failed to clear trace log for new session", exc_info=True)


def _raw_sdk_trace_path(session_id: str) -> str | None:
    trace_dir = _raw_trace_dir()
    if not trace_dir:
        return None
    return os.path.join(trace_dir, "sdk-events", f"{session_id}.jsonl")


def _clear_session_trace_artifacts(session_id: str) -> None:
    if os.getenv("POOL_MANAGEMENT_ENDPOINT", "").startswith("https://"):
        return

    trace_path = _raw_sdk_trace_path(session_id)
    if not trace_path:
        return

    try:
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        with open(trace_path, "w", encoding="utf-8"):
            pass
    except Exception:
        logger.warning("Failed to clear raw SDK trace file for session %s", session_id, exc_info=True)


def _trace_paths_for_session(session_id: str) -> dict[str, str | None]:
    base = _trace_dir()
    return {
        "trace_log": os.path.join(base, "trace.jsonl") if base else None,
        "raw_sdk_trace": _raw_sdk_trace_path(session_id),
    }


_SEED_ARTIFACT_ID = "art-seed0001"


def _seed_engagement_artifacts() -> int:
    """Give every seeded engagement one openable kickoff-notes.md (idempotent)."""
    seeded = 0
    for engagement_id in ("eng-website-launch", "eng-product-launch", "eng-q3-budget"):
        engagement = appdb.load_engagement(engagement_id)
        if engagement is None:
            continue
        if any(a.get("id") == _SEED_ARTIFACT_ID for a in engagement.get("library", [])):
            continue
        content = (
            f"# Kickoff notes — {engagement['name']}\n\n"
            f"Customer: {engagement.get('customer') or '—'}\n\n"
            "Seeded demo artifact: agenda, attendees, and next steps live here.\n"
        ).encode()
        artifact_store.put(engagement_id, _SEED_ARTIFACT_ID, content, "text/markdown")
        entry = {
            "id": _SEED_ARTIFACT_ID, "name": "kickoff-notes.md", "size": len(content),
            "contentType": "text/markdown", "uploadedBy": engagement["createdBy"],
            "uploadedAt": appdb._now_iso(),
        }

        def _mut(doc):
            if any(a.get("id") == _SEED_ARTIFACT_ID for a in doc.get("library", [])):
                raise appdb.AbortWrite(None)
            doc.setdefault("library", []).insert(0, dict(entry))

        appdb.update_engagement(engagement_id, _mut)
        seeded += 1
    return seeded


@asynccontextmanager
async def lifespan(app: FastAPI):
    global session_manager, content_processor, api_authenticator

    # Content Processing (optional — ADLS + Content Understanding)
    from content_processing import ContentProcessor

    content_processor = ContentProcessor()
    try:
        await content_processor.initialize()
    except Exception:
        logger.warning("Content processing initialization failed — disabled", exc_info=True)
    if content_processor.enabled:
        logger.info("Content processing ready")
    else:
        logger.info("Content processing disabled (ADLS or CU not configured)")

    setup_trace_logging()
    api_authenticator = APIAuthenticator(AuthConfig.from_env())

    session_manager = SessionManager(content_processor)
    await session_manager.start()

    # Seed the account registry + per-user personal spaces (idempotent).
    try:
        await asyncio.to_thread(appdb.ensure_seeded)
        logger.info("User accounts + personal spaces seeded")
    except Exception:
        logger.error("Could not seed users/spaces — sign-in will fail until Cosmos is reachable", exc_info=True)

    # Seed one real artifact per demo engagement (idempotent, best-effort) so the
    # Documents tab always has openable content. Bytes go through artifact_store,
    # so this works identically on the local dir and Azure Blob backends.
    try:
        seeded_artifacts = await asyncio.to_thread(_seed_engagement_artifacts)
        if seeded_artifacts:
            logger.info("Seeded %d engagement artifact(s) via %s",
                        seeded_artifacts, artifact_store.describe())
    except Exception:
        logger.warning("Could not seed engagement artifacts", exc_info=True)

    # Ensure the seeded Library reference docs are actually in the Search index, so the
    # library[] list can't point at content search can't find (idempotent, best-effort).
    try:
        seeded = await asyncio.to_thread(library.ensure_seeded_indexed, str(_SC / "seed_docs"))
        if seeded:
            logger.info("Indexed %d seed Library doc(s)", seeded)
    except Exception:
        logger.warning("Could not index seed Library docs (search may be unconfigured)", exc_info=True)

    # Background reminder scheduler — runs due reminders and emails their output.
    import scheduler
    scheduler_task = asyncio.create_task(scheduler.scheduler_loop(session_manager))
    logger.info("Application started")

    yield

    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await session_manager.stop()
    await content_processor.close()
    logger.info("Application shut down")


app = FastAPI(title="Personal Assistant", lifespan=lifespan)

# CORS: allow localhost only in dev, plus configurable FRONTEND_URL for production
cors_origins = []
frontend_url = os.getenv("FRONTEND_URL")
if frontend_url:
    cors_origins.append(frontend_url)
else:
    # No FRONTEND_URL set — assume local development
    cors_origins.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["authorization", "content-type", "x-api-key", "x-auth-token"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return response


@app.middleware("http")
async def enforce_api_auth(request: Request, call_next):
    if api_authenticator is None:
        return JSONResponse(status_code=503, content={"detail": "Authentication not initialized."})
    rejection = await api_authenticator.authenticate(request)
    if rejection is not None:
        trace_event(
            "orchestrator",
            "auth.rejected",
            method=request.method,
            path=request.url.path,
            status=rejection.status_code,
            detail=rejection.body.decode("utf-8"),
        )
        return rejection
    return await call_next(request)


@app.middleware("http")
async def trace_requests(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    trace_event(
        "orchestrator",
        "http.request",
        method=request.method,
        path=request.url.path,
        query=str(request.url.query),
        status=response.status_code,
        duration_s=round(time.monotonic() - t0, 4),
    )
    return response


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class SendMessageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# Auth — app-level accounts (see auth_users.py; demo-grade by design)
# ---------------------------------------------------------------------------
@app.post("/auth/login")
async def auth_login(req: LoginRequest) -> dict:
    result = await asyncio.to_thread(auth_users.login, req.username, req.password)
    trace_event("orchestrator", "auth.login", user=result["user"]["id"])
    return result


@app.post("/auth/logout", status_code=204)
async def auth_logout(request: Request):
    auth_users.logout(request.headers.get(auth_users.AUTH_HEADER))


@app.get("/auth/me")
async def auth_me(uid: str = Depends(current_user)) -> dict:
    user = await asyncio.to_thread(appdb.get_user, uid)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return {**user, "identity": user.get("identity", "demo")}


@app.get("/users")
async def user_directory(uid: str = Depends(current_user)) -> list[dict]:
    """Member-pick directory for any signed-in user: id, username, displayName only —
    never password hashes or persona (list_users strips hashes; we strip the rest)."""
    users = await asyncio.to_thread(appdb.list_users)
    return [{"id": u["id"], "username": u.get("username", ""),
             "displayName": u.get("displayName", "")} for u in users]


# ---------------------------------------------------------------------------
# Session endpoints — all require a signed-in user; sessions are owned
# ---------------------------------------------------------------------------
async def _require_owned_session(session_id: str, uid: str) -> None:
    """A session belongs to the user who created it. Ownership is in-memory (like the
    session set itself): after an orchestrator restart sessions are gone and the
    frontend re-creates — strict, honest, demo-grade."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    owner = session_manager.session_owner(session_id)
    if owner != uid:
        # 404 (not 403): don't reveal that someone else's session id exists.
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/sessions", status_code=201)
async def create_session(uid: str = Depends(current_user)) -> dict:
    """Create a new isolated agent session owned by the signed-in user."""
    _clear_trace_log_for_new_session()
    metadata = await session_manager.create_session(uid)
    _clear_session_trace_artifacts(metadata["session_id"])
    return metadata


@app.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, req: SendMessageRequest, uid: str = Depends(current_user)) -> StreamingResponse:
    """Send a user message and stream back SSE events."""
    await _require_owned_session(session_id, uid)

    return StreamingResponse(
        session_manager.send_message(session_id, req.prompt, uid),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, uid: str = Depends(current_user)) -> dict:
    """Check if a session is still active (used for session restore on reload)."""
    await _require_owned_session(session_id, uid)
    files = (await session_manager.list_files(session_id)).get("files", [])
    return {"session_id": session_id, "status": "active", "files": files}


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, uid: str = Depends(current_user)):
    """Delete a session."""
    await _require_owned_session(session_id, uid)
    await session_manager.delete_session(session_id)


@app.get("/sessions/{session_id}/trace")
async def get_session_trace(session_id: str, uid: str = Depends(current_user)) -> dict:
    """Return local trace file locations for the current session."""
    await _require_owned_session(session_id, uid)
    return {
        **_trace_paths_for_session(session_id),
    }


@app.get("/sessions/{session_id}/files")
async def list_files(session_id: str, uid: str = Depends(current_user)) -> dict:
    """List files in a session's workspace."""
    await _require_owned_session(session_id, uid)

    try:
        return await session_manager.list_files(session_id)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            raise HTTPException(status_code=exc.response.status_code, detail="Failed to list files")
        raise


@app.get("/sessions/{session_id}/app/state")
async def get_app_state(session_id: str, uid: str = Depends(current_user)) -> dict:
    """Return the signed-in user's application state (rendered by the app pane)."""
    await _require_owned_session(session_id, uid)
    state = await asyncio.to_thread(appdb.load_state, uid)
    state["engagements"] = await asyncio.to_thread(appdb.list_engagements_for, uid)
    state["user"] = await asyncio.to_thread(appdb.get_user, uid)
    state["context"] = await asyncio.to_thread(appdb.load_context, uid)
    return state


@app.get("/sessions/{session_id}/files/content")
async def get_file_content(session_id: str, filename: str, uid: str = Depends(current_user)) -> dict:
    """Get text content for a workspace file."""
    await _require_owned_session(session_id, uid)

    try:
        return await session_manager.get_file_content(session_id, filename)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            try:
                detail = exc.response.json().get("detail", "Request failed")
            except Exception:
                detail = "Request failed"
            raise HTTPException(status_code=exc.response.status_code, detail=detail)
        raise


# ── Library (persistent KB) — manual Save to Library, delete, and view ────────
# These are owner-global operations (the Library spans sessions); the session id is just
# the calling context. Promotion = index the file's text into Search + record it in the
# owner Cosmos doc's library[]. Kept in the orchestrator so the manual UI button works
# without the AI (the agent has equivalent tools).
class SaveToLibraryRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=400)


@app.post("/sessions/{session_id}/library", status_code=201)
async def save_to_library(session_id: str, req: SaveToLibraryRequest, uid: str = Depends(current_user)) -> dict:
    await _require_owned_session(session_id, uid)
    filename = os.path.basename(req.filename)
    try:
        fc = await session_manager.get_file_content(session_id, filename)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"No session file named '{filename}'")
        raise
    if "content" not in fc:
        raise HTTPException(status_code=502, detail="Session file content was unavailable")
    text = fc["content"]
    title = library.title_from_filename(filename)
    try:
        n_chunks = await asyncio.to_thread(library.index_document, filename, title, text)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    def _mut(data):
        existing = appdb.find_library_doc(data, filename)
        now = appdb._now_iso()
        if existing:
            existing["savedAt"] = now
            existing["title"] = title
        else:
            data["library"].append({
                "id": appdb.new_id("lib", data["library"]),
                "filename": filename, "title": title, "savedAt": now, "source": "upload",
            })
    try:
        await asyncio.to_thread(appdb.update_state, uid, _mut)
    except Exception:
        # Recording the entry failed after indexing — roll back the index write so the two
        # stores can't drift, then surface the failure.
        try:
            await asyncio.to_thread(library.delete_document, filename)
        except Exception:
            logger.error("save_to_library rollback failed for %s", filename, exc_info=True)
        raise HTTPException(status_code=502, detail="Could not record the document in the Library")
    return {"filename": filename, "chunks": n_chunks, "status": "saved"}


@app.delete("/sessions/{session_id}/library/{filename}", status_code=204)
async def delete_from_library(session_id: str, filename: str, uid: str = Depends(current_user)):
    await _require_owned_session(session_id, uid)
    fn = os.path.basename(filename)

    # Remove from the Cosmos list FIRST: a leftover index chunk is re-deletable, but a phantom
    # list entry pointing at deleted content is not. (Update aborts cleanly if it's not listed.)
    def _mut(data):
        if appdb.find_library_doc(data, fn) is None:
            raise appdb.AbortWrite(None)
        data["library"] = [d for d in data["library"] if d["filename"] != fn]
    await asyncio.to_thread(appdb.update_state, uid, _mut)
    try:
        await asyncio.to_thread(library.delete_document, fn)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/sessions/{session_id}/library/content")
async def get_library_content(session_id: str, filename: str, uid: str = Depends(current_user)) -> dict:
    """Reconstruct a Library doc's text (from its indexed chunks) for the viewer."""
    await _require_owned_session(session_id, uid)
    fn = os.path.basename(filename)
    try:
        text = await asyncio.to_thread(library.get_document_text, fn)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if text is None:
        raise HTTPException(status_code=404, detail=f"'{fn}' is not in the Library")
    return {"filename": fn, "content": text, "mime_type": "text/markdown"}


# ── Manual CRUD — tasks, events, reminders ───────────────────────────────────
# So the app stands on its own without the AI: the same owner Cosmos doc the agent
# mutates, edited directly from the UI through the concurrency-safe `appdb.update` path.
# No session container / agent involved.
class _NotFound(Exception):
    """Raised inside a mutator when the target record is absent. Propagates through
    appdb.update (which only catches AbortWrite) so _mutate can map it to a 404."""


async def _require_session(session_id: str, uid: str) -> None:
    await _require_owned_session(session_id, uid)


async def _mutate(uid: str, mutator) -> None:
    """Run an update_state mutator off-thread; map a _NotFound from the mutator to a 404."""
    try:
        await asyncio.to_thread(appdb.update_state, uid, mutator)
    except _NotFound:
        raise HTTPException(status_code=404, detail="Not found")


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    status: str = "To do"
    priority: str = "Medium"
    group: str = "General"
    dueDate: str = ""


class TaskUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    status: str | None = None
    priority: str | None = None
    group: str | None = None
    dueDate: str | None = None


class SubtaskCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)


class SubtaskToggle(BaseModel):
    done: bool


@app.post("/sessions/{session_id}/tasks", status_code=201)
async def create_task(session_id: str, req: TaskCreate, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)
    if req.status not in appdb.TASK_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {appdb.TASK_STATUSES}")
    if req.priority not in appdb.TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {appdb.TASK_PRIORITIES}")
    created: dict = {}

    def _mut(data):
        task = {
            "id": appdb.new_id("t", data["tasks"]),
            "title": req.title.strip(), "status": req.status, "priority": req.priority,
            "group": (req.group or "General").strip() or "General", "dueDate": req.dueDate.strip(),
            "subtasks": [], "notes": "", "createdAt": appdb._now_iso(),
        }
        data["tasks"].append(task)
        created.update(task)
    await _mutate(uid, _mut)
    return created


@app.patch("/sessions/{session_id}/tasks/{task_id}")
async def update_task(session_id: str, task_id: str, req: TaskUpdate, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)
    if req.status is not None and req.status not in appdb.TASK_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {appdb.TASK_STATUSES}")
    if req.priority is not None and req.priority not in appdb.TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {appdb.TASK_PRIORITIES}")
    out: dict = {}

    def _mut(data):
        t = appdb.find_task(data, task_id)
        if t is None:
            raise _NotFound()
        for field in ("title", "status", "priority", "group", "dueDate"):
            val = getattr(req, field)
            if val is not None:
                t[field] = val.strip() if isinstance(val, str) else val
        out.update(t)
    await _mutate(uid, _mut)
    return out


@app.delete("/sessions/{session_id}/tasks/{task_id}", status_code=204)
async def delete_task(session_id: str, task_id: str, uid: str = Depends(current_user)):
    await _require_session(session_id, uid)

    def _mut(data):
        if appdb.find_task(data, task_id) is None:
            raise _NotFound()
        data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    await _mutate(uid, _mut)


@app.post("/sessions/{session_id}/tasks/{task_id}/subtasks", status_code=201)
async def add_subtask(session_id: str, task_id: str, req: SubtaskCreate, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)

    def _mut(data):
        t = appdb.find_task(data, task_id)
        if t is None:
            raise _NotFound()
        t.setdefault("subtasks", []).append({"text": req.text.strip(), "done": False})
    await _mutate(uid, _mut)
    return {"status": "added"}


@app.patch("/sessions/{session_id}/tasks/{task_id}/subtasks/{index}")
async def toggle_subtask(session_id: str, task_id: str, index: int, req: SubtaskToggle, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)

    def _mut(data):
        t = appdb.find_task(data, task_id)
        subs = (t or {}).get("subtasks") or []
        if t is None or index < 0 or index >= len(subs):
            raise _NotFound()
        subs[index]["done"] = req.done
    await _mutate(uid, _mut)
    return {"status": "ok"}


@app.delete("/sessions/{session_id}/tasks/{task_id}/subtasks/{index}")
async def delete_subtask(session_id: str, task_id: str, index: int, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)

    def _mut(data):
        t = appdb.find_task(data, task_id)
        subs = (t or {}).get("subtasks") or []
        if t is None or index < 0 or index >= len(subs):
            raise _NotFound()
        subs.pop(index)
    await _mutate(uid, _mut)
    return {"status": "deleted"}


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    date: str = Field(..., min_length=1, max_length=10)   # YYYY-MM-DD
    start: str = ""
    end: str = ""
    type: str = "Meeting"


class EventUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    date: str | None = None
    start: str | None = None
    end: str | None = None
    type: str | None = None


@app.post("/sessions/{session_id}/events", status_code=201)
async def create_event(session_id: str, req: EventCreate, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)
    created: dict = {}

    def _mut(data):
        event = {
            "id": appdb.new_id("e", data["events"]),
            "title": req.title.strip(), "date": req.date.strip(), "start": req.start.strip(),
            "end": req.end.strip(), "type": (req.type or "Meeting").strip() or "Meeting", "notes": "",
        }
        data["events"].append(event)
        created.update(event)
    await _mutate(uid, _mut)
    return created


@app.patch("/sessions/{session_id}/events/{event_id}")
async def update_event(session_id: str, event_id: str, req: EventUpdate, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)
    out: dict = {}

    def _mut(data):
        e = appdb.find_event(data, event_id)
        if e is None:
            raise _NotFound()
        for field in ("title", "date", "start", "end", "type"):
            val = getattr(req, field)
            if val is not None:
                e[field] = val.strip()
        out.update(e)
    await _mutate(uid, _mut)
    return out


@app.delete("/sessions/{session_id}/events/{event_id}", status_code=204)
async def delete_event(session_id: str, event_id: str, uid: str = Depends(current_user)):
    await _require_session(session_id, uid)

    def _mut(data):
        if appdb.find_event(data, event_id) is None:
            raise _NotFound()
        data["events"] = [e for e in data["events"] if e["id"] != event_id]
    await _mutate(uid, _mut)


class ScheduleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1, max_length=2000)
    frequency: str
    time: str
    timezone: str = "UTC"
    daysOfWeek: list[int] = Field(default_factory=list)


class ScheduleUpdate(BaseModel):
    enabled: bool | None = None
    title: str | None = Field(None, max_length=200)
    prompt: str | None = Field(None, max_length=2000)


@app.post("/sessions/{session_id}/schedules", status_code=201)
async def create_schedule(session_id: str, req: ScheduleCreate, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)
    freq = req.frequency.strip().lower()
    if freq not in appdb.SCHEDULE_FREQUENCIES:
        raise HTTPException(status_code=422, detail=f"frequency must be one of {appdb.SCHEDULE_FREQUENCIES}")
    try:
        tz = appdb.normalize_timezone(req.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    days = sorted({d for d in req.daysOfWeek if 0 <= d <= 6}) if freq == "weekly" else []
    if freq == "weekly" and not days:
        raise HTTPException(status_code=422, detail="weekly reminder needs at least one day (0=Mon … 6=Sun)")
    try:
        next_run = appdb.compute_next_run(freq, req.time, tz, days)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=f"bad time: {exc}")
    created: dict = {}

    def _mut(data):
        sched = {
            "id": appdb.new_id("s", data["schedules"]), "title": req.title.strip(),
            "prompt": req.prompt.strip(), "frequency": freq, "time": req.time.strip(),
            "timezone": tz, "daysOfWeek": days, "enabled": True, "channel": "email",
            "createdAt": appdb._now_iso(), "lastRunAt": None, "lastStatus": None,
            "nextRunAt": next_run.isoformat(),
        }
        data["schedules"].append(sched)
        created.update(sched)
    await _mutate(uid, _mut)
    return created


@app.patch("/sessions/{session_id}/schedules/{schedule_id}")
async def update_schedule(session_id: str, schedule_id: str, req: ScheduleUpdate, uid: str = Depends(current_user)) -> dict:
    await _require_session(session_id, uid)
    out: dict = {}

    def _mut(data):
        s = appdb.find_schedule(data, schedule_id)
        if s is None:
            raise _NotFound()
        if req.enabled is not None:
            s["enabled"] = req.enabled
        if req.title is not None:
            s["title"] = req.title.strip()
        if req.prompt is not None:
            s["prompt"] = req.prompt.strip()
        out.update(s)
    await _mutate(uid, _mut)
    return out


@app.delete("/sessions/{session_id}/schedules/{schedule_id}", status_code=204)
async def delete_schedule(session_id: str, schedule_id: str, uid: str = Depends(current_user)):
    await _require_session(session_id, uid)

    def _mut(data):
        if appdb.find_schedule(data, schedule_id) is None:
            raise _NotFound()
        data["schedules"] = [s for s in data["schedules"] if s["id"] != schedule_id]
    await _mutate(uid, _mut)


class SaveContentRequest(BaseModel):
    filename: str
    content: str


@app.put("/sessions/{session_id}/files/content")
async def save_file_content(session_id: str, body: SaveContentRequest, uid: str = Depends(current_user)) -> dict:
    """Persist an in-app edit to an existing text artifact."""
    await _require_owned_session(session_id, uid)
    try:
        return await session_manager.save_file_content(session_id, body.filename, body.content)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            try:
                detail = exc.response.json().get("detail", "Request failed")
            except Exception:
                detail = "Request failed"
            raise HTTPException(status_code=exc.response.status_code, detail=detail)
        raise


@app.post("/sessions/{session_id}/upload")
async def upload_file(session_id: str, file: UploadFile, uid: str = Depends(current_user)) -> dict:
    """Upload a document to a session's workspace."""
    await _require_owned_session(session_id, uid)

    try:
        result = await session_manager.upload_file(session_id, file)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            try:
                detail = exc.response.json().get("detail", "Upload failed")
            except Exception:
                detail = "Upload failed"
            raise HTTPException(status_code=exc.response.status_code, detail=detail)
        raise
    return result




# ── Engagements — shared workspaces (membership-gated at this layer AND in tools) ──
class EngagementCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    customer: str = Field("", max_length=120)
    status: str = Field("", max_length=10)
    statusNote: str = Field("", max_length=300)
    startDate: str = Field("", max_length=10)
    targetDate: str = Field("", max_length=10)


class EngagementPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    customer: str | None = Field(None, max_length=120)
    status: str | None = Field(None, max_length=10)
    statusNote: str | None = Field(None, max_length=300)
    startDate: str | None = Field(None, max_length=10)
    targetDate: str | None = Field(None, max_length=10)


def _check_status_field(status: str | None) -> None:
    if status and status not in appdb.ENGAGEMENT_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {appdb.ENGAGEMENT_STATUSES}")


class MemberAdd(BaseModel):
    userId: str = Field(..., min_length=1, max_length=64)
    role: str = Field("viewer")


class ConventionCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)


async def _load_engagement_authed(engagement_id: str, uid: str, minimum: str = "viewer") -> dict:
    """Engagement doc if the user holds at least `minimum` role. Non-members get 404
    (membership isn't revealed); under-privileged members get 403 (explicit)."""
    engagement = await asyncio.to_thread(appdb.load_engagement, engagement_id)
    if engagement is None or appdb.member_role(engagement, uid) is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    if not appdb.role_at_least(engagement, uid, minimum):
        raise HTTPException(status_code=403, detail=f"Requires {minimum} access")
    return engagement


async def _mutate_engagement(engagement_id: str, uid: str, minimum: str, mutator) -> None:
    """ETag-safe engagement mutation with the role re-checked INSIDE the mutator (fresh
    read each retry, so a concurrent role revocation can't be raced past). The up-front
    authed load turns an unknown id / non-member into a clean 404 before mutating."""
    await _load_engagement_authed(engagement_id, uid, minimum)

    def _mut(doc):
        if appdb.member_role(doc, uid) is None:
            raise _NotFound()
        if not appdb.role_at_least(doc, uid, minimum):
            raise appdb.AbortWrite("forbidden")
        return mutator(doc)

    try:
        result = await asyncio.to_thread(appdb.update_engagement, engagement_id, _mut)
    except _NotFound:
        raise HTTPException(status_code=404, detail="Not found")
    if result == "forbidden":
        raise HTTPException(status_code=403, detail=f"Requires {minimum} access")


@app.get("/engagements")
async def list_engagements(uid: str = Depends(current_user)) -> list[dict]:
    return await asyncio.to_thread(appdb.list_engagements_for, uid)


@app.post("/engagements", status_code=201)
async def create_engagement(req: EngagementCreate, uid: str = Depends(current_user)) -> dict:
    _check_status_field(req.status)
    if req.status in ("yellow", "red") and not req.statusNote.strip():
        raise HTTPException(status_code=422, detail="yellow/red status requires statusNote (the why)")
    engagement = await asyncio.to_thread(
        lambda: appdb.new_engagement(uid, req.name, req.description,
                                     customer=req.customer,
                                     status=req.status, status_note=req.statusNote,
                                     start_date=req.startDate, target_date=req.targetDate))
    trace_event("orchestrator", "engagement.created", user=uid, engagement=engagement["id"])
    return engagement


@app.get("/engagements/{engagement_id}")
async def get_engagement(engagement_id: str, uid: str = Depends(current_user)) -> dict:
    return await _load_engagement_authed(engagement_id, uid)


@app.patch("/engagements/{engagement_id}")
async def patch_engagement(engagement_id: str, req: EngagementPatch, uid: str = Depends(current_user)) -> dict:
    _check_status_field(req.status)

    def _mut(doc):
        if req.name is not None:
            doc["name"] = req.name.strip()
        if req.description is not None:
            doc["description"] = req.description.strip()
        for field, value in (("customer", req.customer),
                             ("status", req.status), ("statusNote", req.statusNote),
                             ("startDate", req.startDate), ("targetDate", req.targetDate)):
            if value is not None:
                doc[field] = value.strip()
        # Guard the RESULTING state, not the request shape: status "yellow"/"red" with an
        # empty (or emptied) note must never land, whichever field this patch carried.
        if doc.get("status") in ("yellow", "red") and not (doc.get("statusNote") or "").strip():
            raise HTTPException(status_code=422,
                                detail="yellow/red status requires statusNote (the why)")
        appdb.log_activity(doc, uid, "engagement.updated", doc["name"])

    # Renames stay owner-only; delivery-record fields (customer/status/dates) are
    # editor-level, matching the tool layer.
    minimum = "owner" if (req.name is not None or req.description is not None) else "editor"
    await _mutate_engagement(engagement_id, uid, minimum, _mut)
    return await _load_engagement_authed(engagement_id, uid)


@app.post("/engagements/{engagement_id}/members", status_code=201)
async def add_member(engagement_id: str, req: MemberAdd, uid: str = Depends(current_user)) -> dict:
    role = req.role.strip().lower()
    if role not in appdb.ENGAGEMENT_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {appdb.ENGAGEMENT_ROLES}")
    # Accept a user id OR username — Entra users are known by sign-in name.
    target = await asyncio.to_thread(appdb.find_user, req.userId)
    if target is None:
        raise HTTPException(status_code=422, detail="No such user")

    def _mut(doc):
        existing = next((m for m in doc["members"] if m["userId"] == target["id"]), None)
        if existing:
            existing["role"] = role
        else:
            doc["members"].append({"userId": target["id"], "role": role})
        appdb.log_activity(doc, uid, "member.added", f"{target['id']} as {role}")
    await _mutate_engagement(engagement_id, uid, "owner", _mut)
    return {"userId": target["id"], "role": role}


@app.delete("/engagements/{engagement_id}/members/{member_id}", status_code=204)
async def remove_member(engagement_id: str, member_id: str, uid: str = Depends(current_user)):
    # Pre-check like every other mutating route: unknown id / non-member → 404,
    # non-owner member → 403 — never a 500 (and no member/non-member shape leak).
    await _load_engagement_authed(engagement_id, uid, "owner")

    def _mut(doc):
        remaining_owners = [m for m in doc["members"]
                            if m["role"] == "owner" and m["userId"] != member_id]
        target = next((m for m in doc["members"] if m["userId"] == member_id), None)
        if target is None:
            raise _NotFound()
        if target["role"] == "owner" and not remaining_owners:
            raise appdb.AbortWrite("last-owner")
        doc["members"] = [m for m in doc["members"] if m["userId"] != member_id]
        appdb.log_activity(doc, uid, "member.removed", member_id)
    def _outer(doc):
        if appdb.member_role(doc, uid) is None:
            raise _NotFound()
        if not appdb.role_at_least(doc, uid, "owner"):
            raise appdb.AbortWrite("forbidden")
        return _mut(doc)
    try:
        result = await asyncio.to_thread(appdb.update_engagement, engagement_id, _outer)
    except _NotFound:
        raise HTTPException(status_code=404, detail="Not found")
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Requires owner access")
    if result == "last-owner":
        raise HTTPException(status_code=422, detail="A engagement must keep at least one owner")


# Engagement-scoped record CRUD — same shapes as personal, gated editor+.
@app.post("/engagements/{engagement_id}/tasks", status_code=201)
async def create_engagement_task(engagement_id: str, req: TaskCreate, uid: str = Depends(current_user)) -> dict:
    if req.status not in appdb.TASK_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {appdb.TASK_STATUSES}")
    if req.priority not in appdb.TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {appdb.TASK_PRIORITIES}")
    created: dict = {}

    def _mut(doc):
        task = {
            "id": appdb.new_id("t", doc["tasks"]),
            "title": req.title.strip(), "status": req.status, "priority": req.priority,
            "group": (req.group or "General").strip() or "General", "dueDate": req.dueDate.strip(),
            "subtasks": [], "notes": "", "createdAt": appdb._now_iso(),
        }
        doc["tasks"].append(task)
        appdb.log_activity(doc, uid, "task.created", task["title"])
        created.update(task)
    await _mutate_engagement(engagement_id, uid, "editor", _mut)
    return created


@app.patch("/engagements/{engagement_id}/tasks/{task_id}")
async def update_engagement_task(engagement_id: str, task_id: str, req: TaskUpdate, uid: str = Depends(current_user)) -> dict:
    if req.status is not None and req.status not in appdb.TASK_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {appdb.TASK_STATUSES}")
    if req.priority is not None and req.priority not in appdb.TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {appdb.TASK_PRIORITIES}")
    out: dict = {}

    def _mut(doc):
        t = appdb.find_task(doc, task_id)
        if t is None:
            raise _NotFound()
        for field in ("title", "status", "priority", "group", "dueDate"):
            val = getattr(req, field)
            if val is not None:
                t[field] = val.strip() if isinstance(val, str) else val
        appdb.log_activity(doc, uid, "task.updated", t["title"])
        out.update(t)
    await _mutate_engagement(engagement_id, uid, "editor", _mut)
    return out


@app.delete("/engagements/{engagement_id}/tasks/{task_id}", status_code=204)
async def delete_engagement_task(engagement_id: str, task_id: str, uid: str = Depends(current_user)):
    def _mut(doc):
        t = appdb.find_task(doc, task_id)
        if t is None:
            raise _NotFound()
        doc["tasks"] = [x for x in doc["tasks"] if x["id"] != task_id]
        appdb.log_activity(doc, uid, "task.deleted", t["title"])
    await _mutate_engagement(engagement_id, uid, "editor", _mut)


@app.post("/engagements/{engagement_id}/conventions", status_code=201)
async def add_convention(engagement_id: str, req: ConventionCreate, uid: str = Depends(current_user)) -> dict:
    created: dict = {}

    def _mut(doc):
        conv = {"id": appdb.new_id("c", doc.get("conventions", [])),
                "text": req.text.strip(), "createdBy": uid, "createdAt": appdb._now_iso()}
        doc.setdefault("conventions", []).append(conv)
        appdb.log_activity(doc, uid, "convention.added", conv["text"])
        created.update(conv)
    await _mutate_engagement(engagement_id, uid, "editor", _mut)
    return created


@app.delete("/engagements/{engagement_id}/conventions/{conv_id}", status_code=204)
async def delete_convention(engagement_id: str, conv_id: str, uid: str = Depends(current_user)):
    def _mut(doc):
        if not any(c["id"] == conv_id for c in doc.get("conventions", [])):
            raise _NotFound()
        doc["conventions"] = [c for c in doc["conventions"] if c["id"] != conv_id]
        appdb.log_activity(doc, uid, "convention.removed", conv_id)
    await _mutate_engagement(engagement_id, uid, "editor", _mut)


# ── Engagement artifacts — durable files, metadata on the doc (R9/R10) ────────
# Bytes live in artifact_store (local dir or Azure Blob); any member can add,
# list, and open; removing needs editor+. Non-members always see 404.

_ARTIFACT_MAX_BYTES = 20 * 1024 * 1024
_ARTIFACT_NAME_RE = re.compile(r"[^A-Za-z0-9._ ()-]+")


def _safe_artifact_name(raw: str | None) -> str:
    name = Path(raw or "").name.strip()  # drop any client-supplied path
    name = _ARTIFACT_NAME_RE.sub("_", name)[:120].strip(" .")
    return name or "artifact"


def _find_artifact(engagement: dict, artifact_id: str) -> dict | None:
    return next((a for a in engagement.get("library", []) if a.get("id") == artifact_id), None)


@app.get("/engagements/{engagement_id}/artifacts")
async def list_artifacts(engagement_id: str, uid: str = Depends(current_user)) -> dict:
    engagement = await _load_engagement_authed(engagement_id, uid)
    return {"artifacts": engagement.get("library", [])}


@app.post("/engagements/{engagement_id}/artifacts", status_code=201)
async def upload_artifact(engagement_id: str, file: UploadFile,
                          uid: str = Depends(current_user)) -> dict:
    eng = await _load_engagement_authed(engagement_id, uid)  # any member may add (R10)
    # Read at most cap+1 bytes so an oversized body 413s without buffering it all
    # (same idiom as session_manager upload).
    data = await file.read(_ARTIFACT_MAX_BYTES + 1)
    if len(data) > _ARTIFACT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Artifact exceeds the 20MB limit")
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")
    entry = {
        "id": f"art-{secrets.token_hex(4)}",
        "name": _safe_artifact_name(file.filename),
        "size": len(data),
        "contentType": file.content_type or "application/octet-stream",
        "uploadedBy": uid,
        "uploadedAt": appdb._now_iso(),
    }
    # Bytes first, metadata second: a metadata failure leaves an orphan blob
    # (harmless, cleaned below), never a listed artifact with no bytes. Storage is
    # keyed by the CANONICAL doc id (the URL segment may omit the eng- prefix).
    await asyncio.to_thread(
        artifact_store.put, eng["id"], entry["id"], data, entry["contentType"])

    def _mut(doc):
        doc.setdefault("library", []).insert(0, dict(entry))
        appdb.log_activity(doc, uid, "artifact.added", entry["name"])

    try:
        await _mutate_engagement(eng["id"], uid, "viewer", _mut)
    except Exception:
        await asyncio.to_thread(artifact_store.delete, eng["id"], entry["id"])
        raise
    return entry


@app.get("/engagements/{engagement_id}/artifacts/{artifact_id}")
async def download_artifact(engagement_id: str, artifact_id: str,
                            uid: str = Depends(current_user)) -> Response:
    engagement = await _load_engagement_authed(engagement_id, uid)
    entry = _find_artifact(engagement, artifact_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    data = await asyncio.to_thread(artifact_store.get, engagement["id"], artifact_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Artifact content missing")
    filename = entry["name"].replace('"', "")
    return Response(
        content=data,
        media_type=entry.get("contentType") or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/engagements/{engagement_id}/artifacts/{artifact_id}", status_code=204)
async def delete_artifact(engagement_id: str, artifact_id: str,
                          uid: str = Depends(current_user)):
    eng = await _load_engagement_authed(engagement_id, uid, "editor")

    def _mut(doc):
        entry = _find_artifact(doc, artifact_id)
        if entry is None:
            raise _NotFound()
        doc["library"] = [a for a in doc["library"] if a.get("id") != artifact_id]
        appdb.log_activity(doc, uid, "artifact.removed", entry["name"])

    await _mutate_engagement(eng["id"], uid, "editor", _mut)
    await asyncio.to_thread(artifact_store.delete, eng["id"], artifact_id)


# ── Navigation context — visit log + quick links (no AI in this path) ─────────
class VisitCreate(BaseModel):
    path: str = Field(..., min_length=1, max_length=300)
    title: str = Field("", max_length=200)


@app.post("/visits", status_code=201)
async def record_visit(req: VisitCreate, uid: str = Depends(current_user)) -> dict:
    """Every route change — manual click or agent-driven — feeds the visit log."""
    await asyncio.to_thread(appdb.record_visit, uid, req.path, req.title)
    return {"status": "ok"}


@app.get("/quicklinks")
async def quick_links(uid: str = Depends(current_user)) -> list[dict]:
    """rank_destinations(context) — the no-utterance consumer: top destinations now."""
    import navsvc
    personal = await asyncio.to_thread(appdb.load_state, uid)
    engagements = await asyncio.to_thread(appdb.list_engagements_for, uid)
    ctx = await asyncio.to_thread(appdb.load_context, uid)
    ranked = await asyncio.to_thread(
        navsvc.rank_destinations, personal, engagements, ctx["visits"], None, None, 5
    )
    return [{"path": d["path"], "title": d["title"], "kind": d["kind"]} for d in ranked]



# ── Personal settings — persona (memories & standing approvals are parked, R7) ──
class PersonaPut(BaseModel):
    role: str = Field("", max_length=120)
    tone: str = Field("", max_length=200)
    outputPrefs: str = Field("", max_length=300)
    language: str = Field("", max_length=60)


@app.put("/settings/persona")
async def put_persona(req: PersonaPut, uid: str = Depends(current_user)) -> dict:
    def _mut(user):
        user["persona"] = {
            "role": req.role.strip(), "tone": req.tone.strip(),
            "outputPrefs": req.outputPrefs.strip(), "language": req.language.strip() or "English",
        }
        return user["persona"]
    persona = await asyncio.to_thread(appdb.update_user, uid, _mut)
    if persona is None:
        raise HTTPException(status_code=404, detail="Unknown user")
    return persona


@app.get("/context-bundle")
async def context_bundle(view: str = "", uid: str = Depends(current_user)) -> dict:
    """The per-turn context bundle — what personalizes the next turn, made LEGIBLE.

    Precedence (docs/projects-spec.md F8): turn instruction > engagement convention >
    user persona > app default. The bundle carries each level separately so the
    inspector can show exactly what applied and why; the frontend renders the same
    bundle into the prompt preamble, so what the user sees IS what the model got.
    """
    user = await asyncio.to_thread(appdb.get_user, uid)
    ctx = await asyncio.to_thread(appdb.load_context, uid)
    conventions: list[dict] = []
    engagement_name = None
    # A engagement's conventions apply when the turn's view is inside that engagement.
    if view.startswith("/engagements/"):
        pid = view.split("/")[2] if len(view.split("/")) > 2 else ""
        engagement = await asyncio.to_thread(appdb.load_engagement, pid)
        if engagement and appdb.member_role(engagement, uid) is not None:
            conventions = engagement.get("conventions", [])
            engagement_name = engagement["name"]
    return {
        "user": {"id": uid, "displayName": (user or {}).get("displayName", uid)},
        "persona": (user or {}).get("persona", {}),
        "conventions": conventions,
        "engagementName": engagement_name,
        "workingContext": ctx["workingContext"],
        "precedence": ["turn instruction", "engagement convention", "user persona", "app default"],
    }

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Return service health."""
    return {"status": "ok"}
