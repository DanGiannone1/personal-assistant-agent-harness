"""Small ASGI request limits shared by the public API and session runtime."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


MAX_EDIT_CONTENT_BYTES = 2 * 1024 * 1024
# Leave room for the filename and JSON syntax around the 2 MiB editable text.
MAX_EDIT_JSON_REQUEST_BYTES = MAX_EDIT_CONTENT_BYTES + 64 * 1024
MAX_EDIT_FILENAME_CHARS = 255


def _is_json_request(scope: Scope) -> bool:
    if scope["type"] != "http":
        return False
    headers = {name.lower(): value for name, value in scope.get("headers", [])}
    content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
    return content_type == b"application/json" or content_type.endswith(b"+json")


def _is_edit_content_request(scope: Scope) -> bool:
    """Recognize the two JSON-edit endpoints even when a client omits Content-Type."""
    if scope.get("method") != "PUT":
        return False
    path = str(scope.get("path", ""))
    if path == "/files/content":
        return True
    return len(path_parts := path.strip("/").split("/")) == 4 and path_parts[0] == "sessions" and path_parts[2:] == ["files", "content"]


class JsonRequestBodyLimitMiddleware:
    """Buffer bounded JSON and edit-route bodies before FastAPI can parse or route them.

    Multipart uploads deliberately bypass this middleware and retain their own
    endpoint-specific limits. The edit routes are limited even without a JSON
    Content-Type, so a malformed client cannot make FastAPI buffer an oversized
    body before returning its normal validation error. Buffering is intentional:
    it lets chunked request bodies be rejected before endpoint parsing or side
    effects, just as an oversized Content-Length is.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_EDIT_JSON_REQUEST_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (_is_json_request(scope) or _is_edit_content_request(scope)):
            await self.app(scope, receive, send)
            return

        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                if int(raw_length) > self.max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                # The ASGI server owns malformed HTTP framing.  Still enforce
                # the observed byte count below if it forwards the request.
                pass

        body_parts: list[bytes] = []
        body_size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body = message.get("body", b"")
            body_size += len(body)
            if body_size > self.max_body_bytes:
                await self._reject(scope, receive, send)
                return
            body_parts.append(body)
            if not message.get("more_body", False):
                break

        complete_message: Message = {
            "type": "http.request",
            "body": b"".join(body_parts),
            "more_body": False,
        }
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return complete_message
            # Delegate to the real channel after the buffered body: streaming
            # responses poll receive() for client disconnects, and answering
            # with a synthetic http.disconnect here killed every SSE stream.
            return await receive()

        await self.app(scope, bounded_receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(
            status_code=413,
            content={"detail": "JSON request body exceeds the edit limit"},
        )(scope, receive, send)
