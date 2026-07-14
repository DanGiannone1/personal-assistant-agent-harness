"""API-shape probe: error contracts the e2e doesn't exercise (review gap list).

Covers: artifact upload 413/422 without unbounded buffering, canonical-id
artifact keying (eng- prefix optional in the URL), member-removal error shapes
(404 non-member / 403 non-owner / 422 last-owner), the /users directory, and
username-based member adds. Real routes + middleware via in-process TestClient
against the Cosmos emulator. Usage:
    set -a && source .env && set +a && uv run python scripts/api_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "session-container"))

WL = "eng-website-launch"
failures = 0


def ok(name: str, cond: bool, extra: str = "") -> None:
    global failures
    print(f"{'PASS' if cond else 'FAIL'}  {name}{f' — {extra}' if extra else ''}")
    if not cond:
        failures += 1


def main() -> int:
    from fastapi.testclient import TestClient

    import app as app_module

    with TestClient(app_module.app) as client:
        def login(user: str) -> dict:
            res = client.post("/auth/login", json={"username": user, "password": "demo1234"})
            assert res.status_code == 200, f"login {user} failed: {res.status_code}"
            return {"X-Auth-Token": res.json()["token"]}

        dan, ava, sam = login("dan"), login("ava"), login("sam")

        # ── Artifact upload caps (member may add; body must not buffer unbounded) ──
        big = b"x" * (20 * 1024 * 1024 + 1)
        res = client.post(f"/engagements/{WL}/artifacts", headers=dan,
                          files={"file": ("big.bin", big, "application/octet-stream")})
        ok("oversized upload → 413", res.status_code == 413, str(res.status_code))
        res = client.post(f"/engagements/{WL}/artifacts", headers=dan,
                          files={"file": ("empty.bin", b"", "application/octet-stream")})
        ok("empty upload → 422", res.status_code == 422, str(res.status_code))

        # ── Canonical-id keying: upload via the UNPREFIXED id, read via canonical ──
        res = client.post("/engagements/website-launch/artifacts", headers=dan,
                          files={"file": ("probe.txt", b"canonical-key-check", "text/plain")})
        ok("upload via unprefixed engagement id → 201", res.status_code == 201, str(res.status_code))
        art_id = res.json().get("id", "")
        res = client.get(f"/engagements/{WL}/artifacts/{art_id}", headers=dan)
        ok("download via canonical id returns the bytes",
           res.status_code == 200 and res.content == b"canonical-key-check")
        res = client.delete(f"/engagements/website-launch/artifacts/{art_id}", headers=dan)
        ok("delete via unprefixed id → 204", res.status_code == 204, str(res.status_code))
        res = client.get(f"/engagements/{WL}/artifacts/{art_id}", headers=dan)
        ok("deleted artifact gone from both paths", res.status_code == 404, str(res.status_code))

        # ── Member-removal error shapes ─────────────────────────────────────────
        res = client.delete(f"/engagements/{WL}/members/sam", headers=ava)  # ava: non-member
        ok("non-member remove_member → 404 (no membership leak)", res.status_code == 404, str(res.status_code))
        res = client.delete(f"/engagements/{WL}/members/dan", headers=sam)  # sam: viewer
        ok("non-owner member remove_member → 403", res.status_code == 403, str(res.status_code))
        res = client.delete(f"/engagements/{WL}/members/dan", headers=dan)  # dan: only owner
        ok("removing the last owner → 422", res.status_code == 422, str(res.status_code))
        res = client.delete("/engagements/eng-nope/members/dan", headers=dan)
        ok("unknown engagement remove_member → 404", res.status_code == 404, str(res.status_code))

        # ── /users directory ────────────────────────────────────────────────────
        res = client.get("/users", headers=sam)
        body = res.json() if res.status_code == 200 else []
        ok("/users lists the seeded accounts", res.status_code == 200
           and {"dan", "ava", "sam"} <= {u["id"] for u in body})
        ok("/users never exposes password hashes or persona",
           all(set(u) <= {"id", "username", "displayName"} for u in body))
        res = client.get("/users")
        ok("/users requires auth", res.status_code == 401, str(res.status_code))

        # ── Member add resolves username (case-insensitive), rejects unknown ────
        res = client.post(f"/engagements/{WL}/members", headers=dan,
                          json={"userId": "AVA", "role": "viewer"})
        ok("member add by username resolves case-insensitively",
           res.status_code == 201 and res.json().get("userId") == "ava", str(res.status_code))
        res = client.delete(f"/engagements/{WL}/members/ava", headers=dan)
        ok("cleanup: probe member removed", res.status_code == 204, str(res.status_code))
        res = client.post(f"/engagements/{WL}/members", headers=dan,
                          json={"userId": "nobody-here", "role": "viewer"})
        ok("unknown user member add → 422 (never a silent add)", res.status_code == 422, str(res.status_code))

    print()
    if failures:
        print(f"API PROBE: {failures} FAILURE(S)")
        return 1
    print("API PROBE: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
