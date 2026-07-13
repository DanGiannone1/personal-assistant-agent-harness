"""Auth behavior probe (R1/R2): demo flag gating + Entra principal mapping.

Runs against the real FastAPI app with the Cosmos emulator (in-process TestClient —
real routes, real middleware, real appdb writes). The Entra path is exercised at the
validated-claims seam (`request.state.auth_claims`), NOT by forging JWTs: api_auth's
signature/audience/tenant checks are its own concern and are proven on the deployed
app. Usage:  set -a && source .env && set +a && uv run python scripts/auth_probe.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "session-container"))

FAKE_OID = "00000000-0000-4000-8000-00000000e2e1"
FAKE_UID = f"u-{FAKE_OID}"

failures = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global failures
    print(f"{'PASS' if cond else 'FAIL'}  {name}{f' — {extra}' if extra else ''}")
    if not cond:
        failures += 1


def make_request(headers: dict[str, str] | None = None, claims: dict | None = None):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/probe",
        "query_string": b"",
        "state": {},
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    request = Request(scope)
    if claims is not None:
        request.state.auth_claims = claims
    return request


def cleanup(appdb) -> None:
    """Remove the probe's provisioned Entra user + its docs so reruns start clean."""
    container = appdb._container()
    try:
        appdb._update_raw(
            appdb._USERS_DOC_ID,
            lambda doc: doc["users"].__delitem__(
                next(i for i, u in enumerate(doc["users"]) if u["id"] == FAKE_UID)
            ),
        )
    except Exception:
        pass
    for doc_id in (f"space-{FAKE_UID}", f"ctx-{FAKE_UID}"):
        try:
            container.delete_item(item=doc_id, partition_key=doc_id)
        except Exception:
            pass


def main() -> int:
    os.environ.pop("DEMO_LOGIN_ENABLED", None)

    from fastapi.testclient import TestClient
    from fastapi import HTTPException

    import app as app_module
    import appdb
    import auth_users

    with TestClient(app_module.app) as client:
        # ── Demo path, flag on (default) ────────────────────────────────────
        res = client.post("/auth/login", json={"username": "dan", "password": "demo1234"})
        ok("demo login succeeds with flag unset", res.status_code == 200)
        token = res.json()["token"]
        res = client.get("/auth/me", headers={"X-Auth-Token": token})
        ok("demo token resolves via /auth/me", res.status_code == 200 and res.json()["id"] == "dan")
        ok("demo identity kind reported", res.json().get("identity") == "demo")

        # ── Flag off: login blocked AND existing tokens stop resolving ──────
        os.environ["DEMO_LOGIN_ENABLED"] = "false"
        res = client.post("/auth/login", json={"username": "dan", "password": "demo1234"})
        ok("login returns 403 when demo disabled", res.status_code == 403, str(res.status_code))
        res = client.get("/auth/me", headers={"X-Auth-Token": token})
        ok("previously issued demo token stops resolving", res.status_code == 401, str(res.status_code))
        os.environ["DEMO_LOGIN_ENABLED"] = "true"
        res = client.get("/auth/me", headers={"X-Auth-Token": token})
        ok("token resolves again once re-enabled", res.status_code == 200)

        # ── Entra path: provisioning at the validated-claims seam ────────────
        claims = {
            "oid": FAKE_OID,
            "preferred_username": "Probe.User@example.test",
            "name": "Probe User",
        }
        uid = auth_users.current_user(make_request(claims=claims))
        ok("entra claims resolve to u-<oid>", uid == FAKE_UID, uid)
        record = appdb.get_user(FAKE_UID)
        ok("first sight auto-provisions the app user", record is not None)
        ok("displayName from name claim", (record or {}).get("displayName") == "Probe User")
        ok("identity marked entra", (record or {}).get("identity") == "entra")
        ok("no password hash on entra users", "passwordHash" not in (record or {"passwordHash": 1}))

        uid2 = auth_users.current_user(make_request(claims=claims))
        all_matching = [u for u in appdb.list_users() if u["id"] == FAKE_UID]
        ok("second call reuses the record (no duplicate)", uid2 == FAKE_UID and len(all_matching) == 1)

        # ── Precedence: demo token wins only while demo login is enabled ─────
        both = make_request(headers={"X-Auth-Token": token}, claims=claims)
        ok("demo token wins when both identities present", auth_users.current_user(both) == "dan")
        os.environ["DEMO_LOGIN_ENABLED"] = "false"
        both = make_request(headers={"X-Auth-Token": token}, claims=claims)
        ok("entra wins once demo is disabled", auth_users.current_user(both) == FAKE_UID)
        os.environ["DEMO_LOGIN_ENABLED"] = "true"

        # ── No credentials → 401 ─────────────────────────────────────────────
        try:
            auth_users.current_user(make_request())
            ok("anonymous request rejected", False)
        except HTTPException as exc:
            ok("anonymous request rejected", exc.status_code == 401)

        cleanup(appdb)

    print()
    if failures:
        print(f"AUTH PROBE: {failures} FAILURE(S)")
        return 1
    print("AUTH PROBE: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
