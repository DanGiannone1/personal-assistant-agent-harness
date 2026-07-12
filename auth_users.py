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

AUTH_HEADER = "X-Auth-Token"
# Idle demo sessions die after 12h — long enough for any demo, short enough to not
# accumulate forever in memory.
_TOKEN_TTL_SECONDS = 12 * 3600


def login(username: str, password: str) -> dict:
    """Verify credentials → {token, user}. Raises 401 on failure (no reason leakage)."""
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


def current_user(request: Request) -> str:
    """FastAPI dependency: the signed-in user id, or 401. Every /sessions* route uses it."""
    uid = _resolve(request.headers.get(AUTH_HEADER))
    if uid is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return uid
