"""FastAPI orchestrator — session CRUD, message streaming, and file upload.

Proxies all AI interactions to isolated session containers via SessionManager.
"""

import asyncio
import logging
import os
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
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    return user


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
    state["projects"] = await asyncio.to_thread(appdb.list_projects_for, uid)
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




# ── Projects — shared workspaces (membership-gated at this layer AND in tools) ──
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)


class MemberAdd(BaseModel):
    userId: str = Field(..., min_length=1, max_length=64)
    role: str = Field("viewer")


class ConventionCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=300)


async def _load_project_authed(project_id: str, uid: str, minimum: str = "viewer") -> dict:
    """Project doc if the user holds at least `minimum` role. Non-members get 404
    (membership isn't revealed); under-privileged members get 403 (explicit)."""
    project = await asyncio.to_thread(appdb.load_project, project_id)
    if project is None or appdb.member_role(project, uid) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not appdb.role_at_least(project, uid, minimum):
        raise HTTPException(status_code=403, detail=f"Requires {minimum} access")
    return project


async def _mutate_project(project_id: str, uid: str, minimum: str, mutator) -> None:
    """ETag-safe project mutation with the role re-checked INSIDE the mutator (fresh
    read each retry, so a concurrent role revocation can't be raced past)."""
    def _mut(doc):
        if appdb.member_role(doc, uid) is None:
            raise _NotFound()
        if not appdb.role_at_least(doc, uid, minimum):
            raise appdb.AbortWrite("forbidden")
        return mutator(doc)
    result = await asyncio.to_thread(appdb.update_project, project_id, _mut)
    if result == "forbidden":
        raise HTTPException(status_code=403, detail=f"Requires {minimum} access")


@app.get("/projects")
async def list_projects(uid: str = Depends(current_user)) -> list[dict]:
    return await asyncio.to_thread(appdb.list_projects_for, uid)


@app.post("/projects", status_code=201)
async def create_project(req: ProjectCreate, uid: str = Depends(current_user)) -> dict:
    project = await asyncio.to_thread(appdb.new_project, uid, req.name, req.description)
    trace_event("orchestrator", "project.created", user=uid, project=project["id"])
    return project


@app.get("/projects/{project_id}")
async def get_project(project_id: str, uid: str = Depends(current_user)) -> dict:
    return await _load_project_authed(project_id, uid)


@app.patch("/projects/{project_id}")
async def patch_project(project_id: str, req: ProjectPatch, uid: str = Depends(current_user)) -> dict:
    def _mut(doc):
        if req.name is not None:
            doc["name"] = req.name.strip()
        if req.description is not None:
            doc["description"] = req.description.strip()
        appdb.log_activity(doc, uid, "project.updated", doc["name"])
    await _mutate_project(project_id, uid, "owner", _mut)
    return await _load_project_authed(project_id, uid)


@app.post("/projects/{project_id}/members", status_code=201)
async def add_member(project_id: str, req: MemberAdd, uid: str = Depends(current_user)) -> dict:
    role = req.role.strip().lower()
    if role not in appdb.PROJECT_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {appdb.PROJECT_ROLES}")
    target = await asyncio.to_thread(appdb.get_user, req.userId.strip().lower())
    if target is None:
        raise HTTPException(status_code=422, detail="No such user")

    def _mut(doc):
        existing = next((m for m in doc["members"] if m["userId"] == target["id"]), None)
        if existing:
            existing["role"] = role
        else:
            doc["members"].append({"userId": target["id"], "role": role})
        appdb.log_activity(doc, uid, "member.added", f"{target['id']} as {role}")
    await _mutate_project(project_id, uid, "owner", _mut)
    return {"userId": target["id"], "role": role}


@app.delete("/projects/{project_id}/members/{member_id}", status_code=204)
async def remove_member(project_id: str, member_id: str, uid: str = Depends(current_user)):
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
    def _wrapped(doc):
        return _mut(doc)
    result_holder = {}
    def _outer(doc):
        if appdb.member_role(doc, uid) is None:
            raise _NotFound()
        if not appdb.role_at_least(doc, uid, "owner"):
            raise appdb.AbortWrite("forbidden")
        return _mut(doc)
    result = await asyncio.to_thread(appdb.update_project, project_id, _outer)
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Requires owner access")
    if result == "last-owner":
        raise HTTPException(status_code=422, detail="A project must keep at least one owner")


# Project-scoped record CRUD — same shapes as personal, gated editor+.
@app.post("/projects/{project_id}/tasks", status_code=201)
async def create_project_task(project_id: str, req: TaskCreate, uid: str = Depends(current_user)) -> dict:
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
    await _mutate_project(project_id, uid, "editor", _mut)
    return created


@app.patch("/projects/{project_id}/tasks/{task_id}")
async def update_project_task(project_id: str, task_id: str, req: TaskUpdate, uid: str = Depends(current_user)) -> dict:
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
    await _mutate_project(project_id, uid, "editor", _mut)
    return out


@app.delete("/projects/{project_id}/tasks/{task_id}", status_code=204)
async def delete_project_task(project_id: str, task_id: str, uid: str = Depends(current_user)):
    def _mut(doc):
        t = appdb.find_task(doc, task_id)
        if t is None:
            raise _NotFound()
        doc["tasks"] = [x for x in doc["tasks"] if x["id"] != task_id]
        appdb.log_activity(doc, uid, "task.deleted", t["title"])
    await _mutate_project(project_id, uid, "editor", _mut)


@app.post("/projects/{project_id}/events", status_code=201)
async def create_project_event(project_id: str, req: EventCreate, uid: str = Depends(current_user)) -> dict:
    created: dict = {}

    def _mut(doc):
        event = {
            "id": appdb.new_id("e", doc["events"]),
            "title": req.title.strip(), "date": req.date.strip(), "start": req.start.strip(),
            "end": req.end.strip(), "type": (req.type or "Meeting").strip() or "Meeting", "notes": "",
        }
        doc["events"].append(event)
        appdb.log_activity(doc, uid, "event.created", event["title"])
        created.update(event)
    await _mutate_project(project_id, uid, "editor", _mut)
    return created


@app.delete("/projects/{project_id}/events/{event_id}", status_code=204)
async def delete_project_event(project_id: str, event_id: str, uid: str = Depends(current_user)):
    def _mut(doc):
        e = appdb.find_event(doc, event_id)
        if e is None:
            raise _NotFound()
        doc["events"] = [x for x in doc["events"] if x["id"] != event_id]
        appdb.log_activity(doc, uid, "event.deleted", e["title"])
    await _mutate_project(project_id, uid, "editor", _mut)


@app.post("/projects/{project_id}/conventions", status_code=201)
async def add_convention(project_id: str, req: ConventionCreate, uid: str = Depends(current_user)) -> dict:
    created: dict = {}

    def _mut(doc):
        conv = {"id": appdb.new_id("c", doc.get("conventions", [])),
                "text": req.text.strip(), "createdBy": uid, "createdAt": appdb._now_iso()}
        doc.setdefault("conventions", []).append(conv)
        appdb.log_activity(doc, uid, "convention.added", conv["text"])
        created.update(conv)
    await _mutate_project(project_id, uid, "editor", _mut)
    return created


@app.delete("/projects/{project_id}/conventions/{conv_id}", status_code=204)
async def delete_convention(project_id: str, conv_id: str, uid: str = Depends(current_user)):
    def _mut(doc):
        if not any(c["id"] == conv_id for c in doc.get("conventions", [])):
            raise _NotFound()
        doc["conventions"] = [c for c in doc["conventions"] if c["id"] != conv_id]
        appdb.log_activity(doc, uid, "convention.removed", conv_id)
    await _mutate_project(project_id, uid, "editor", _mut)



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
    projects = await asyncio.to_thread(appdb.list_projects_for, uid)
    ctx = await asyncio.to_thread(appdb.load_context, uid)
    ranked = await asyncio.to_thread(
        navsvc.rank_destinations, personal, projects, ctx["visits"], None, None, 5
    )
    return [{"path": d["path"], "title": d["title"], "kind": d["kind"]} for d in ranked]

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Return service health."""
    return {"status": "ok"}
