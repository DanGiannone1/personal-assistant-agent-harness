from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "session-container"))

import api_auth
import auth_users
from identity_config import IdentityConfig


def request(headers: dict[str, str] | None = None, query: str = "") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/users", "query_string": query.encode(),
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()],
    })


def test_identity_config_fails_closed_but_imports_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IDENTITY_MODE", raising=False)
    config = IdentityConfig.from_env()
    assert config.mode == ""
    with pytest.raises(ValueError, match="IDENTITY_MODE"):
        config.validate()

    monkeypatch.setenv("IDENTITY_MODE", "demo")
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="DEMO_PASSWORD"):
        IdentityConfig.from_env().validate()


@pytest.mark.parametrize("mode,headers,expected", [
    ("demo", {}, None),
    ("demo", {"Authorization": "Bearer wrong-mode"}, 401),
    ("demo", {"Authorization": "Bearer x", "X-Auth-Token": "demo"}, 401),
    ("entra", {}, 401),
    ("entra", {"X-Auth-Token": "wrong-mode"}, 401),
    ("entra", {"Authorization": "Bearer x", "X-Auth-Token": "demo"}, 401),
])
def test_api_credential_mode_matrix(mode: str, headers: dict[str, str], expected: int | None) -> None:
    identity = IdentityConfig(
        mode=mode, demo_password="test-secret" if mode == "demo" else None,
        tenant_id="tenant" if mode == "entra" else None,
        api_client_id="api" if mode == "entra" else None,
        allowed_audiences=("api",) if mode == "entra" else (),
    )
    auth = api_auth.APIAuthenticator(api_auth.AuthConfig(identity, identity.tenant_id, identity.api_client_id, identity.allowed_audiences))
    result = asyncio.run(auth.authenticate(request(headers)))
    assert (result.status_code if result else None) == expected


def test_entra_api_token_requires_the_delegated_access_as_user_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = IdentityConfig(
        mode="entra", demo_password=None, tenant_id="tenant", api_client_id="api",
        allowed_audiences=("api",),
    )
    auth = api_auth.APIAuthenticator(api_auth.AuthConfig(
        identity, identity.tenant_id, identity.api_client_id, identity.allowed_audiences,
    ))

    class SigningKey:
        key = object()

    class Keys:
        def get_signing_key_from_jwt(self, _token: str) -> SigningKey:
            return SigningKey()

    auth._jwks_client = Keys()
    base_claims = {
        "tid": "tenant", "iss": "https://login.microsoftonline.com/tenant/v2.0",
    }
    monkeypatch.setattr(api_auth.jwt, "decode", lambda *_args, **_kwargs: {
        **base_claims, "scp": "openid profile access_as_user",
    })
    assert asyncio.run(auth._validate_token("token"))["scp"] == "openid profile access_as_user"

    for claims in (
        base_claims,
        {**base_claims, "scp": "openid profile"},
        {**base_claims, "roles": ["access_as_user"]},
        {**base_claims, "scp": ["access_as_user"]},
    ):
        monkeypatch.setattr(api_auth.jwt, "decode", lambda *_args, claims=claims, **_kwargs: claims)
        with pytest.raises(api_auth.InvalidTokenError):
            asyncio.run(auth._validate_token("token"))
        rejected = asyncio.run(auth.authenticate(request({"Authorization": "Bearer token"})))
        assert rejected is not None
        assert (rejected.status_code, rejected.body) == (401, b'{"detail":"Unauthorized"}')


def test_demo_and_entra_actor_resolution_rejects_dual_and_requires_tid_oid(monkeypatch: pytest.MonkeyPatch) -> None:
    auth_users._TOKENS.clear()
    auth_users._TOKENS["demo-token"] = {"userId": "dan", "issuedAt": 0 + __import__("time").time()}
    monkeypatch.setenv("IDENTITY_MODE", "demo")
    monkeypatch.setenv("DEMO_PASSWORD", "test-secret")
    assert auth_users.current_user(request({"X-Auth-Token": "demo-token"})) == "dan"

    monkeypatch.setenv("IDENTITY_MODE", "entra")
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
    auth_users._ENTRA_SEEN.clear()
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(auth_users.appdb, "ensure_entra_user", lambda tid, oid, *_: seen.append((tid, oid)))
    entra_request = request()
    entra_request.state.auth_claims = {"tid": "tenant", "oid": "object", "name": "Display"}
    assert auth_users.current_user(entra_request) == "u-object"
    assert seen == [("tenant", "object")]

    for claims in (
        {"tid": "tenant"}, {"oid": "object"}, {"tid": "other", "oid": "object"},
        {"tid": 1, "oid": "object"}, {"tid": "tenant", "oid": ["object"]},
    ):
        bad = request(); bad.state.auth_claims = claims
        with pytest.raises(HTTPException, match="Unauthorized"):
            auth_users.current_user(bad)
    dual = request({"X-Auth-Token": "demo-token"}); dual.state.auth_claims = {"tid": "tenant", "oid": "object"}
    with pytest.raises(HTTPException, match="Unauthorized"):
        auth_users.current_user(dual)


def test_clean_entra_registry_starts_without_demo_actors(monkeypatch: pytest.MonkeyPatch) -> None:
    import appdb
    from azure.cosmos import exceptions as cosmos_exceptions

    class Container:
        def __init__(self) -> None:
            self.items: dict[str, dict] = {}
        def read_item(self, *, item: str, partition_key: str) -> dict:
            if item not in self.items:
                raise cosmos_exceptions.CosmosResourceNotFoundError(message="missing", response=None)
            return self.items[item]
        def create_item(self, item: dict) -> None:
            self.items[item["id"]] = item

    container = Container()
    monkeypatch.setattr(appdb, "_container", lambda: container)
    registry = appdb._ensure_user_registry()
    assert registry["users"] == []
    assert set(container.items) == {"users"}


def test_demo_seeding_creates_actors_private_workspaces_and_shared_engagement_records(monkeypatch: pytest.MonkeyPatch) -> None:
    import appdb
    from azure.cosmos import exceptions as cosmos_exceptions

    class Container:
        def __init__(self) -> None:
            self.items: dict[str, dict] = {}

        def read_item(self, *, item: str, partition_key: str) -> dict:
            if item not in self.items:
                raise cosmos_exceptions.CosmosResourceNotFoundError(message="missing", response=None)
            return self.items[item]

        def create_item(self, item: dict) -> None:
            if item["id"] in self.items:
                raise cosmos_exceptions.CosmosResourceExistsError(message="exists", response=None)
            self.items[item["id"]] = dict(item)

        def replace_item(self, *, item: str, body: dict) -> None:
            self.items[item] = dict(body)

    container = Container()
    monkeypatch.setattr(appdb, "_container", lambda: container)
    appdb.ensure_seeded("test-secret")
    assert set(container.items) == {
        "users", "personal-dan", "personal-ava", "personal-sam",
        "eng-website-launch", "eng-product-launch", "eng-q3-budget",
    }


def test_identity_registry_rejects_mixed_mode_actor_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    import appdb

    registry = {"id": "users", "sessionId": "users", "users": [{"id": "u-object", "identity": "entra"}]}
    monkeypatch.setattr(appdb, "_ensure_user_registry", lambda: registry)
    with pytest.raises(appdb.IdentityRegistryError, match="non-demo"):
        appdb.ensure_seeded("test-secret")

    registry["users"] = [{"id": "dan", "identity": "demo"}]
    with pytest.raises(appdb.IdentityRegistryError, match="canonical"):
        appdb.validate_identity_registry("entra", "tenant")
    registry["users"] = [{"id": "u-object"}]
    with pytest.raises(appdb.IdentityRegistryError, match="canonical"):
        appdb.validate_identity_registry("entra", "tenant")
    registry["users"] = [{"id": "dan", "identity": "demo", "identitySubject": "demo:other"}]
    with pytest.raises(appdb.IdentityRegistryError, match="canonical demo"):
        appdb.validate_identity_registry("demo")


def test_entra_registry_requires_the_configured_tenant_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    import appdb

    registry = {"id": "users", "sessionId": "users", "users": [{
        "id": "u-object", "identity": "entra", "identitySubject": "tenant:object",
    }]}
    monkeypatch.setattr(appdb, "_ensure_user_registry", lambda: registry)
    assert appdb.validate_identity_registry("entra", "tenant") == registry
    for record in (
        {"id": "u-object", "identity": "entra"},
        {"id": "u-object", "identity": "entra", "identitySubject": "tenant:other"},
        {"id": "u-object", "identity": "entra", "identitySubject": "other-tenant:object"},
        {"id": "object", "identity": "entra", "identitySubject": "tenant:object"},
    ):
        registry["users"] = [record]
        with pytest.raises(appdb.IdentityRegistryError, match="canonical"):
            appdb.validate_identity_registry("entra", "tenant")


def test_runtime_session_binding_is_write_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import server

    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._session_users.clear()
    sid = "0123456789abcdef"
    server._session_users[sid] = "dan"
    same = request({"X-User-Id": "dan"}, f"identifier={sid}")
    assert server._get_user(same) == "dan"
    other = request({"X-User-Id": "ava"}, f"identifier={sid}")
    with pytest.raises(HTTPException) as exc:
        server._get_user(other)
    assert exc.value.status_code == 404


def test_actor_mismatch_keeps_original_runtime_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import server

    class OriginalSession:
        user_id = "dan"
        token = "old-token"
        raw_sdk_log_path = None
        destroyed = False
        async def __aexit__(self, *_: object) -> None:
            self.destroyed = True

    sid = "0123456789abcdef"
    original = OriginalSession()
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._sessions[sid] = original
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server._get_or_create_session("new-token", sid, "ava"))
    assert exc.value.status_code == 404
    assert server._sessions[sid] is original
    assert not original.destroyed


def test_unbound_preexisting_workspace_cannot_be_claimed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    (tmp_path / sid).mkdir()
    with TestClient(server.app) as client:
        response = client.get(f"/session?identifier={sid}", headers={"X-User-Id": "dan"})
    assert response.status_code == 404


def test_bound_workspace_file_endpoints_reject_another_actor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    workspace = tmp_path / sid
    workspace.mkdir()
    secret = workspace / "secret.txt"
    secret.write_text("dan-only", encoding="utf-8")
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    server._session_users[sid] = "dan"
    headers = {"X-User-Id": "ava"}
    with TestClient(server.app) as client:
        assert client.get(f"/files?identifier={sid}", headers=headers).status_code == 404
        assert client.get(f"/files/content?identifier={sid}&filename=secret.txt", headers=headers).status_code == 404
        assert client.put(
            f"/files/content?identifier={sid}", headers=headers,
            json={"filename": "secret.txt", "content": "overwritten"},
        ).status_code == 404
        assert client.post(
            f"/upload?identifier={sid}", headers=headers,
            files={"file": ("new.txt", b"unauthorized", "text/plain")},
        ).status_code == 404
    assert secret.read_text(encoding="utf-8") == "dan-only"
    assert not (workspace / "new.txt").exists()


def test_chat_actor_mismatch_rejects_before_acquiring_owner_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient
    import server

    sid = "0123456789abcdef"
    (tmp_path / sid).mkdir()
    monkeypatch.setattr(server, "WORKSPACE", str(tmp_path))
    server._sessions.clear()
    server._session_users.clear()
    server._session_locks.clear()
    server._session_users[sid] = "dan"
    with TestClient(server.app) as client:
        response = client.post(
            f"/chat/stream?identifier={sid}", headers={"X-User-Id": "ava"}, json={"prompt": "hello"},
        )
    assert response.status_code == 404
    lock = server._session_lock(sid)
    assert not lock.locked()

    async def acquire_and_release() -> None:
        await lock.acquire()
        lock.release()
    asyncio.run(acquire_and_release())
