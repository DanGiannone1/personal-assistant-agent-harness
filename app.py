"""FastAPI orchestrator — session CRUD, message streaming, and file upload.

Proxies all AI interactions to isolated session containers via SessionManager.
"""

import asyncio
import logging
import os
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

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api_auth import APIAuthenticator, AuthConfig
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

    # Ensure the seeded Library reference docs are actually in the Search index, so the
    # library[] list can't point at content search can't find (idempotent, best-effort).
    try:
        seeded = await asyncio.to_thread(library.ensure_seeded_indexed, str(_SC / "seed_docs"))
        if seeded:
            logger.info("Indexed %d seed Library doc(s)", seeded)
    except Exception:
        logger.warning("Could not index seed Library docs (search may be unconfigured)", exc_info=True)

    # Seed the demo user accounts (idempotent). Sign-in depends on these; a failure here
    # surfaces loudly in logs and every login will 401 rather than silently half-work.
    try:
        created = await asyncio.to_thread(appdb.ensure_seeded_users)
        if created:
            logger.info("Seeded %d demo user account(s)", created)
        created = await asyncio.to_thread(appdb.ensure_seeded_projects)
        if created:
            logger.info("Seeded %d demo project(s)", created)
    except Exception:
        logger.warning("Could not seed demo users/projects (Cosmos unreachable?)", exc_info=True)

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
    allow_headers=["authorization", "content-type", "x-api-key", "x-user-token"],
)

# ── User sessions (spec F1) ──────────────────────────────────────────────────
# Demo-grade app-level accounts, distinct from api_auth (which authenticates the CALLER
# application): a login mints an opaque token mapped in memory to the seeded user. An
# orchestrator restart just means re-login — consistent with in-memory agent sessions.
_user_tokens: dict[str, dict] = {}  # token -> {"id","username","displayName"}
_USER_EXEMPT_PATHS = {"/health", "/auth/login"}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return response


@app.middleware("http")
async def enforce_user_auth(request: Request, call_next):
    """Resolve the signed-in user from x-user-token and bind them for this request.

    Runs inside enforce_api_auth (caller auth first, then user identity). The appdb
    contextvar covers direct appdb work (manual CRUD, Library); container-proxied calls
    forward the user explicitly as headers because streaming bodies outlive this scope.
    """
    if request.method == "OPTIONS" or request.url.path in _USER_EXEMPT_PATHS:
        return await call_next(request)
    user = _user_tokens.get(request.headers.get("x-user-token", ""))
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Sign in required."})
    request.state.user = user
    ctx = appdb.set_current_user(user["id"])
    try:
        return await call_next(request)
    finally:
        appdb.reset_current_user(ctx)


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
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Auth endpoints (app-level user accounts — spec F1)
# ---------------------------------------------------------------------------
@app.post("/auth/login")
async def auth_login(req: LoginRequest) -> dict:
    """Exchange username+password for a session token. The seam to a real IdP is here."""
    user = await asyncio.to_thread(appdb.get_user, req.username)
    if user is None or not appdb.verify_password(req.password, user.get("passwordHash", "")):
        # One message for both cases — don't leak which usernames exist.
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = secrets.token_urlsafe(32)
    info = {"id": user["id"], "username": user["username"], "displayName": user.get("displayName") or user["username"]}
    _user_tokens[token] = info
    trace_event("orchestrator", "auth.login", user=info["id"])
    return {"token": token, "user": info}


@app.get("/auth/me")
async def auth_me(request: Request) -> dict:
    """Who is signed in (used for session restore on reload)."""
    return {"user": request.state.user}


@app.post("/auth/logout", status_code=204)
async def auth_logout(request: Request):
    token = request.headers.get("x-user-token", "")
    _user_tokens.pop(token, None)


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------
@app.post("/sessions", status_code=201)
async def create_session(request: Request) -> dict:
    """Create a new isolated agent session for the signed-in user."""
    _clear_trace_log_for_new_session()
    metadata = await session_manager.create_session(user=request.state.user)
    _clear_session_trace_artifacts(metadata["session_id"])
    return metadata


@app.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, req: SendMessageRequest, request: Request) -> StreamingResponse:
    """Send a user message and stream back SSE events."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    return StreamingResponse(
        session_manager.send_message(session_id, req.prompt, user=request.state.user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    """Check if a session is still active (used for session restore on reload)."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    files = (await session_manager.list_files(session_id)).get("files", [])
    return {"session_id": session_id, "status": "active", "files": files}


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """Delete a session."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    await session_manager.delete_session(session_id)


@app.get("/sessions/{session_id}/trace")
async def get_session_trace(session_id: str) -> dict:
    """Return local trace file locations for the current session."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        **_trace_paths_for_session(session_id),
    }


@app.get("/sessions/{session_id}/files")
async def list_files(session_id: str) -> dict:
    """List files in a session's workspace."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        return await session_manager.list_files(session_id)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            raise HTTPException(status_code=exc.response.status_code, detail="Failed to list files")
        raise


@app.get("/sessions/{session_id}/app/state")
async def get_app_state(session_id: str, request: Request) -> dict:
    """Return the signed-in user's application state (rendered by the app pane)."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        return await session_manager.get_app_state(session_id, user=request.state.user)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            raise HTTPException(status_code=exc.response.status_code, detail="Failed to load app state")
        raise


@app.get("/sessions/{session_id}/files/content")
async def get_file_content(session_id: str, filename: str) -> dict:
    """Get text content for a workspace file."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

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
async def save_to_library(session_id: str, req: SaveToLibraryRequest) -> dict:
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
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
        await asyncio.to_thread(appdb.update, _mut)
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
async def delete_from_library(session_id: str, filename: str):
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    fn = os.path.basename(filename)

    # Remove from the Cosmos list FIRST: a leftover index chunk is re-deletable, but a phantom
    # list entry pointing at deleted content is not. (Update aborts cleanly if it's not listed.)
    def _mut(data):
        if appdb.find_library_doc(data, fn) is None:
            raise appdb.AbortWrite(None)
        data["library"] = [d for d in data["library"] if d["filename"] != fn]
    await asyncio.to_thread(appdb.update, _mut)
    try:
        await asyncio.to_thread(library.delete_document, fn)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/sessions/{session_id}/library/content")
async def get_library_content(session_id: str, filename: str) -> dict:
    """Reconstruct a Library doc's text (from its indexed chunks) for the viewer."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
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


async def _require_session(session_id: str) -> None:
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


async def _mutate(mutator) -> None:
    """Run an appdb.update mutator off-thread; map a _NotFound from the mutator to a 404."""
    try:
        await asyncio.to_thread(appdb.update, mutator)
    except _NotFound:
        raise HTTPException(status_code=404, detail="Not found")


async def _require_project(request: Request, project_id: str, *, write: bool) -> tuple[dict, str]:
    """Membership-gate a project op. Non-members get a 404 (indistinguishable from absent);
    viewers get a 403 only on writes. Returns (project, role)."""
    uid = request.state.user["id"]
    got = await asyncio.to_thread(appdb.get_project_for, project_id, uid)
    if got is None:
        raise HTTPException(status_code=404, detail="Not found")
    project, role = got
    if write and not appdb.can_write(role):
        raise HTTPException(status_code=403, detail="Viewers can't modify this project.")
    return project, role


async def _mutate_scoped(request: Request, project_id: str | None, mutator) -> None:
    """Apply a record mutator to the chosen scope: a project doc (membership + role
    gated) or the signed-in user's personal doc. The record shape is identical in both."""
    if project_id:
        await _require_project(request, project_id, write=True)
        try:
            await asyncio.to_thread(appdb.update_project, project_id, mutator)
        except _NotFound:
            raise HTTPException(status_code=404, detail="Not found")
    else:
        await _mutate(mutator)


# ── Projects (spec F2) ───────────────────────────────────────────────────────
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    archived: bool | None = None


class MemberAdd(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    role: str = "editor"


class ConventionsPut(BaseModel):
    conventions: list[str] = Field(default_factory=list, max_length=50)


@app.get("/sessions/{session_id}/projects")
async def list_projects(session_id: str, request: Request) -> dict:
    await _require_session(session_id)
    uid = request.state.user["id"]
    projects = await asyncio.to_thread(appdb.list_projects_for, uid)
    for p in projects:
        p["role"] = appdb.project_role(p, uid)
    return {"projects": projects}


@app.post("/sessions/{session_id}/projects", status_code=201)
async def create_project(session_id: str, req: ProjectCreate, request: Request) -> dict:
    await _require_session(session_id)
    project = await asyncio.to_thread(
        appdb.create_project, req.name, request.state.user["id"], req.description
    )
    project["role"] = "owner"
    return project


@app.patch("/sessions/{session_id}/projects/{project_id}")
async def update_project_meta(session_id: str, project_id: str, req: ProjectUpdate, request: Request) -> dict:
    await _require_session(session_id)
    _, role = await _require_project(request, project_id, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can rename or archive.")
    out: dict = {}

    def _mut(data):
        if req.name is not None:
            data["name"] = req.name.strip()
        if req.description is not None:
            data["description"] = req.description.strip()
        if req.archived is not None:
            data["archived"] = req.archived
        out.update(data)
    await asyncio.to_thread(appdb.update_project, project_id, _mut)
    return out


@app.post("/sessions/{session_id}/projects/{project_id}/members", status_code=201)
async def add_member(session_id: str, project_id: str, req: MemberAdd, request: Request) -> dict:
    await _require_session(session_id)
    _, role = await _require_project(request, project_id, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can manage members.")
    if req.role not in appdb.PROJECT_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {list(appdb.PROJECT_ROLES)}")
    user = await asyncio.to_thread(appdb.get_user, req.username)
    if user is None:
        raise HTTPException(status_code=404, detail=f"No user named '{req.username}'")

    def _mut(data):
        if any(m["userId"] == user["id"] for m in data["members"]):
            raise appdb.AbortWrite(None)
        data["members"].append({"userId": user["id"], "role": req.role})
    await asyncio.to_thread(appdb.update_project, project_id, _mut)
    return {"userId": user["id"], "role": req.role}


@app.delete("/sessions/{session_id}/projects/{project_id}/members/{member_id}", status_code=204)
async def remove_member(session_id: str, project_id: str, member_id: str, request: Request):
    await _require_session(session_id)
    _, role = await _require_project(request, project_id, write=True)
    if role != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can manage members.")

    def _mut(data):
        remaining = [m for m in data["members"] if m["userId"] != member_id]
        if len(remaining) == len(data["members"]):
            raise _NotFound()
        if not any(m["role"] == "owner" for m in remaining):
            raise appdb.AbortWrite("last-owner")  # can't orphan the project
        data["members"] = remaining
    result = await asyncio.to_thread(appdb.update_project, project_id, _mut)
    if result == "last-owner":
        raise HTTPException(status_code=422, detail="A project must keep at least one owner.")


@app.put("/sessions/{session_id}/projects/{project_id}/conventions")
async def put_conventions(session_id: str, project_id: str, req: ConventionsPut, request: Request) -> dict:
    await _require_session(session_id)
    await _require_project(request, project_id, write=True)

    def _mut(data):
        data["conventions"] = [c.strip() for c in req.conventions if c.strip()]
    await asyncio.to_thread(appdb.update_project, project_id, _mut)
    return {"conventions": req.conventions}


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
async def create_task(session_id: str, req: TaskCreate, request: Request, project: str | None = None) -> dict:
    await _require_session(session_id)
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
    await _mutate_scoped(request, project, _mut)
    return created


@app.patch("/sessions/{session_id}/tasks/{task_id}")
async def update_task(session_id: str, task_id: str, req: TaskUpdate, request: Request, project: str | None = None) -> dict:
    await _require_session(session_id)
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
    await _mutate_scoped(request, project, _mut)
    return out


@app.delete("/sessions/{session_id}/tasks/{task_id}", status_code=204)
async def delete_task(session_id: str, task_id: str, request: Request, project: str | None = None):
    await _require_session(session_id)

    def _mut(data):
        if appdb.find_task(data, task_id) is None:
            raise _NotFound()
        data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
    await _mutate_scoped(request, project, _mut)


@app.post("/sessions/{session_id}/tasks/{task_id}/subtasks", status_code=201)
async def add_subtask(session_id: str, task_id: str, req: SubtaskCreate, request: Request, project: str | None = None) -> dict:
    await _require_session(session_id)

    def _mut(data):
        t = appdb.find_task(data, task_id)
        if t is None:
            raise _NotFound()
        t.setdefault("subtasks", []).append({"text": req.text.strip(), "done": False})
    await _mutate_scoped(request, project, _mut)
    return {"status": "added"}


@app.patch("/sessions/{session_id}/tasks/{task_id}/subtasks/{index}")
async def toggle_subtask(session_id: str, task_id: str, index: int, req: SubtaskToggle, request: Request, project: str | None = None) -> dict:
    await _require_session(session_id)

    def _mut(data):
        t = appdb.find_task(data, task_id)
        subs = (t or {}).get("subtasks") or []
        if t is None or index < 0 or index >= len(subs):
            raise _NotFound()
        subs[index]["done"] = req.done
    await _mutate_scoped(request, project, _mut)
    return {"status": "ok"}


@app.delete("/sessions/{session_id}/tasks/{task_id}/subtasks/{index}")
async def delete_subtask(session_id: str, task_id: str, index: int, request: Request, project: str | None = None) -> dict:
    await _require_session(session_id)

    def _mut(data):
        t = appdb.find_task(data, task_id)
        subs = (t or {}).get("subtasks") or []
        if t is None or index < 0 or index >= len(subs):
            raise _NotFound()
        subs.pop(index)
    await _mutate_scoped(request, project, _mut)
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
async def create_event(session_id: str, req: EventCreate, request: Request, project: str | None = None) -> dict:
    await _require_session(session_id)
    created: dict = {}

    def _mut(data):
        event = {
            "id": appdb.new_id("e", data["events"]),
            "title": req.title.strip(), "date": req.date.strip(), "start": req.start.strip(),
            "end": req.end.strip(), "type": (req.type or "Meeting").strip() or "Meeting", "notes": "",
        }
        data["events"].append(event)
        created.update(event)
    await _mutate_scoped(request, project, _mut)
    return created


@app.patch("/sessions/{session_id}/events/{event_id}")
async def update_event(session_id: str, event_id: str, req: EventUpdate, request: Request, project: str | None = None) -> dict:
    await _require_session(session_id)
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
    await _mutate_scoped(request, project, _mut)
    return out


@app.delete("/sessions/{session_id}/events/{event_id}", status_code=204)
async def delete_event(session_id: str, event_id: str, request: Request, project: str | None = None):
    await _require_session(session_id)

    def _mut(data):
        if appdb.find_event(data, event_id) is None:
            raise _NotFound()
        data["events"] = [e for e in data["events"] if e["id"] != event_id]
    await _mutate_scoped(request, project, _mut)


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
async def create_schedule(session_id: str, req: ScheduleCreate) -> dict:
    await _require_session(session_id)
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
    await _mutate(_mut)
    return created


@app.patch("/sessions/{session_id}/schedules/{schedule_id}")
async def update_schedule(session_id: str, schedule_id: str, req: ScheduleUpdate) -> dict:
    await _require_session(session_id)
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
    await _mutate(_mut)
    return out


@app.delete("/sessions/{session_id}/schedules/{schedule_id}", status_code=204)
async def delete_schedule(session_id: str, schedule_id: str):
    await _require_session(session_id)

    def _mut(data):
        if appdb.find_schedule(data, schedule_id) is None:
            raise _NotFound()
        data["schedules"] = [s for s in data["schedules"] if s["id"] != schedule_id]
    await _mutate(_mut)


class SaveContentRequest(BaseModel):
    filename: str
    content: str


@app.put("/sessions/{session_id}/files/content")
async def save_file_content(session_id: str, body: SaveContentRequest) -> dict:
    """Persist an in-app edit to an existing text artifact."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
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
async def upload_file(session_id: str, file: UploadFile) -> dict:
    """Upload a document to a session's workspace."""
    try:
        await session_manager.validate_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Return service health."""
    return {"status": "ok"}
