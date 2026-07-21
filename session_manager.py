"""Session manager that proxies requests to the internal runtime service.

The orchestrator never runs an agent SDK directly — it streams SSE from the
runtime's /chat/stream endpoint and passes events through to the frontend.
"""

import asyncio
import codecs
import json
import logging
import os
import re
from pathlib import Path
import uuid
from collections.abc import AsyncGenerator

import httpx
from fastapi import HTTPException
from azure.identity.aio import DefaultAzureCredential
from fastapi import UploadFile

from workbench_core.trace_logging import trace_event
from workbench_core.upload_policy import is_allowed_upload

logger = logging.getLogger(__name__)

POOL_MANAGEMENT_ENDPOINT = os.getenv("POOL_MANAGEMENT_ENDPOINT", "")

# Session IDs are created as uuid4().hex[:16] — exactly 16 lowercase hex chars
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{16}$")

def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _agui_error(message: str) -> str:
    return _sse_event({"type": "RUN_ERROR", "message": message})


def _parse_sse_frame(frame: str) -> dict:
    """Validate one complete SSE data frame without searching raw stream text."""
    data_lines = [line[5:].lstrip() for line in frame.replace("\r\n", "\n").split("\n") if line.startswith("data:")]
    if len(data_lines) != 1:
        raise ValueError("expected exactly one data line")
    event = json.loads(data_lines[0])
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise ValueError("missing event type")
    return event


_KNOWN_EVENT_TYPES = {
    "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
    "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_RESULT", "TOOL_CALL_END",
    "NAVIGATION_RESOLVED", "RUN_FINISHED", "RUN_ERROR", "REASONING_START",
    "REASONING_DELTA", "REASONING_END",
}


class _UpstreamEventValidator:
    def __init__(self) -> None:
        self.started = False
        self.terminal = False
        self.run_id: str | None = None
        self.thread_id: str | None = None
        self.open_message: str | None = None
        self.tools: dict[str, dict] = {}

    @staticmethod
    def _string(event: dict, name: str) -> str:
        value = event.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"missing {name}")
        return value

    def validate(self, event: dict) -> str:
        event_type = event.get("type")
        if event_type not in _KNOWN_EVENT_TYPES:
            raise ValueError("unknown event type")
        if self.terminal:
            raise ValueError("event after terminal")
        if not self.started and event_type != "RUN_STARTED":
            raise ValueError("stream must start with RUN_STARTED")
        if event_type == "RUN_STARTED":
            if self.started:
                raise ValueError("duplicate RUN_STARTED")
            self.run_id = self._string(event, "run_id"); self.thread_id = self._string(event, "thread_id"); self.started = True
        elif event_type == "TEXT_MESSAGE_START":
            if self.open_message: raise ValueError("overlapping text")
            self.open_message = self._string(event, "message_id"); self._string(event, "role")
        elif event_type == "TEXT_MESSAGE_CONTENT":
            if self._string(event, "message_id") != self.open_message: raise ValueError("text content without matching start")
            self._string(event, "delta")
        elif event_type == "TEXT_MESSAGE_END":
            if self._string(event, "message_id") != self.open_message: raise ValueError("text end without matching start")
            self.open_message = None
        elif event_type == "TOOL_CALL_START":
            call_id = self._string(event, "tool_call_id")
            if call_id in self.tools: raise ValueError("duplicate tool start")
            self.tools[call_id] = {"phase": "started", "navigated": False}; self._string(event, "tool_call_name")
        elif event_type in {"TOOL_CALL_ARGS", "TOOL_CALL_RESULT"}:
            call_id = self._string(event, "tool_call_id")
            if self.tools.get(call_id, {}).get("phase") != "started":
                raise ValueError("tool event before start")
            if event_type == "TOOL_CALL_RESULT":
                result = event.get("result")
                if not isinstance(result, dict):
                    raise ValueError("missing tool result")
                self._string(result, "status"); self._string(result, "code"); self._string(result, "operation")
                self.tools[call_id] = {"phase": "result", "result": result, "navigated": False}
        elif event_type == "TOOL_CALL_END":
            call_id = self._string(event, "tool_call_id")
            if self.tools.get(call_id, {}).get("phase") != "result": raise ValueError("tool end before result")
            del self.tools[call_id]
        elif event_type == "RUN_FINISHED":
            if self._string(event, "run_id") != self.run_id or self._string(event, "thread_id") != self.thread_id: raise ValueError("terminal run mismatch")
            if self.tools or self.open_message: raise ValueError("terminal with open lifecycle")
            self.terminal = True
        elif event_type == "RUN_ERROR":
            self._string(event, "message")
            if self.tools or self.open_message: raise ValueError("terminal with open lifecycle")
            self.terminal = True
        elif event_type == "NAVIGATION_RESOLVED":
            if self._string(event, "runId") != self.run_id: raise ValueError("navigation run mismatch")
            if not isinstance(event.get("requestedAtNavigationVersion"), int):
                raise ValueError("missing requestedAtNavigationVersion")
            if not isinstance(event.get("destination"), dict):
                raise ValueError("missing destination")
            matches = [tool for tool in self.tools.values() if tool.get("phase") == "result" and not tool.get("navigated") and tool["result"].get("status") in {"resolved", "committed"} and tool["result"].get("destination") == event["destination"]]
            if len(matches) != 1:
                raise ValueError("navigation is not bound to a resolved tool result")
            matches[0]["navigated"] = True
        return event_type

    def interruption_closures(self) -> list[dict]:
        closures: list[dict] = []
        if self.open_message:
            closures.append({"type": "TEXT_MESSAGE_END", "message_id": self.open_message})
            self.open_message = None
        for call_id, tool in list(self.tools.items()):
            if tool.get("phase") == "started":
                closures.append({"type": "TOOL_CALL_RESULT", "tool_call_id": call_id, "result": {"status": "failed", "code": "tool.stream_interrupted", "operation": "unknown", "message": "Tool stream interrupted."}})
            closures.append({"type": "TOOL_CALL_END", "tool_call_id": call_id})
            del self.tools[call_id]
        return closures


def _pop_sse_frame(buffer: str) -> tuple[str | None, str]:
    """Return one complete LF/CRLF-delimited frame while retaining partial data."""
    separator = re.search(r"\r?\n\r?\n", buffer)
    if separator is None:
        return None, buffer
    return buffer[:separator.start()], buffer[separator.end():]


class _RuntimeServiceAuth(httpx.Auth):
    """httpx Auth that attaches a Bearer token for the internal runtime service.

    In local dev (POOL_MANAGEMENT_ENDPOINT pointing at the plain HTTP runtime)
    no token is needed — we skip auth when the endpoint is a bare http URL.
    """

    def __init__(self):
        self._credential: DefaultAzureCredential | None = None
        self._token: str | None = None
        self._expires_on: float = 0

    def _needs_token(self) -> bool:
        # Plain HTTP is the explicit local profile. HTTPS calls are deployment
        # workload calls and must always carry an identity token; POOL_AUTH=off
        # is intentionally not a production bypass.
        return POOL_MANAGEMENT_ENDPOINT.startswith("https://")

    @staticmethod
    def _token_scope() -> str:
        audience = os.getenv("POOL_AUTH_AUDIENCE", "").strip().rstrip("/")
        if not audience:
            raise ValueError("POOL_AUTH_AUDIENCE is required for HTTPS internal runtime requests")
        if audience.endswith("/.default"):
            audience = audience[:-len("/.default")]
        if not audience:
            raise ValueError("POOL_AUTH_AUDIENCE must not be empty or only '/.default'")
        return f"{audience}/.default"

    async def _refresh(self) -> None:
        import time

        if not self._needs_token():
            return
        if self._token and time.time() < self._expires_on - 60:
            return
        if self._credential is None:
            self._credential = DefaultAzureCredential(
                managed_identity_client_id=os.getenv("AZURE_CLIENT_ID") or None,
            )
        tok = await asyncio.wait_for(
            self._credential.get_token(self._token_scope()),
            timeout=30,
        )
        self._token = tok.token
        self._expires_on = tok.expires_on

    async def async_auth_flow(self, request):
        await self._refresh()
        if self._token:
            request.headers["Authorization"] = f"Bearer {self._token}"
        yield request

    async def close(self) -> None:
        if self._credential:
            await self._credential.close()


class SessionManager:
    """Proxies session lifecycle to the internal runtime service."""

    def __init__(self):
        self._auth = _RuntimeServiceAuth()
        self._http = httpx.AsyncClient(
            auth=self._auth,
            timeout=httpx.Timeout(connect=10, read=600, write=10, pool=10),
        )
        self._sessions: set[str] = set()
        # Session ownership: sid -> user id. In-memory like the session set itself —
        # a restart drops both, and the frontend re-creates (demo-grade, documented).
        self._owners: dict[str, str] = {}
        self._cogservices_credential: DefaultAzureCredential | None = None
        self._cogservices_token: str | None = None
        self._cogservices_expires_on: float = 0

    async def _get_cogservices_token(self) -> str | None:
        """Get a Cognitive Services token to forward to the internal runtime.

        Returns None for local dev (http endpoints) — the internal runtime
        handle their own auth via AZURE_OPENAI_TOKEN env var.
        """
        if os.getenv("FORWARD_AZURE_OPENAI_TOKEN", "").lower() != "true":
            return None

        import time

        if not POOL_MANAGEMENT_ENDPOINT.startswith("https://"):
            return None
        if self._cogservices_token and time.time() < self._cogservices_expires_on - 60:
            return self._cogservices_token
        if self._cogservices_credential is None:
            self._cogservices_credential = DefaultAzureCredential(
                managed_identity_client_id=os.getenv("AZURE_CLIENT_ID") or None,
            )
        tok = await asyncio.wait_for(
            self._cogservices_credential.get_token(
                "https://cognitiveservices.azure.com/.default"
            ),
            timeout=30,
        )
        self._cogservices_token = tok.token
        self._cogservices_expires_on = tok.expires_on
        return self._cogservices_token

    async def start(self) -> None:
        logger.info("SessionManager started (runtime=%s)", POOL_MANAGEMENT_ENDPOINT)

    async def stop(self) -> None:
        await self._http.aclose()
        await self._auth.close()
        if self._cogservices_credential:
            await self._cogservices_credential.close()
        logger.info("SessionManager stopped")

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def _runtime_url(self, path: str, session_id: str) -> str:
        base = POOL_MANAGEMENT_ENDPOINT.rstrip("/")
        return f"{base}{path}?identifier={session_id}"

    async def create_session(self, user_id: str) -> dict:
        session_id = uuid.uuid4().hex[:16]

        url = self._runtime_url("/session", session_id)
        resp = await self._http.post(
            url,
            timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
            headers={"X-User-Id": user_id},
        )
        resp.raise_for_status()

        self._sessions.add(session_id)
        self._owners[session_id] = user_id
        logger.info("Created session %s (user=%s)", session_id, user_id)
        return {
            "session_id": session_id,
            "status": "active",
            "user_id": user_id,
        }

    def session_owner(self, session_id: str) -> str | None:
        return self._owners.get(session_id)

    @staticmethod
    def _actor_headers(user_id: str) -> dict[str, str]:
        return {"X-User-Id": user_id}

    async def validate_session(self, session_id: str, user_id: str) -> None:
        """Ensure session exists, probing runtime state for orchestrator restarts."""
        if not _SESSION_ID_RE.match(session_id):
            raise KeyError(session_id)

        url = self._runtime_url("/session", session_id)
        resp = await self._http.get(url, headers=self._actor_headers(user_id))
        # Only a genuine 404 means "this session is gone" (→ caller returns 404 and the
        # frontend may start fresh). Transient runtime/auth/network failures must NOT be
        # masked as 404 — that would make the frontend silently discard a valid session.
        # Let them propagate (caller surfaces a 5xx the client can retry).
        if resp.status_code == 404:
            raise KeyError(session_id)
        resp.raise_for_status()
        self._sessions.add(session_id)

    async def delete_session(self, session_id: str, user_id: str | None = None) -> None:
        """Delete session and best-effort reset container context."""
        self._sessions.discard(session_id)
        actor_id = user_id or self._owners.get(session_id)
        self._owners.pop(session_id, None)
        if actor_id is None:
            # A runtime request without a bound actor would bypass its ownership
            # check.  After an orchestrator restart, leave that stale runtime
            # session for normal expiry rather than deleting it unsafely.
            logger.warning("Skipped deleting unowned session %s", session_id)
            return
        reset_url = self._runtime_url("/session", session_id)
        try:
            resp = await self._http.delete(reset_url, headers=self._actor_headers(actor_id))
            if resp.status_code == 404:
                return
            resp.raise_for_status()
        except Exception:
            logger.warning("Session reset failed for %s during delete", session_id, exc_info=True)

    async def send_message(self, session_id: str, prompt: str, user_id: str, navigation_version: int = 0) -> AsyncGenerator[str, None]:
        """Stream SSE events from the internal runtime to the frontend."""
        validator: _UpstreamEventValidator | None = None
        pending_terminal_frame: str | None = None
        try:
            stream_url = self._runtime_url("/chat/stream", session_id)

            cogservices_token = await self._get_cogservices_token()
            chat_body = {"prompt": prompt, "navigation_version": navigation_version}
            # The agent always runs AS a specific user — tools scope to that user's state.
            headers = self._actor_headers(user_id)
            if cogservices_token:
                headers["X-Cogservices-Token"] = cogservices_token

            async with self._http.stream("POST", stream_url, json=chat_body, headers=headers) as resp:
                if resp.status_code == 409:
                    yield _agui_error("Session is busy. Wait for the current response to finish and retry.")
                    return

                if resp.status_code >= 400:
                    await resp.aread()
                    try:
                        detail = resp.json().get("detail")
                    except Exception:
                        detail = None
                    logger.error(
                        "Internal runtime returned %s for %s: %s",
                        resp.status_code, session_id, detail,
                    )
                    # Sanitize: hide internal details for 5xx; for 4xx forward only a clean
                    # JSON `detail` string (never raw resp.text — could be an HTML/error page).
                    if resp.status_code >= 500:
                        yield _agui_error("Session error: an internal error occurred. Please retry.")
                    elif isinstance(detail, str) and detail:
                        yield _agui_error(f"Session error: {detail}")
                    else:
                        yield _agui_error("Session error: the request could not be completed.")
                    return

                # Frame first, then validate required JSON event types.  Do not infer
                # terminal state from byte substrings: tokens can be split across chunks.
                decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
                buffer = ""
                validator = _UpstreamEventValidator()
                terminal: str | None = None
                stream_error: str | None = None
                async for chunk in resp.aiter_raw():
                    if chunk:
                        try:
                            buffer += decoder.decode(chunk)
                        except UnicodeDecodeError:
                            stream_error = "The assistant stream was malformed. Please retry."
                            break
                        while True:
                            frame, buffer = _pop_sse_frame(buffer)
                            if frame is None:
                                break
                            if not frame.strip():
                                continue
                            try:
                                event = _parse_sse_frame(frame)
                            except (ValueError, json.JSONDecodeError):
                                stream_error = "The assistant stream was malformed. Please retry."
                                break
                            try:
                                event_type = validator.validate(event)
                            except ValueError:
                                stream_error = "The assistant stream ended incorrectly. Please retry."
                                break
                            if event_type in {"RUN_FINISHED", "RUN_ERROR"}:
                                terminal = event_type
                                # Hold the terminal until clean EOF proves it is unique.
                                pending_terminal_frame = frame + "\n\n"
                            else:
                                yield frame + "\n\n"
                        if stream_error:
                            break
                try:
                    buffer += decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    stream_error = "The assistant stream was malformed. Please retry."
                if buffer.strip() and not stream_error:
                    stream_error = "The assistant stream ended unexpectedly. Please retry."
                if stream_error or terminal is None:
                    logger.error("Invalid upstream stream for %s: %s", session_id, stream_error or "missing terminal")
                    for closure in validator.interruption_closures():
                        yield _sse_event(closure)
                    yield _agui_error(stream_error or "The assistant stopped responding unexpectedly. Please retry.")
                elif pending_terminal_frame is not None:
                    yield pending_terminal_frame

        except Exception:
            logger.exception("send_message failed for session %s", session_id)
            if pending_terminal_frame is not None:
                yield pending_terminal_frame
                return
            if validator is not None and validator.terminal:
                return
            if validator is not None and validator.started and not validator.terminal:
                for closure in validator.interruption_closures():
                    yield _sse_event(closure)
            yield _agui_error("Internal server error")

    async def upload_file(self, session_id: str, user_id: str, upload_file: UploadFile) -> dict:
        """Proxy a validated Markdown upload to the internal runtime service."""
        upload_endpoint = self._runtime_url("/upload", session_id)
        max_bytes = 50 * 1024 * 1024  # 50 MB — match runtime limit

        filename = Path(upload_file.filename or "upload").name
        if not is_allowed_upload(filename):
            raise HTTPException(status_code=415, detail="Markdown (.md) files only")

        content = await upload_file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="File too large (50 MB limit)")

        response = await self._http.post(
            upload_endpoint,
            files={"file": (filename, content, "text/markdown")},
            headers=self._actor_headers(user_id),
        )
        response.raise_for_status()

        trace_event(
            "orchestrator",
            "fs.upload",
            session_id=session_id,
            filename=filename,
            size=len(content),
            status="uploaded",
        )
        return {
            **response.json(),
            "markdown_ready": True,
        }

    async def list_files(self, session_id: str, user_id: str) -> dict:
        """Proxy GET /files to the internal runtime."""
        url = self._runtime_url("/files", session_id)
        resp = await self._http.get(url, headers=self._actor_headers(user_id))
        resp.raise_for_status()
        result = resp.json()
        files = result.get("files", [])
        trace_event(
            "orchestrator",
            "fs.list",
            session_id=session_id,
            file_count=len(files),
            filenames=[f["filename"] for f in files],
        )
        return result

    async def get_file_content(self, session_id: str, user_id: str, filename: str) -> dict:
        """Proxy GET /files/content to the internal runtime."""
        from urllib.parse import quote
        trace_event("orchestrator", "fs.content_request", session_id=session_id, filename=filename)
        url = self._runtime_url("/files/content", session_id)
        # Append filename directly to preserve the identifier param already in the URL.
        # httpx params= replaces the entire query string, which would drop identifier.
        try:
            resp = await self._http.get(
                f"{url}&filename={quote(filename, safe='')}",
                headers=self._actor_headers(user_id),
            )
            resp.raise_for_status()
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            trace_event(
                "orchestrator",
                "fs.content_error",
                session_id=session_id,
                filename=filename,
                status=status,
                error=str(exc),
            )
            raise
        result = resp.json()
        trace_event(
            "orchestrator",
            "fs.content_response",
            session_id=session_id,
            filename=filename,
            size=result.get("size"),
            mime_type=result.get("mime_type"),
        )
        return result

    async def save_file_content(self, session_id: str, user_id: str, filename: str, content: str) -> dict:
        """Proxy PUT /files/content (in-app artifact edit) to the internal runtime."""
        trace_event("orchestrator", "fs.content_write", session_id=session_id, filename=filename)
        url = self._runtime_url("/files/content", session_id)
        resp = await self._http.put(
            url, json={"filename": filename, "content": content},
            headers=self._actor_headers(user_id),
        )
        resp.raise_for_status()
        return resp.json()
