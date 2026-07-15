"""Authentication for orchestrator-to-runtime workload calls.

The session runtime has no browser-facing identity surface.  In the Entra
release profile it accepts only a token issued to the configured orchestrator
workload identity; local development explicitly uses the default ``off`` mode.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import InvalidTokenError, PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

logger = logging.getLogger(__name__)


def _env_value(name: str) -> str | None:
    return (os.getenv(name) or "").strip() or None


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class WorkloadAuthConfig:
    mode: str
    tenant_id: str | None
    audience: str | None
    caller_object_id: str | None
    required_role: str

    @classmethod
    def from_env(cls) -> "WorkloadAuthConfig":
        return cls(
            mode=(os.getenv("WORKLOAD_AUTH_MODE") or "off").strip().lower(),
            tenant_id=_env_value("WORKLOAD_ENTRA_TENANT_ID"),
            audience=_env_value("WORKLOAD_ENTRA_AUDIENCE"),
            caller_object_id=_env_value("WORKLOAD_ENTRA_CALLER_OBJECT_ID"),
            required_role=(os.getenv("WORKLOAD_ENTRA_REQUIRED_ROLE") or "invoke").strip(),
        )

    @property
    def is_entra(self) -> bool:
        return self.mode == "entra"

    def validate(self) -> None:
        if self.mode not in {"off", "entra"}:
            raise ValueError("WORKLOAD_AUTH_MODE must be exactly 'off' or 'entra'")
        if not self.is_entra:
            return
        missing = [
            name for name, value in (
                ("WORKLOAD_ENTRA_TENANT_ID", self.tenant_id),
                ("WORKLOAD_ENTRA_AUDIENCE", self.audience),
                ("WORKLOAD_ENTRA_CALLER_OBJECT_ID", self.caller_object_id),
                ("WORKLOAD_ENTRA_REQUIRED_ROLE", self.required_role),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"missing required workload authentication configuration: {', '.join(missing)}")


class EntraTokenVerifier:
    """Validate an Entra access token using the tenant JWKS endpoint."""

    def __init__(self, config: WorkloadAuthConfig, jwks_client: Any | None = None):
        self.config = config
        self._jwks_client = jwks_client or PyJWKClient(
            f"https://login.microsoftonline.com/{config.tenant_id}/discovery/v2.0/keys"
        )

    async def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError:
            raise
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or not header["kid"]:
            raise InvalidTokenError("Unsupported token signing header")

        try:
            signing_key = await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)
        except PyJWKClientConnectionError:
            raise
        except PyJWKClientError as exc:
            raise InvalidTokenError("Unknown token signing key") from exc
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.config.audience,
            options={"require": ["exp", "iss", "aud", "tid", "oid", "roles"]},
        )
        self._validate_claims(claims)
        return claims

    def _validate_claims(self, claims: dict[str, Any]) -> None:
        tenant_id = self.config.tenant_id
        caller_object_id = self.config.caller_object_id
        if not isinstance(claims.get("tid"), str) or claims["tid"] != tenant_id:
            raise InvalidTokenError("Unexpected tenant")
        if not isinstance(claims.get("oid"), str) or claims["oid"] != caller_object_id:
            raise InvalidTokenError("Unexpected caller")
        if not isinstance(claims.get("iss"), str) or claims["iss"] not in self._allowed_issuers():
            raise InvalidTokenError("Unexpected issuer")
        roles = claims.get("roles")
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise InvalidTokenError("Invalid roles")
        if self.config.required_role not in roles:
            raise InvalidTokenError("Missing required application role")

    def _allowed_issuers(self) -> set[str]:
        tenant_id = self.config.tenant_id
        assert tenant_id is not None
        return {
            f"https://login.microsoftonline.com/{tenant_id}",
            f"https://login.microsoftonline.com/{tenant_id}/",
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://login.microsoftonline.com/{tenant_id}/v2.0/",
            f"https://sts.windows.net/{tenant_id}/",
        }


class WorkloadAuthenticator:
    """FastAPI-facing workload authentication with uniform token rejections."""

    def __init__(self, config: WorkloadAuthConfig, verifier: TokenVerifier | None = None):
        self.config = config
        self._verifier = verifier or (EntraTokenVerifier(config) if config.is_entra else None)

    @classmethod
    def from_env(cls) -> "WorkloadAuthenticator":
        return cls(WorkloadAuthConfig.from_env())

    async def authenticate(self, request: Request) -> JSONResponse | None:
        if request.url.path == "/health" or not self.config.is_entra:
            return None

        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return self._unauthorized()
        assert self._verifier is not None
        try:
            claims = await self._verifier.verify(token.strip())
        except InvalidTokenError as exc:
            logger.info("Runtime workload token rejected: %s", exc)
            return self._unauthorized()
        except Exception:
            logger.exception("Runtime workload token verification unavailable")
            return JSONResponse(status_code=503, content={"detail": "Authentication service unavailable."})

        request.state.workload_authenticated = True
        request.state.workload_claims = claims
        return None

    @staticmethod
    def _unauthorized() -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
