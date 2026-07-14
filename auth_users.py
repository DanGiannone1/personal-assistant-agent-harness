"""App-level user authentication for the orchestrator (demo-grade by design).

Seeded username/password accounts live in Cosmos (see appdb users doc). This module
issues opaque bearer tokens held in memory: an orchestrator restart signs everyone out
(mirroring the existing in-memory session set — the frontend already recovers by
re-creating). No refresh, lockout, or MFA; the seam to a real identity provider is
exactly this module.

Distinct from `api_auth.py` (deploy-time caller gate: IP allow-list / Entra). That
answers "may this caller reach the API at all"; this answers "which app user is it".
Header: X-Auth-Token (Authorization stays reserved for the deploy-time Entra flow).
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request

_SC = Path(__file__).resolve().parent / "session-container"
if str(_SC) not in sys.path:
    sys.path.insert(0, str(_SC))
import appdb  # noqa: E402

_LOCK = threading.Lock()
_TOKENS: dict[str, dict] = {}  # token -> {"userId": str, "issuedAt": float}
_ENTRA_SEEN: set[str] = set()  # uids provisioned this process — skips a Cosmos read per request

AUTH_HEADER = "X-Auth-Token"
# Idle demo sessions die after 12h — long enough for any demo, short enough to not
# accumulate forever in memory.
_TOKEN_TTL_SECONDS = 12 * 3600


def demo_login_enabled() -> bool:
    """Seeded demo accounts (R2): on by default so local stacks and the deployed
    Playwright path work; flip DEMO_LOGIN_ENABLED=false to turn the path off
    without a code change. Read per-call so probes and env updates take effect
    immediately."""
    return (os.getenv("DEMO_LOGIN_ENABLED") or "true").strip().lower() not in {"0", "false", "no", "off"}


def login(username: str, password: str) -> dict:
    """Verify credentials → {token, user}. Raises 401 on failure (no reason leakage)."""
    if not demo_login_enabled():
        raise HTTPException(status_code=403, detail="Demo sign-in is disabled on this deployment")
    user = appdb.verify_login(username, password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = secrets.token_urlsafe(32)
    with _LOCK:
        _TOKENS[token] = {"userId": user["id"], "issuedAt": time.time()}
    return {"token": token, "user": user}


def logout(token: str | None) -> None:
    if not token:
        return
    with _LOCK:
        _TOKENS.pop(token, None)


def _resolve(token: str | None) -> str | None:
    if not token:
        return None
    with _LOCK:
        entry = _TOKENS.get(token)
        if entry is None:
            return None
        if time.time() - entry["issuedAt"] > _TOKEN_TTL_SECONDS:
            _TOKENS.pop(token, None)
            return None
        return entry["userId"]


def _entra_user(claims: dict) -> str:
    """Map a VALIDATED Entra token (api_auth already checked signature, audience,
    tenant, issuer) to an app user, provisioning it on first sight."""
    oid = (claims.get("oid") or "").strip().lower()
    if not oid:
        raise HTTPException(status_code=401, detail="Token carries no object id")
    uid = f"u-{oid}"
    if uid not in _ENTRA_SEEN:
        username = claims.get("preferred_username") or claims.get("upn") or claims.get("email") or uid
        display = claims.get("name") or username
        appdb.ensure_entra_user(oid, username, display)
        with _LOCK:
            _ENTRA_SEEN.add(uid)
    return uid


def current_user(request: Request) -> str:
    """FastAPI dependency: the signed-in user id, or 401. Every /sessions* route uses it.

    Two identities can arrive on one request (Entra bearer + demo X-Auth-Token,
    because the frontend always merges both headers). The demo token wins while
    demo login is enabled — that keeps Playwright runs deterministic on deployments
    where Easy Auth or MSAL also injects a bearer. With demo login disabled, demo
    tokens stop resolving entirely and only the Entra path remains.
    """
    if demo_login_enabled():
        uid = _resolve(request.headers.get(AUTH_HEADER))
        if uid is not None:
            return uid
    claims = getattr(request.state, "auth_claims", None)
    if isinstance(claims, dict):
        return _entra_user(claims)
    raise HTTPException(status_code=401, detail="Sign in required")
