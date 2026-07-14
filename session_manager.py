"""Session manager that proxies requests to ACA dynamic session containers.

Each user gets an isolated container via the ACA session pool. The orchestrator
never runs the Copilot SDK directly — it streams SSE from the session
container's /chat/stream endpoint and passes events through to the frontend.
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

from trace_logging import trace_event
from upload_policy import is_allowed_upload, normalize_markdown_filename

logger = logging.getLogger(__name__)

POOL_MANAGEMENT_ENDPOINT = os.getenv("POOL_MANAGEMENT_ENDPOINT", "")

# Session IDs are created as uuid4().hex[:16] — exactly 16 lowercase hex chars
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{16}$")

def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _agui_error(message: str) -> str:
    return _sse_event({"type": "RUN_ERROR", "message": message})


def _agui_finished() -> str:
    return _sse_event(
        {
            "type": "RUN_FINISHED",
            "thread_id": str(uuid.uuid4()),
            "run_id": str(uuid.uuid4()),
        }
    )


class _SessionPoolAuth(httpx.Auth):
    """httpx Auth that attaches a Bearer token for the ACA session pool.

    In local dev (POOL_MANAGEMENT_ENDPOINT pointing at a plain container)
    no token is needed — we skip auth when the endpoint is a bare http URL.
    """

    def __init__(self):
        self._credential: DefaultAzureCredential | None = None
        self._token: str | None = None
        self._expires_on: float = 0

    def _needs_token(self) -> bool:
        # POOL_AUTH=off: the session runtime is a plain container app (internal
        # ingress), not a Dynamic Sessions pool — no bearer to attach.
        if os.getenv("POOL_AUTH", "").lower() == "off":
            return False
        return POOL_MANAGEMENT_ENDPOINT.startswith("https://")

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
            self._credential.get_token("https://dynamicsessions.io/.default"),
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
    """Proxies session lifecycle to ACA dynamic session containers."""

    def __init__(self, content_processor=None):
        self._content_processor = content_processor
        self._auth = _SessionPoolAuth()
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
        """Get a Cognitive Services token to forward to session containers.

        Returns None for local dev (http endpoints) — session containers
        handle their own auth via AZURE_OPENAI_TOKEN env var.
        """
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
        logger.info("SessionManager started (pool=%s)", POOL_MANAGEMENT_ENDPOINT)

    async def stop(self) -> None:
        await self._http.aclose()
        await self._auth.close()
        if self._cogservices_credential:
            await self._cogservices_credential.close()
        logger.info("SessionManager stopped")

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def _pool_url(self, path: str, session_id: str) -> str:
        base = POOL_MANAGEMENT_ENDPOINT.rstrip("/")
        return f"{base}{path}?identifier={session_id}"

    async def create_session(self, user_id: str) -> dict:
        session_id = uuid.uuid4().hex[:16]

        url = self._pool_url("/session", session_id)
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

    async def validate_session(self, session_id: str) -> None:
        """Ensure session exists, probing pool state for orchestrator restarts."""
        if not _SESSION_ID_RE.match(session_id):
            raise KeyError(session_id)

        url = self._pool_url("/session", session_id)
        resp = await self._http.get(url)
        # Only a genuine 404 means "this session is gone" (→ caller returns 404 and the
        # frontend may start fresh). Transient pool/auth/network failures must NOT be
        # masked as 404 — that would make the frontend silently discard a valid session.
        # Let them propagate (caller surfaces a 5xx the client can retry).
        if resp.status_code == 404:
            raise KeyError(session_id)
        resp.raise_for_status()
        self._sessions.add(session_id)

    async def delete_session(self, session_id: str) -> None:
        """Delete session and best-effort reset container context."""
        self._sessions.discard(session_id)
        self._owners.pop(session_id, None)
        reset_url = self._pool_url("/session", session_id)
        try:
            resp = await self._http.delete(reset_url)
            if resp.status_code == 404:
                return
            resp.raise_for_status()
        except Exception:
            logger.warning("Session reset failed for %s during delete", session_id, exc_info=True)

    async def send_message(self, session_id: str, prompt: str, user_id: str) -> AsyncGenerator[str, None]:
        """Stream SSE events from the session container to the frontend."""
        try:
            stream_url = self._pool_url("/chat/stream", session_id)

            cogservices_token = await self._get_cogservices_token()
            chat_body = {"prompt": prompt}
            # The agent always runs AS a specific user — tools scope to that user's state.
            headers = {"X-User-Id": user_id}
            if cogservices_token:
                headers["X-Cogservices-Token"] = cogservices_token

            async with self._http.stream("POST", stream_url, json=chat_body, headers=headers) as resp:
                if resp.status_code == 409:
                    yield _agui_error("Session is busy. Wait for the current response to finish and retry.")
                    yield _agui_finished()
                    return

                if resp.status_code >= 400:
                    await resp.aread()
                    try:
                        detail = resp.json().get("detail")
                    except Exception:
                        detail = None
                    logger.error(
                        "Session container returned %s for %s: %s",
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
                    yield _agui_finished()
                    return

                # Pass the SSE stream through unmodified (frame on the blank line),
                # rather than per-line strip/rejoin which would corrupt any future
                # multi-line event payload. Use an incremental UTF-8 decoder so a
                # multi-byte char (e.g. an em-dash) split across network chunks isn't
                # mangled into replacement characters.
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                saw_terminal = False
                carry = ""  # tail carryover so a terminal token split across chunks is still seen
                async for chunk in resp.aiter_raw():
                    if chunk:
                        text = decoder.decode(chunk)
                        if text:
                            scan = carry + text
                            if "RUN_FINISHED" in scan or "RUN_ERROR" in scan:
                                saw_terminal = True
                            carry = scan[-32:]
                            yield text
                tail = decoder.decode(b"", final=True)
                if tail:
                    if "RUN_FINISHED" in (carry + tail) or "RUN_ERROR" in (carry + tail):
                        saw_terminal = True
                    yield tail

                # Fail loud: a truncated upstream stream (clean close mid-turn, container
                # recycle) must not leave the client hanging in "thinking" forever.
                if not saw_terminal:
                    logger.error("Upstream stream for %s ended with no terminal event", session_id)
                    yield _agui_error("The assistant stopped responding unexpectedly. Please retry.")
                    yield _agui_finished()

        except Exception:
            logger.exception("send_message failed for session %s", session_id)
            yield _agui_error("Internal server error")
            yield _agui_finished()

    async def upload_file(self, session_id: str, upload_file: UploadFile) -> dict:
        """Proxy a file upload to the session container, then run CU processing."""
        upload_endpoint = self._pool_url("/upload", session_id)
        max_bytes = 50 * 1024 * 1024  # 50 MB — match session container limit
        content = await upload_file.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="File too large (50 MB limit)")

        filename = Path(upload_file.filename or "upload").name
        if not is_allowed_upload(filename):
            ext = Path(filename).suffix.lower() or "(none)"
            raise HTTPException(status_code=400, detail=f"File type '{ext}' not allowed")

        markdown_filename = normalize_markdown_filename(filename)

        # Normalize already-markdown uploads so we keep only a single `.md` artifact.
        # For non-markdown uploads, run document conversion and forward the markdown
        # result back to the container. For markdown uploads, skip conversion and
        # forward the provided content directly.
        is_markdown_upload = filename.lower().endswith(".md")

        content_type = upload_file.content_type or "application/octet-stream"
        markdown_upload_result: dict | None = None

        async def forward_markdown(md_filename: str, md_bytes: bytes) -> dict:
            """Upload the converted markdown to the session container."""
            nonlocal markdown_upload_result
            md_url = upload_endpoint
            md_files = {"file": (md_filename, md_bytes, "text/markdown")}
            md_resp = await self._http.post(md_url, files=md_files)
            md_resp.raise_for_status()
            markdown_upload_result = md_resp.json()
            return markdown_upload_result

        if is_markdown_upload:
            upload_result = await forward_markdown(markdown_filename, content)
            markdown_upload_result = upload_result
            trace_event(
                "orchestrator",
                "fs.upload",
                session_id=session_id,
                filename=markdown_filename,
                size=len(content),
                status="converted",  # markdown path only
                direct_markdown=True,
            )
            return {
                **upload_result,
                "markdown_ready": True,
                "source_filename": filename,
            }

        if not (self._content_processor and self._content_processor.enabled):
            raise HTTPException(
                status_code=503,
                detail="Document processing is not available. Azure Content Understanding and ADLS must be configured.",
            )

        proc = await self._content_processor.process_document(
            session_id=session_id,
            filename=filename,
            file_bytes=content,
            content_type=content_type,
            markdown_filename=markdown_filename,
            forward_markdown_fn=forward_markdown,
        )
        if not proc["markdown_forwarded"]:
            trace_event(
                "orchestrator",
                "fs.upload_failed",
                session_id=session_id,
                filename=markdown_filename,
                source_filename=filename,
                size=len(content),
                error=proc.get("error"),
                error_code=proc.get("error_code"),
                diagnostic=proc.get("diagnostic"),
                markdown_size=proc.get("markdown_size"),
                markdown_preview=proc.get("markdown_preview"),
                adls_original=proc.get("adls_original"),
                adls_markdown=proc.get("adls_markdown"),
            )
            if proc.get("error_code") == "protected_pdf":
                raise HTTPException(
                    status_code=422,
                    detail=proc.get("error") or "Protected PDF could not be converted.",
                )
            raise HTTPException(
                status_code=500,
                detail=proc.get("error") or "Document conversion failed. Please try again.",
            )

        trace_event(
            "orchestrator",
            "fs.upload",
            session_id=session_id,
            filename=markdown_filename,
            size=len(content),
            status="converted",
            source_filename=filename,
            adls_original=proc.get("adls_original"),
            adls_markdown=proc.get("adls_markdown"),
            markdown_size=proc.get("markdown_size"),
            markdown_preview=proc.get("markdown_preview"),
            diagnostic=proc.get("diagnostic"),
        )
        return {
            "path": (markdown_upload_result or {}).get("path"),
            "filename": markdown_filename,
            "size": (markdown_upload_result or {}).get(
                "size",
                proc.get("markdown_size", len(content)),
            ),
            "markdown_ready": True,
            "source_filename": filename,
        }

    async def list_files(self, session_id: str) -> dict:
        """Proxy GET /files to the session container."""
        url = self._pool_url("/files", session_id)
        resp = await self._http.get(url)
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

    async def get_app_state(self, session_id: str) -> dict:
        """Proxy GET /app/state to the session container (Tax Workbench state)."""
        url = self._pool_url("/app/state", session_id)
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.json()

    async def get_file_content(self, session_id: str, filename: str) -> dict:
        """Proxy GET /files/content to the session container."""
        from urllib.parse import quote
        trace_event("orchestrator", "fs.content_request", session_id=session_id, filename=filename)
        url = self._pool_url("/files/content", session_id)
        # Append filename directly to preserve the identifier param already in the URL.
        # httpx params= replaces the entire query string, which would drop identifier.
        try:
            resp = await self._http.get(f"{url}&filename={quote(filename, safe='')}")
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

    async def save_file_content(self, session_id: str, filename: str, content: str) -> dict:
        """Proxy PUT /files/content (in-app artifact edit) to the session container."""
        trace_event("orchestrator", "fs.content_write", session_id=session_id, filename=filename)
        url = self._pool_url("/files/content", session_id)
        resp = await self._http.put(url, json={"filename": filename, "content": content})
        resp.raise_for_status()
        return resp.json()
