"""Focused release-boundary checks for the plain ACA runtime profile."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "session-container"))

import artifact_store
import app as orchestrator
import session_manager
from session_manager import SessionManager, _RuntimeServiceAuth
from workload_auth import EntraTokenVerifier, WorkloadAuthConfig, WorkloadAuthenticator
from workbench_core.request_limits import (
    MAX_EDIT_CONTENT_BYTES,
    MAX_EDIT_FILENAME_CHARS,
    MAX_EDIT_JSON_REQUEST_BYTES,
    JsonRequestBodyLimitMiddleware,
)


def _request(headers: dict[str, str] | None = None, path: str = "/session") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": path,
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
    })


def _config() -> WorkloadAuthConfig:
    return WorkloadAuthConfig(
        mode="entra", tenant_id="tenant-id", audience="api://runtime",
        caller_object_id="orchestrator-object-id", required_role="invoke",
    )


class _SigningKey:
    def __init__(self, key: object):
        self.key = key


class _Jwks:
    def __init__(self, key: object):
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
        return _SigningKey(self.key)


def _token(private_key: object, **overrides: object) -> str:
    claims = {
        "exp": int(time.time()) + 300,
        "iss": "https://login.microsoftonline.com/tenant-id/v2.0",
        "aud": "api://runtime",
        "tid": "tenant-id",
        "oid": "orchestrator-object-id",
        "roles": ["invoke"],
        **overrides,
    }
    if not isinstance(claims["iss"], str):
        def encode_segment(value: object) -> bytes:
            return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")

        signing_input = b".".join((
            encode_segment({"alg": "RS256", "kid": "test-key", "typ": "JWT"}),
            encode_segment(claims),
        ))
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.mark.parametrize("name", [
    "WORKLOAD_ENTRA_TENANT_ID", "WORKLOAD_ENTRA_AUDIENCE", "WORKLOAD_ENTRA_CALLER_OBJECT_ID",
])
def test_entra_workload_config_requires_all_identity_values(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv("WORKLOAD_AUTH_MODE", "entra")
    monkeypatch.setenv("WORKLOAD_ENTRA_TENANT_ID", "tenant")
    monkeypatch.setenv("WORKLOAD_ENTRA_AUDIENCE", "api://runtime")
    monkeypatch.setenv("WORKLOAD_ENTRA_CALLER_OBJECT_ID", "orchestrator")
    monkeypatch.delenv(name)
    with pytest.raises(ValueError, match=name):
        WorkloadAuthConfig.from_env().validate()


def test_workload_config_defaults_off_and_rejects_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKLOAD_AUTH_MODE", raising=False)
    assert WorkloadAuthConfig.from_env().mode == "off"
    monkeypatch.setenv("WORKLOAD_AUTH_MODE", "header")
    with pytest.raises(ValueError, match="WORKLOAD_AUTH_MODE"):
        WorkloadAuthConfig.from_env().validate()


@pytest.mark.parametrize("overrides", [
    {"tid": "another-tenant"},
    {"aud": "api://wrong-runtime"},
    {"oid": "another-orchestrator"},
    {"roles": ["other-role"]},
    {"roles": "invoke"},
    {"iss": "https://login.microsoftonline.com/another-tenant/v2.0"},
    {"iss": []},
    {"iss": 42},
    {"exp": int(time.time()) - 1},
])
def test_workload_token_rejects_wrong_tenant_audience_caller_or_role(overrides: dict[str, object]) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = EntraTokenVerifier(_config(), _Jwks(private_key.public_key()))
    authenticator = WorkloadAuthenticator(_config(), verifier)
    response = asyncio.run(authenticator.authenticate(
        _request({"Authorization": f"Bearer {_token(private_key, **overrides)}"})
    ))
    assert response is not None
    assert response.status_code == 401
    assert response.body == b'{"detail":"Unauthorized"}'


def test_workload_token_requires_bearer_and_accepts_valid_signed_token() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = EntraTokenVerifier(_config(), _Jwks(private_key.public_key()))
    authenticator = WorkloadAuthenticator(_config(), verifier)

    missing = asyncio.run(authenticator.authenticate(_request({"X-User-Id": "dan"})))
    assert missing is not None and missing.status_code == 401
    valid_request = _request({"Authorization": f"Bearer {_token(private_key)}", "X-User-Id": "dan"})
    assert asyncio.run(authenticator.authenticate(valid_request)) is None
    assert valid_request.state.workload_authenticated is True


def test_workload_auth_only_exempts_health_and_reports_jwks_connection_outage() -> None:
    class UnavailableJwks:
        def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
            raise PyJWKClientConnectionError("JWKS unavailable")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = WorkloadAuthenticator(_config(), EntraTokenVerifier(_config(), UnavailableJwks()))
    assert asyncio.run(authenticator.authenticate(_request(path="/health"))) is None
    unavailable = asyncio.run(authenticator.authenticate(
        _request({"Authorization": f"Bearer {_token(private_key)}"})
    ))
    assert unavailable is not None and unavailable.status_code == 503


def test_unknown_runtime_jwks_key_is_an_unauthorized_token() -> None:
    class MissingKeyJwks:
        def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
            raise PyJWKClientError("Unable to find a signing key")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = WorkloadAuthenticator(_config(), EntraTokenVerifier(_config(), MissingKeyJwks()))
    response = asyncio.run(authenticator.authenticate(
        _request({"Authorization": f"Bearer {_token(private_key)}"})
    ))
    assert response is not None and response.status_code == 401


def test_runtime_does_not_trust_user_header_before_entra_workload_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    import server

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        server, "workload_authenticator",
        WorkloadAuthenticator(_config(), EntraTokenVerifier(_config(), _Jwks(private_key.public_key()))),
    )
    with TestClient(server.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/session?identifier=0123456789abcdef", headers={"X-User-Id": "dan"}).status_code == 401
        assert client.get(
            "/session?identifier=0123456789abcdef",
            headers={"Authorization": f"Bearer {_token(private_key)}", "X-User-Id": "dan"},
        ).status_code == 404


def test_custom_runtime_audience_token_is_attached_for_https(monkeypatch: pytest.MonkeyPatch) -> None:
    class Credential:
        async def get_token(self, scope: str):
            self.scope = scope
            return type("Token", (), {"token": "runtime-token", "expires_on": time.time() + 300})()

    monkeypatch.setattr(session_manager, "POOL_MANAGEMENT_ENDPOINT", "https://runtime.internal")
    monkeypatch.setenv("POOL_AUTH_AUDIENCE", "api://runtime/")
    monkeypatch.setenv("POOL_AUTH", "off")
    auth = _RuntimeServiceAuth()
    credential = Credential()
    auth._credential = credential

    async def attach() -> httpx.Request:
        flow = auth.async_auth_flow(httpx.Request("GET", "https://runtime.internal/session"))
        return await anext(flow)

    request = asyncio.run(attach())
    assert credential.scope == "api://runtime/.default"
    assert request.headers["Authorization"] == "Bearer runtime-token"


def test_https_runtime_requires_a_configured_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_manager, "POOL_MANAGEMENT_ENDPOINT", "https://runtime.internal")
    monkeypatch.delenv("POOL_AUTH_AUDIENCE", raising=False)
    with pytest.raises(ValueError, match="POOL_AUTH_AUDIENCE"):
        _RuntimeServiceAuth._token_scope()


def test_local_http_runtime_skips_token_auth_without_an_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_manager, "POOL_MANAGEMENT_ENDPOINT", "http://localhost:8080")
    monkeypatch.delenv("POOL_AUTH_AUDIENCE", raising=False)
    auth = _RuntimeServiceAuth()

    async def attach() -> httpx.Request:
        flow = auth.async_auth_flow(httpx.Request("GET", "http://localhost:8080/session"))
        return await anext(flow)

    request = asyncio.run(attach())
    assert "Authorization" not in request.headers


def test_active_sources_omit_dynamic_sessions_and_legacy_trace_tools() -> None:
    banned_domain = "dynamicsessions" + ".io"
    banned_label = "Dynamic" + " Sessions"
    source_files = [ROOT / "app.py", ROOT / "session_manager.py"]
    source_files.extend((ROOT / "workbench_core").rglob("*.py"))
    source_files.extend(
        path for path in (ROOT / "session-container").rglob("*.py")
        if ".venv" not in path.parts
    )
    source_files.extend(
        path for path in (ROOT / "frontend" / "src").rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )
    for path in source_files:
        source = path.read_text(encoding="utf-8")
        assert banned_domain not in source, path
        assert banned_label not in source, path

    trace = (ROOT / "frontend" / "src" / "components" / "ToolTrace.tsx").read_text()
    for legacy_tool in (
        "create_task", "update_task", "delete_task", "add_subtask", "list_tasks",
        "create_event", "update_event", "delete_event", "list_events",
        "propose_memory", "save_memory", "delete_schedule", "write_file",
    ):
        assert legacy_tool not in trace


def test_azure_openai_token_is_not_forwarded_without_explicit_legacy_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORWARD_AZURE_OPENAI_TOKEN", raising=False)
    manager = object.__new__(SessionManager)
    assert asyncio.run(manager._get_cogservices_token()) is None


def test_entra_requires_durable_artifact_account_but_demo_allows_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARTIFACTS_ACCOUNT", raising=False)
    with pytest.raises(ValueError, match="ARTIFACTS_ACCOUNT"):
        artifact_store.assert_durable_configuration("entra")
    artifact_store.assert_durable_configuration("demo")
    monkeypatch.setenv("ARTIFACTS_ACCOUNT", "durableaccount")
    artifact_store.assert_durable_configuration("entra")


def test_legacy_personal_scheduler_and_library_surfaces_are_absent() -> None:
    routes = {route.path for route in orchestrator.app.routes}
    assert not any(route.startswith("/sessions/{session_id}/tasks") for route in routes)
    assert not any(route.startswith("/sessions/{session_id}/events") for route in routes)
    assert not any(route.startswith("/sessions/{session_id}/schedules") for route in routes)
    assert not any(route.startswith("/sessions/{session_id}/library") for route in routes)
    assert not (ROOT / "scheduler.py").exists()
    assert not (ROOT / "email_acs.py").exists()
    assert not (ROOT / "session-container" / "library.py").exists()


def test_supported_app_state_and_context_bundle_are_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    import appdb

    user = {
        "id": "dan", "username": "dan", "displayName": "Dan",
        "identity": "demo", "identitySubject": "demo:dan",
        "passwordHash": "must-not-leak",
        "persona": {"role": "Product lead", "tone": "concise", "outputPrefs": "", "language": "English"},
    }
    engagements = [{"id": "eng-product-launch", "name": "Product Launch"}]
    monkeypatch.setattr(appdb, "get_user", lambda uid: user if uid == "dan" else None)
    monkeypatch.setattr(appdb, "list_engagements_for", lambda uid: engagements if uid == "dan" else [])
    state = appdb.supported_app_state_for("dan")
    assert set(state) == {"currentRoute", "engagements", "user"}
    assert state["currentRoute"] == "/engagements"
    assert state["engagements"] == engagements
    assert state["user"] == {
        "id": "dan", "username": "dan", "displayName": "Dan", "persona": user["persona"],
    }

    async def owned(_session_id: str, _uid: str) -> None:
        return None

    monkeypatch.setattr(orchestrator, "_require_owned_session", owned)
    assert asyncio.run(orchestrator.get_app_state("0123456789abcdef", "dan")) == state

    monkeypatch.setattr(appdb, "load_engagement", lambda _pid: {
        "name": "Product Launch", "members": [{"userId": "dan", "role": "editor"}],
        "conventions": [{"id": "c-1", "text": "Use French.", "createdBy": "ava"}],
    })
    bundle = asyncio.run(orchestrator.context_bundle("/engagements/eng-product-launch", "dan"))
    assert bundle["workingContext"] == {}
    assert bundle["engagementName"] == "Product Launch"
    assert bundle["conventions"] == [{"id": "c-1", "text": "Use French.", "createdBy": "ava"}]
    assert bundle["persona"] == user["persona"]


def test_legacy_personal_state_helpers_and_runtime_proxy_are_absent() -> None:
    appdb_source = (ROOT / "session-container" / "appdb.py").read_text()
    runtime_source = (ROOT / "session-container" / "server.py").read_text()
    manager_source = (ROOT / "session_manager.py").read_text()
    for symbol in (
        "load_state", "save_state", "update_state", "load_context", "update_context",
        "record_visit", "set_working_context", "resolve_destination", "find_schedule",
        "resolve_schedule", "find_library_doc",
    ):
        assert f"def {symbol}" not in appdb_source
    assert "space-" not in appdb_source
    assert "ctx-" not in appdb_source
    assert "/app/state" not in runtime_source
    assert "def get_app_state" not in manager_source


def test_runtime_image_packages_the_shared_tool_schemas() -> None:
    dockerfile = (ROOT / "session-container" / "Dockerfile").read_text()
    assert "session-container/mvp_tool_schemas.py" in dockerfile


def test_runtime_image_packages_the_product_skill_runtime() -> None:
    dockerfile = (ROOT / "session-container" / "Dockerfile").read_text()
    assert "session-container/skill_runtime.py" in dockerfile
    assert "session-container/product-skills/" in dockerfile
    assert "session-container/skills/" not in dockerfile
    assert (ROOT / "session-container" / "product-skills" / "engagement-meeting-prep" / "SKILL.md").is_file()
    assert not (ROOT / "session-container" / "skills").exists()


def test_session_upload_profile_excludes_conversion_dependencies_and_sources() -> None:
    source = (ROOT / "session_manager.py").read_text()
    dependencies = (ROOT / "pyproject.toml").read_text()
    assert not (ROOT / "content_processing.py").exists()
    assert "ContentProcessor" not in source
    assert "content_processor" not in source
    assert "contentunderstanding" not in dependencies
    assert "file-datalake" not in dependencies


def test_shared_session_upload_policy_accepts_only_markdown() -> None:
    from workbench_core.upload_policy import is_allowed_upload

    assert is_allowed_upload("notes.md")
    assert is_allowed_upload("NOTES.MD")
    assert not is_allowed_upload("notes.txt")


def test_runtime_image_uses_a_fixed_non_root_user_and_writable_workspace() -> None:
    dockerfile = (ROOT / "session-container" / "Dockerfile").read_text()
    assert "--uid 10001" in dockerfile
    assert "chown -R 10001:10001 /app /workspace" in dockerfile
    assert "USER 10001:10001" in dockerfile


def test_session_manager_forwards_the_bound_actor_to_runtime_operations() -> None:
    calls: list[tuple[str, dict[str, str] | None]] = []

    class Response:
        status_code = 200
        def raise_for_status(self) -> None: pass
        def json(self) -> dict: return {"files": [], "content": "text"}

    class Http:
        async def get(self, url: str, *, headers: dict[str, str] | None = None):
            calls.append((f"GET {url}", headers))
            return Response()
        async def post(self, url: str, *, files: dict, headers: dict[str, str] | None = None):
            calls.append((f"POST {url}", headers))
            return Response()
        async def put(self, url: str, *, json: dict, headers: dict[str, str] | None = None):
            calls.append((f"PUT {url}", headers))
            return Response()
        async def delete(self, url: str, *, headers: dict[str, str] | None = None):
            calls.append((f"DELETE {url}", headers))
            return Response()

    manager = object.__new__(SessionManager)
    manager._http = Http()
    manager._sessions = set()
    manager._owners = {"0123456789abcdef": "dan"}
    manager._runtime_url = lambda path, sid: f"runtime{path}?identifier={sid}"

    class MarkdownUpload:
        filename = "notes.md"
        content_type = "text/markdown"
        async def read(self, _limit: int) -> bytes:
            return b"# Notes\n"

    sid = "0123456789abcdef"
    asyncio.run(manager.validate_session(sid, "dan"))
    asyncio.run(manager.list_files(sid, "dan"))
    asyncio.run(manager.get_file_content(sid, "dan", "notes.md"))
    asyncio.run(manager.save_file_content(sid, "dan", "notes.md", "text"))
    asyncio.run(manager.upload_file(sid, "dan", MarkdownUpload()))
    asyncio.run(manager.delete_session(sid, "dan"))
    assert calls and all(headers == {"X-User-Id": "dan"} for _, headers in calls)


def test_session_manager_rejects_non_markdown_before_proxying() -> None:
    calls: list[str] = []

    class Http:
        async def post(self, url: str, **kwargs: object) -> None:
            calls.append(url)
            raise AssertionError("non-Markdown uploads must not reach the runtime")

    class TextUpload:
        filename = "notes.txt"

        async def read(self, _limit: int) -> bytes:
            return b"private notes"

    manager = object.__new__(SessionManager)
    manager._http = Http()
    manager._runtime_url = lambda path, sid: f"runtime{path}?identifier={sid}"

    with pytest.raises(orchestrator.HTTPException) as exc:
        asyncio.run(manager.upload_file("0123456789abcdef", "dan", TextUpload()))
    assert exc.value.status_code == 415
    assert exc.value.detail == "Markdown (.md) files only"
    assert calls == []


def test_artifact_download_is_always_inert_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    class AllowRequest:
        async def authenticate(self, _request: Request) -> None:
            return None

    async def load_engagement(*_args: object, **_kwargs: object) -> dict:
        return {"id": "eng-1", "library": [{"id": "art-1", "name": "malicious.html", "contentType": "text/html"}]}

    monkeypatch.setattr(orchestrator, "api_authenticator", AllowRequest())
    monkeypatch.setattr(orchestrator, "_load_engagement_authed", load_engagement)
    monkeypatch.setattr(artifact_store, "get", lambda *_args: b"<script>alert(1)</script>")
    monkeypatch.setitem(orchestrator.app.dependency_overrides, orchestrator.current_user, lambda: "dan")

    client = TestClient(orchestrator.app)
    response = client.get("/engagements/eng-1/artifacts/art-1")
    client.close()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == 'attachment; filename="malicious.html"'
    assert response.headers["x-content-type-options"] == "nosniff"


def test_artifact_frontend_uses_download_anchor_without_blob_navigation() -> None:
    source = (ROOT / "frontend" / "src" / "components" / "workbench" / "EngagementScreens.tsx").read_text()
    api_source = (ROOT / "frontend" / "src" / "lib" / "api.ts").read_text()

    assert "window.open" not in source
    assert "downloadEngagementArtifact" in source
    assert "document.createElement(\"a\")" in source
    assert "anchor.download = artifact.name" in source
    assert "artifact-download-" in source
    assert "downloadEngagementArtifact" in api_source
    assert "openEngagementArtifact" not in api_source


def test_json_body_limit_rejects_declared_chunked_and_untyped_edit_bodies_before_app_execution() -> None:
    import server

    assert any(item.cls is JsonRequestBodyLimitMiddleware for item in orchestrator.app.user_middleware)
    assert any(item.cls is JsonRequestBodyLimitMiddleware for item in server.app.user_middleware)

    async def run(messages: list[dict], headers: list[tuple[bytes, bytes]], *, method: str = "POST", path: str = "/") -> tuple[list[dict], int]:
        calls = 0

        async def inner(_scope: dict, _receive: object, _send: object) -> None:
            nonlocal calls
            calls += 1

        pending = iter(messages)
        sent: list[dict] = []

        async def receive() -> dict:
            return next(pending)

        async def send(message: dict) -> None:
            sent.append(message)

        middleware = JsonRequestBodyLimitMiddleware(inner, max_body_bytes=8)
        await middleware({"type": "http", "method": method, "path": path, "headers": headers}, receive, send)
        return sent, calls

    declared, declared_calls = asyncio.run(run(
        [{"type": "http.request", "body": b"{}", "more_body": False}],
        [(b"content-type", b"application/json"), (b"content-length", b"9")],
    ))
    chunked, chunked_calls = asyncio.run(run(
        [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"6789", "more_body": False},
        ],
        [(b"content-type", b"application/json")],
    ))
    untyped_edit, untyped_edit_calls = asyncio.run(run(
        [{"type": "http.request", "body": b"123456789", "more_body": False}],
        [], method="PUT", path="/files/content",
    ))
    plain_public_edit, plain_public_edit_calls = asyncio.run(run(
        [{"type": "http.request", "body": b"123456789", "more_body": False}],
        [(b"content-type", b"text/plain")], method="PUT", path="/sessions/0123456789abcdef/files/content",
    ))

    for sent, calls in (
        (declared, declared_calls),
        (chunked, chunked_calls),
        (untyped_edit, untyped_edit_calls),
        (plain_public_edit, plain_public_edit_calls),
    ):
        assert calls == 0
        assert sent[0]["status"] == 413


def test_edit_request_models_share_filename_and_content_bounds() -> None:
    import server

    for model in (orchestrator.SaveContentRequest, server.WriteContentBody):
        properties = model.model_json_schema()["properties"]
        assert properties["filename"]["maxLength"] == MAX_EDIT_FILENAME_CHARS
        assert properties["content"]["maxLength"] == MAX_EDIT_CONTENT_BYTES


def test_runtime_bounded_write_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    workspace = tmp_path / sid
    workspace.mkdir()
    (workspace / "notes.txt").write_text("before", encoding="utf-8")
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    server._session_users[sid] = "dan"
    content = "x" * MAX_EDIT_CONTENT_BYTES

    with TestClient(server.app) as client:
        response = client.put(
            f"/files/content?identifier={sid}",
            headers={"X-User-Id": "dan"},
            json={"filename": "notes.txt", "content": content},
        )

    assert response.status_code == 200
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == content


def test_runtime_untyped_oversized_edit_body_is_rejected_before_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    workspace = tmp_path / sid
    workspace.mkdir()
    (workspace / "notes.txt").write_text("before", encoding="utf-8")
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    server._session_users[sid] = "dan"

    with TestClient(server.app) as client:
        response = client.put(
            f"/files/content?identifier={sid}",
            headers={"X-User-Id": "dan"},
            content=b"x" * (MAX_EDIT_JSON_REQUEST_BYTES + 1),
        )

    assert response.status_code == 413
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "before"


def test_runtime_upload_accepts_markdown_and_rejects_other_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    workspace = tmp_path / sid
    workspace.mkdir()
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    server._session_users[sid] = "dan"
    with TestClient(server.app) as client:
        accepted = client.post(
            f"/upload?identifier={sid}",
            headers={"X-User-Id": "dan"},
            files={"file": ("notes.md", b"# Notes\n", "text/markdown")},
        )
        rejected = client.post(
            f"/upload?identifier={sid}",
            headers={"X-User-Id": "dan"},
            files={"file": ("notes.txt", b"private notes", "text/plain")},
        )
    assert accepted.status_code == 200
    assert accepted.json()["filename"] == "notes.md"
    assert accepted.json()["path"] == "notes.md"
    assert str(tmp_path) not in accepted.json()["path"]
    assert (workspace / "notes.md").read_bytes() == b"# Notes\n"
    assert rejected.status_code == 415
    assert rejected.json() == {"detail": "Markdown (.md) files only"}
    assert not (workspace / "notes.txt").exists()


def test_runtime_session_state_and_lifecycle_endpoints_hide_other_actors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    (tmp_path / sid).mkdir()
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    server._session_users[sid] = "dan"
    with TestClient(server.app) as client:
        for method, path in (
            ("get", f"/session?identifier={sid}"),
            ("delete", f"/session?identifier={sid}"),
            ("post", f"/reset?identifier={sid}"),
        ):
            assert getattr(client, method)(path, headers={"X-User-Id": "ava"}).status_code == 404


def test_runtime_session_endpoints_reject_missing_actor_headers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    workspace = tmp_path / sid
    workspace.mkdir()
    (workspace / "notes.txt").write_text("private", encoding="utf-8")
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    server._session_users[sid] = "dan"
    with TestClient(server.app) as client:
        requests = (
            ("get", f"/session?identifier={sid}", {}),
            ("delete", f"/session?identifier={sid}", {}),
            ("post", f"/reset?identifier={sid}", {}),
            ("get", f"/files?identifier={sid}", {}),
            ("get", f"/files/content?identifier={sid}&filename=notes.txt", {}),
            ("put", f"/files/content?identifier={sid}", {"json": {"filename": "notes.txt", "content": "changed"}}),
            ("post", f"/upload?identifier={sid}", {"files": {"file": ("new.txt", b"private", "text/plain")}}),
        )
        for method, path, kwargs in requests:
            assert getattr(client, method)(path, **kwargs).status_code == 404
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "private"
    assert not (workspace / "new.txt").exists()


def test_runtime_app_state_proxy_endpoint_and_manager_method_are_absent() -> None:
    import server

    routes = {route.path for route in server.app.routes}
    assert "/app/state" not in routes
    assert not hasattr(SessionManager, "get_app_state")


def test_library_search_is_not_started_or_routed() -> None:
    source = (ROOT / "app.py").read_text()
    assert "import library" not in source
    assert "ensure_seeded_indexed" not in source
    assert '"/sessions/{session_id}/library' not in source
    assert "scheduler_loop" not in source
    assert "SCHEDULER_ENABLED" not in source
    assert "azure-communication-email" not in (ROOT / "pyproject.toml").read_text()
    assert "library.py" not in (ROOT / "Dockerfile").read_text()
    assert "library.py" not in (ROOT / "session-container" / "Dockerfile").read_text()


def test_agent_error_messages_are_fixed_and_do_not_echo_sdk_text() -> None:
    import agent
    import agent_deepagents

    secret = "provider failure includes https://internal.example/token"
    for module in (agent, agent_deepagents):
        assert module._safe_error_message(secret) == "The assistant could not complete that request. Please retry."
        assert secret not in module._safe_error_message(secret)
        assert "rate-limited" in module._safe_error_message("HTTP 429")


def test_engagement_task_validation_rejects_bad_values_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected_mutation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid request must not mutate engagement")

    monkeypatch.setattr(orchestrator, "_mutate_engagement", unexpected_mutation)
    for body in (
        orchestrator.TaskCreate(title=" ", dueDate=""),
        orchestrator.TaskCreate(title="Valid", dueDate="2026-02-30"),
    ):
        with pytest.raises(orchestrator.HTTPException) as exc:
            asyncio.run(orchestrator.create_engagement_task("eng-1", body, "dan"))
        assert exc.value.status_code == 422


def test_engagement_task_group_is_bounded_to_120_characters() -> None:
    assert len(orchestrator.TaskCreate(title="Valid", group="g" * 120).group) == 120
    assert len(orchestrator.TaskUpdate(group="g" * 120).group or "") == 120
    with pytest.raises(ValueError):
        orchestrator.TaskCreate(title="Valid", group="g" * 121)
    with pytest.raises(ValueError):
        orchestrator.TaskUpdate(group="g" * 121)


def test_deepagents_managed_identity_uses_refreshable_sync_and_async_token_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_deepagents

    model_options: list[dict] = []
    credentials: list[object] = []
    sync_credentials: list[object] = []

    class SyncCredential:
        def __init__(self) -> None:
            self.token_requests: list[str] = []
            self.closed = False
            sync_credentials.append(self)

        def get_token(self, scope: str):
            self.token_requests.append(scope)
            return type("AccessToken", (), {"token": f"sync-managed-{len(self.token_requests)}"})()

        def close(self) -> None:
            self.closed = True

    class Credential:
        def __init__(self) -> None:
            self.token_requests: list[str] = []
            self.closed = False
            credentials.append(self)

        async def get_token(self, scope: str):
            self.token_requests.append(scope)
            return type("AccessToken", (), {"token": f"managed-{len(self.token_requests)}"})()

        async def close(self) -> None:
            self.closed = True

    def build_model(**kwargs: object) -> object:
        model_options.append(kwargs)
        return object()

    monkeypatch.setenv("AZURE_ENDPOINT", "https://example.openai.azure.com/openai")
    monkeypatch.setenv("AZURE_DEPLOYMENT", "gpt-4o")
    monkeypatch.delenv("AZURE_OPENAI_TOKEN", raising=False)
    monkeypatch.setattr(agent_deepagents, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(agent_deepagents, "SyncDefaultAzureCredential", SyncCredential)
    monkeypatch.setattr(agent_deepagents, "AzureChatOpenAI", build_model)
    monkeypatch.setattr(agent_deepagents, "_build_langchain_tools", lambda *_: [])
    monkeypatch.setattr(agent_deepagents, "create_deep_agent", lambda **_: object())
    monkeypatch.setattr(agent_deepagents, "deepagents_skill_config", lambda: {})
    monkeypatch.setattr(agent_deepagents, "_user_prompt_line", lambda _: "")

    managed_session = agent_deepagents.AgentSession("/tmp", session_id="managed")
    asyncio.run(managed_session.__aenter__())
    managed_options = model_options[-1]
    assert "azure_ad_token" not in managed_options
    sync_provider = managed_options["azure_ad_token_provider"]
    async_provider = managed_options["azure_ad_async_token_provider"]
    assert credentials[0].token_requests == []
    assert sync_credentials[0].token_requests == []
    assert sync_provider() == "sync-managed-1"
    assert sync_provider() == "sync-managed-2"
    assert asyncio.run(async_provider()) == "managed-1"
    assert asyncio.run(async_provider()) == "managed-2"
    assert sync_credentials[0].token_requests == [
        "https://cognitiveservices.azure.com/.default",
        "https://cognitiveservices.azure.com/.default",
    ]
    assert credentials[0].token_requests == [
        "https://cognitiveservices.azure.com/.default",
        "https://cognitiveservices.azure.com/.default",
    ]
    assert managed_session.token is None
    asyncio.run(managed_session.__aexit__(None, None, None))
    assert credentials[0].closed
    assert sync_credentials[0].closed

    explicit_session = agent_deepagents.AgentSession("/tmp", token="explicit-token", session_id="explicit")
    asyncio.run(explicit_session.__aenter__())
    explicit_options = model_options[-1]
    assert explicit_options["azure_ad_token"] == "explicit-token"
    assert "azure_ad_token_provider" not in explicit_options
    assert "azure_ad_async_token_provider" not in explicit_options
    assert explicit_session.token == "explicit-token"

    monkeypatch.setenv("AZURE_OPENAI_TOKEN", "configured-token")
    configured_session = agent_deepagents.AgentSession("/tmp", session_id="configured")
    asyncio.run(configured_session.__aenter__())
    configured_options = model_options[-1]
    assert configured_options["azure_ad_token"] == "configured-token"
    assert "azure_ad_token_provider" not in configured_options
    assert "azure_ad_async_token_provider" not in configured_options


def test_azure_chat_openai_accepts_managed_identity_sync_and_async_providers_offline() -> None:
    from langchain_openai import AzureChatOpenAI

    def sync_provider() -> str:
        return "sync-managed-token"

    async def async_provider() -> str:
        return "async-managed-token"

    model = AzureChatOpenAI(
        azure_endpoint="https://example.openai.azure.com",
        azure_deployment="gpt-4o",
        api_version="2024-10-21",
        streaming=True,
        azure_ad_token_provider=sync_provider,
        azure_ad_async_token_provider=async_provider,
    )
    try:
        assert model.root_client._azure_ad_token_provider is sync_provider
        assert model.root_async_client._azure_ad_token_provider is async_provider
    finally:
        model.root_client.close()
        asyncio.run(model.root_async_client.close())


def test_manual_quick_link_and_visit_api_surfaces_are_absent() -> None:
    source = (ROOT / "app.py").read_text()
    routes = {route.path for route in orchestrator.app.routes}
    assert "/quicklinks" not in routes
    assert "/visits" not in routes
    assert "import navsvc" not in source
    assert "rank_destinations" not in source
    assert "record_visit" not in source
    assert "session-container/navsvc.py" not in (ROOT / "Dockerfile").read_text()
