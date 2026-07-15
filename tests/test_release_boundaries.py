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
from session_manager import SessionManager, _SessionPoolAuth
from workload_auth import EntraTokenVerifier, WorkloadAuthConfig, WorkloadAuthenticator


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
    auth = _SessionPoolAuth()
    credential = Credential()
    auth._credential = credential

    async def attach() -> httpx.Request:
        flow = auth.async_auth_flow(httpx.Request("GET", "https://runtime.internal/session"))
        return await anext(flow)

    request = asyncio.run(attach())
    assert credential.scope == "api://runtime/.default"
    assert request.headers["Authorization"] == "Bearer runtime-token"


def test_dynamic_sessions_scope_is_retained_without_custom_runtime_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POOL_AUTH_AUDIENCE", raising=False)
    assert _SessionPoolAuth._token_scope() == "https://dynamicsessions.io/.default"


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


def test_scheduler_is_disabled_until_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
    assert not orchestrator._scheduler_enabled()
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    assert orchestrator._scheduler_enabled()
    monkeypatch.setenv("SCHEDULER_ENABLED", "1")
    assert not orchestrator._scheduler_enabled()


def test_runtime_image_packages_the_shared_tool_schemas() -> None:
    dockerfile = (ROOT / "session-container" / "Dockerfile").read_text()
    assert "session-container/mvp_tool_schemas.py" in dockerfile


def test_api_image_packages_navsvc_for_manual_quick_links() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "session-container/navsvc.py" in dockerfile


def test_manual_quick_links_rank_context_and_expose_only_five_safe_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    personal = {"currentRoute": "/engagements"}
    engagements = [{"id": "eng-1", "name": "Contoso"}]
    visits = [{"path": "/engagements/eng-1"}]
    ranked = [
        {"path": f"/engagements/eng-{index}", "title": f"Engagement {index}", "kind": "engagement-page", "internal": True}
        for index in range(6)
    ]
    captured: dict[str, object] = {}

    monkeypatch.setattr(orchestrator.appdb, "load_state", lambda uid: personal)
    monkeypatch.setattr(orchestrator.appdb, "list_engagements_for", lambda uid: engagements)
    monkeypatch.setattr(orchestrator.appdb, "load_context", lambda uid: {"visits": visits})

    def rank_destinations(*args: object) -> list[dict[str, object]]:
        captured["args"] = args
        return ranked

    monkeypatch.setattr(orchestrator.navsvc, "rank_destinations", rank_destinations)

    response = asyncio.run(orchestrator.quick_links("dan"))

    assert captured["args"] == (personal, engagements, visits, None, None, 5)
    assert response == [
        {"path": f"/engagements/eng-{index}", "title": f"Engagement {index}", "kind": "engagement-page"}
        for index in range(5)
    ]
