"""FastAPI orchestrator — session CRUD, message streaming, and file upload.

Proxies all AI interactions to isolated session containers via SessionManager.
"""

import asyncio
from datetime import date
import logging
import os
import re
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Reuse the session-container's Cosmos adapter.
_SC = Path(__file__).resolve().parent / "session-container"
if str(_SC) not in sys.path:
    sys.path.insert(0, str(_SC))
import appdb  # noqa: E402
from workbench_core import EngagementService, Outcome  # noqa: E402
from workbench_core.appdb_repository import AppdbEngagementRepository  # noqa: E402
from workbench_core.request_limits import (  # noqa: E402
    MAX_EDIT_CONTENT_BYTES,
    MAX_EDIT_FILENAME_CHARS,
    JsonRequestBodyLimitMiddleware,
)

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
from identity_config import IdentityConfig
from session_manager import SessionManager
from workbench_core.trace_logging import setup_trace_logging, trace_event

logger = logging.getLogger(__name__)

_engagement_service = EngagementService(AppdbEngagementRepository(appdb), appdb.find_user)


# ---------------------------------------------------------------------------
# Globals set during lifespan
# ---------------------------------------------------------------------------
session_manager: SessionManager | None = None
api_authenticator: APIAuthenticator | None = None
identity_config: IdentityConfig | None = None


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
    global session_manager, api_authenticator, identity_config

    identity_config = IdentityConfig.from_env()
    identity_config.validate()
    artifact_store.assert_durable_configuration(identity_config.mode)

    setup_trace_logging()
    api_authenticator = APIAuthenticator(AuthConfig.from_env())

    session_manager = SessionManager()
    await session_manager.start()

    # Only a demo instance creates deterministic actors and Engagement fixtures.
    try:
        if identity_config.is_demo:
            await asyncio.to_thread(appdb.ensure_seeded, identity_config.demo_password)
            logger.info("Demo actors and engagements seeded")
        else:
            await asyncio.to_thread(appdb.validate_identity_registry, "entra", identity_config.tenant_id)
            logger.info("Entra actor registry ready without demo fixtures")
    except appdb.IdentityRegistryError:
        logger.critical("Identity registry conflicts with the selected identity mode", exc_info=True)
        raise
    except Exception:
        logger.critical("Could not initialize the required actor registry", exc_info=True)
        raise

    # Seed one real artifact per demo engagement (idempotent, best-effort) so the
    # Artifacts tab always has openable content. Bytes go through artifact_store,
    # so this works identically on the local dir and Azure Blob backends.
    try:
        if identity_config.is_demo:
            seeded_artifacts = await asyncio.to_thread(_seed_engagement_artifacts)
            if seeded_artifacts:
                logger.info("Seeded %d demo engagement artifact(s) via %s",
                            seeded_artifacts, artifact_store.describe())
    except Exception:
        logger.warning("Could not seed engagement artifacts", exc_info=True)

    logger.info("Application started")

    yield

    await session_manager.stop()
    logger.info("Application shut down")


app = FastAPI(title="CSA Workbench", lifespan=lifespan)
app.add_middleware(JsonRequestBodyLimitMiddleware)


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
    navigation_version: int = Field(default=0, ge=0)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# Auth — app-level accounts (see auth_users.py; demo-grade by design)
# ---------------------------------------------------------------------------
@app.post("/auth/login")
async def auth_login(req: LoginRequest) -> dict:
    if identity_config is None or not identity_config.is_demo:
        raise HTTPException(status_code=404, detail="Not found")
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
        await session_manager.validate_session(session_id, uid)
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
        session_manager.send_message(session_id, req.prompt, uid, req.navigation_version),
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
    files = (await session_manager.list_files(session_id, uid)).get("files", [])
    return {"session_id": session_id, "status": "active", "files": files}


@app.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, uid: str = Depends(current_user)):
    """Delete a session."""
    await _require_owned_session(session_id, uid)
    await session_manager.delete_session(session_id, uid)


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
        return await session_manager.list_files(session_id, uid)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            raise HTTPException(status_code=exc.response.status_code, detail="Failed to list files")
        raise


@app.get("/sessions/{session_id}/app/state")
async def get_app_state(session_id: str, uid: str = Depends(current_user)) -> dict:
    """Return the signed-in user's application state (rendered by the app pane)."""
    await _require_owned_session(session_id, uid)
    try:
        return await asyncio.to_thread(appdb.supported_app_state_for, uid)
    except LookupError:
        raise HTTPException(status_code=404, detail="Unknown user")


@app.get("/sessions/{session_id}/files/content")
async def get_file_content(session_id: str, filename: str, uid: str = Depends(current_user)) -> dict:
    """Get text content for a workspace file."""
    await _require_owned_session(session_id, uid)

    try:
        return await session_manager.get_file_content(session_id, uid, filename)
    except Exception as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
            try:
                detail = exc.response.json().get("detail", "Request failed")
            except Exception:
                detail = "Request failed"
            raise HTTPException(status_code=exc.response.status_code, detail=detail)
        raise


# ── Shared Engagement record helpers ─────────────────────────────────────────
class _NotFound(Exception):
    """Raised inside an Engagement mutator when the target record is absent."""


class _Forbidden(Exception):
    """Raised inside a mutator when the actor lacks the required role. Propagates like
    _NotFound so _mutate_engagement maps it to a 403 without a string sentinel."""


def _require_text(value: str, field: str) -> None:
    if not value.strip():
        raise HTTPException(status_code=422, detail=f"{field} must not be blank")


def _validate_date(value: str, field: str, *, allow_empty: bool = False) -> None:
    if allow_empty and value == "":
        return
    if len(value) != 10:
        raise HTTPException(status_code=422, detail=f"{field} must be a valid YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be a valid YYYY-MM-DD date")
    if parsed.isoformat() != value:
        raise HTTPException(status_code=422, detail=f"{field} must be a valid YYYY-MM-DD date")


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    status: str = "To do"
    priority: str = "Medium"
    group: str = Field("General", max_length=120)
    dueDate: str = ""


class TaskUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    status: str | None = None
    priority: str | None = None
    group: str | None = Field(None, max_length=120)
    dueDate: str | None = None

class SaveContentRequest(BaseModel):
    filename: str = Field(..., max_length=MAX_EDIT_FILENAME_CHARS)
    content: str = Field(..., max_length=MAX_EDIT_CONTENT_BYTES)


@app.put("/sessions/{session_id}/files/content")
async def save_file_content(session_id: str, body: SaveContentRequest, uid: str = Depends(current_user)) -> dict:
    """Persist an in-app edit to an existing text artifact."""
    await _require_owned_session(session_id, uid)
    try:
        return await session_manager.save_file_content(session_id, uid, body.filename, body.content)
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
        result = await session_manager.upload_file(session_id, uid, file)
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
            raise _Forbidden()
        return mutator(doc)

    try:
        await asyncio.to_thread(appdb.update_engagement, engagement_id, _mut)
    except _NotFound:
        raise HTTPException(status_code=404, detail="Not found")
    except _Forbidden:
        raise HTTPException(status_code=403, detail=f"Requires {minimum} access")


def _raise_for_engagement_outcome(outcome: Outcome) -> None:
    if outcome.status == "not_found":
        raise HTTPException(status_code=404, detail="Engagement not found")
    if outcome.status == "forbidden":
        raise HTTPException(status_code=403, detail=next(iter(outcome.errors.values()), "Forbidden"))
    if outcome.status == "invalid":
        raise HTTPException(status_code=422, detail=next(iter(outcome.errors.values()), "Invalid request"))
    if outcome.status == "conflict":
        raise HTTPException(status_code=409, detail="Engagement conflict")


@app.get("/engagements")
async def list_engagements(uid: str = Depends(current_user)) -> list[dict]:
    outcome = await asyncio.to_thread(_engagement_service.list, uid)
    return outcome.record["engagements"]


@app.post("/engagements", status_code=201)
async def create_engagement(req: EngagementCreate, response: Response, uid: str = Depends(current_user)) -> dict:
    outcome = await asyncio.to_thread(
        _engagement_service.create, uid,
        {"name": req.name, "description": req.description, "customer": req.customer,
         "status": req.status, "statusNote": req.statusNote,
         "startDate": req.startDate, "targetDate": req.targetDate},
    )
    _raise_for_engagement_outcome(outcome)
    engagement = outcome.record
    if outcome.status == "noop":
        response.status_code = 200
    else:
        trace_event("orchestrator", "engagement.created", user=uid, engagement=engagement["id"])
    return engagement


@app.get("/engagements/{engagement_id}")
async def get_engagement(engagement_id: str, uid: str = Depends(current_user)) -> dict:
    outcome = await asyncio.to_thread(_engagement_service.get, uid, engagement_id)
    _raise_for_engagement_outcome(outcome)
    return outcome.record


@app.patch("/engagements/{engagement_id}")
async def patch_engagement(engagement_id: str, req: EngagementPatch, uid: str = Depends(current_user)) -> dict:
    values = req.model_dump(exclude_none=True)
    outcome = await asyncio.to_thread(_engagement_service.update, uid, engagement_id, values)
    _raise_for_engagement_outcome(outcome)
    return outcome.record


@app.post("/engagements/{engagement_id}/members", status_code=201)
async def add_member(engagement_id: str, req: MemberAdd, response: Response, uid: str = Depends(current_user)) -> dict:
    outcome = await asyncio.to_thread(_engagement_service.share, uid, engagement_id, req.userId, req.role)
    _raise_for_engagement_outcome(outcome)
    if outcome.status == "noop":
        response.status_code = 200
    member = next(member for member in outcome.record["members"] if member["userId"] == outcome.target_user_id)
    return member


@app.delete("/engagements/{engagement_id}/members/{member_id}", status_code=204)
async def remove_member(engagement_id: str, member_id: str, uid: str = Depends(current_user)):
    outcome = await asyncio.to_thread(_engagement_service.remove_member, uid, engagement_id, member_id)
    _raise_for_engagement_outcome(outcome)
    return Response(status_code=204)


# Engagement-scoped task CRUD, gated editor+.
@app.post("/engagements/{engagement_id}/tasks", status_code=201)
async def create_engagement_task(engagement_id: str, req: TaskCreate, uid: str = Depends(current_user)) -> dict:
    _require_text(req.title, "title")
    _validate_date(req.dueDate, "dueDate", allow_empty=True)
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
    if req.title is not None:
        _require_text(req.title, "title")
    if req.dueDate is not None:
        _validate_date(req.dueDate, "dueDate", allow_empty=True)
    if req.status is not None and req.status not in appdb.TASK_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {appdb.TASK_STATUSES}")
    if req.priority is not None and req.priority not in appdb.TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"priority must be one of {appdb.TASK_PRIORITIES}")
    out: dict = {}

    def _mut(doc):
        t = appdb.find_engagement_task(doc, task_id)
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
        t = appdb.find_engagement_task(doc, task_id)
        if t is None:
            raise _NotFound()
        doc["tasks"] = [x for x in doc["tasks"] if x["id"] != task_id]
        appdb.log_activity(doc, uid, "task.deleted", t["title"])
    await _mutate_engagement(engagement_id, uid, "editor", _mut)


@app.post("/engagements/{engagement_id}/conventions", status_code=201)
async def add_convention(engagement_id: str, req: ConventionCreate, uid: str = Depends(current_user)) -> dict:
    _require_text(req.text, "text")
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


# ── Engagement artifacts — durable bytes with metadata on the record ──────────
# Bytes live in artifact_store (local dir or Azure Blob); members can list and
# open, while editors and owners can add or remove. Non-members always see 404.

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
    eng = await _load_engagement_authed(engagement_id, uid, "editor")
    # Read at most cap+1 bytes so an oversized body 413s without buffering it all
    # (same idiom as session_manager upload).
    data = await file.read(_ARTIFACT_MAX_BYTES + 1)
    if len(data) > _ARTIFACT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Artifact exceeds the 20MB limit")
    if not data:
        raise HTTPException(status_code=422, detail="Empty file")
    entry = {
        "id": f"art-{secrets.token_hex(8)}",
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
        await _mutate_engagement(eng["id"], uid, "editor", _mut)
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
        media_type="application/octet-stream",
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


# ── User settings — persona ──────────────────────────────────────────────────
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

    Precedence: turn instruction > engagement convention > user persona > app
    default. The bundle carries each level separately so the
    inspector can show exactly what applied and why; the frontend renders the same
    bundle into the prompt preamble, so what the user sees IS what the model got.
    """
    user = await asyncio.to_thread(appdb.get_user, uid)
    conventions: list[dict] = []
    engagement_name = None
    # An Engagement's conventions apply when the turn's view is inside that record.
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
        "workingContext": {},
        "precedence": ["turn instruction", "engagement convention", "user persona", "app default"],
    }

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Return service health."""
    return {"status": "ok"}
