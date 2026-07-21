"""Application-level credential validation for the selected identity mode."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import InvalidTokenError, PyJWKClient

from identity_config import IdentityConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthConfig:
    identity: IdentityConfig
    tenant_id: str | None
    api_client_id: str | None
    allowed_audiences: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "AuthConfig":
        identity = IdentityConfig.from_env()
        return cls(identity=identity, tenant_id=identity.tenant_id,
                   api_client_id=identity.api_client_id, allowed_audiences=identity.allowed_audiences)

    @property
    def bearer_enabled(self) -> bool:
        return bool(self.tenant_id and self.allowed_audiences)

    @property
    def enabled(self) -> bool:
        return True


class APIAuthenticator:
    def __init__(self, config: AuthConfig):
        self.config = config
        self._jwks_client = (
            PyJWKClient(f"https://login.microsoftonline.com/{config.tenant_id}/discovery/v2.0/keys")
            if config.bearer_enabled
            else None
        )

    async def authenticate(self, request: Request) -> JSONResponse | None:
        if request.method == "OPTIONS" or request.url.path == "/health":
            return None

        auth_header = request.headers.get("authorization", "")
        demo_token = request.headers.get("x-auth-token")
        if self.config.identity.is_demo:
            if auth_header or request.headers.get("x-api-key"):
                return self._unauthorized()
            return None

        if demo_token or request.headers.get("x-api-key"):
            return self._unauthorized()
        if auth_header.lower().startswith("bearer "):
            if not self._jwks_client:
                return self._unauthorized()
            token = auth_header.split(" ", 1)[1].strip()
            if not token:
                return self._unauthorized()
            try:
                claims = await self._validate_token(token)
            except InvalidTokenError as exc:
                logger.info("Bearer token rejected: %s", exc)
                return self._unauthorized()
            except Exception:
                logger.exception("Bearer token validation failed unexpectedly")
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Authentication service unavailable."},
                )
            request.state.auth_method = "bearer"
            request.state.auth_claims = claims
            return None

        return self._unauthorized()

    async def _validate_token(self, token: str) -> dict[str, Any]:
        assert self._jwks_client is not None
        signing_key = await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.config.allowed_audiences,
            options={"require": ["exp", "iss", "aud"]},
        )

        tenant_id = self.config.tenant_id
        if tenant_id and claims.get("tid") != tenant_id:
            raise InvalidTokenError("Unexpected tenant")

        issuer = claims.get("iss")
        if issuer not in self._allowed_issuers():
            raise InvalidTokenError("Unexpected issuer")

        # This public API accepts only delegated user access.  Application tokens
        # carry roles rather than the delegated `scp` claim and must not be usable
        # as a browser credential.
        scopes = claims.get("scp")
        if not isinstance(scopes, str) or "access_as_user" not in scopes.split():
            raise InvalidTokenError("Missing delegated scope")

        return claims

    def _allowed_issuers(self) -> set[str]:
        tenant_id = self.config.tenant_id
        if not tenant_id:
            return set()
        return {
            f"https://login.microsoftonline.com/{tenant_id}",
            f"https://login.microsoftonline.com/{tenant_id}/",
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://login.microsoftonline.com/{tenant_id}/v2.0/",
            f"https://sts.windows.net/{tenant_id}/",
        }

    @staticmethod
    def _unauthorized() -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
