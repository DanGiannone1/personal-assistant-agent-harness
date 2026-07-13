"""Data-layer smoke test for the engagement shared scope (appdb).

Exercises the engagement doc lifecycle against the configured Cosmos account —
create/list/resolve/update/items, ETag-retry convergence under concurrent
writers, navigation resolution, and delete. Run from the repo root:

    set -a; source .env; set +a
    uv run --project session-container python scripts/engagements_db_smoke.py

Uses COSMOS_DATABASE from the environment — point it at a dev database, never
at shared data.
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "session-container"))
import appdb  # noqa: E402


def main() -> None:
    # 1. Seeding includes the /engagements route (fresh docs AND migrated old docs).
    state = appdb.ensure_seeded()
    assert any(r["path"] == "/engagements" for r in state["routes"]), "/engagements route missing"
    print("1. seeded routes include /engagements")

    # 2. Create.
    eng = appdb.create_engagement(
        "Smoke Test Engagement", customer="Contoso", stage="Build",
        target_date="2026-12-01", notes="created by engagements_db_smoke",
    )
    eid = eng["id"]
    assert eng["health"] == "green" and eng["stage"] == "Build"
    print(f"2. created {eid}")

    try:
        # 3. List + resolve by substring.
        assert any(g["id"] == eid for g in appdb.list_engagements())
        resolved = appdb.resolve_engagement("smoke test")
        assert resolved and resolved["id"] == eid
        print("3. list + resolve ok")

        # 4. Items via update_engagement.
        def _add_items(g):
            g["milestones"].append({
                "id": appdb.new_id("m", g["milestones"]), "title": "Design sign-off",
                "dueDate": "2026-08-01", "status": "Planned", "notes": "",
            })
            g["risks"].append({
                "id": appdb.new_id("r", g["risks"]), "title": "Security review slip",
                "severity": "High", "status": "Open", "mitigation": "escalate", "owner": "Dan",
            })
        appdb.update_engagement(eid, _add_items)
        g = appdb.load_engagement(eid)
        assert len(g["milestones"]) == 1 and len(g["risks"]) == 1
        assert appdb.find_engagement_item(g, "risk", "security")["severity"] == "High"
        print("4. items ok")

        # 5. Six concurrent writers must all land (ETag retry — no lost updates).
        def _bump():
            def _mut(gg):
                gg["actions"].append({
                    "id": appdb.new_id("a", gg["actions"]),
                    "title": f"action-{len(gg['actions']) + 1}",
                    "owner": "", "dueDate": "", "status": "Open", "notes": "",
                })
            appdb.update_engagement(eid, _mut)
        threads = [threading.Thread(target=_bump) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        g = appdb.load_engagement(eid)
        assert len(g["actions"]) == 6, f"lost writes: {len(g['actions'])}/6 actions survived"
        print("5. 6/6 concurrent writers converged (no lost updates)")

        # 6. Health + why commit atomically.
        def _red(gg):
            gg["health"] = "red"
            gg["healthNote"] = "smoke reason"
        appdb.update_engagement(eid, _red)
        g = appdb.load_engagement(eid)
        assert g["health"] == "red" and g["healthNote"] == "smoke reason"
        print("6. health+note atomic ok")

        # 7. Navigation resolves the page and the engagement by title.
        engs = appdb.list_engagements()
        res = appdb.resolve_destination(appdb.load(), "Smoke Test Engagement", engs)
        assert res["status"] == "resolved" and res["path"] == appdb.engagement_route(eid), res
        res2 = appdb.resolve_destination(appdb.load(), "engagements", engs)
        assert res2["status"] == "resolved" and res2["path"] == "/engagements", res2
        print("7. navigation ok")

        # 8. AbortWrite returns without writing.
        marker = appdb.update_engagement(eid, lambda gg: (_ for _ in ()).throw(appdb.AbortWrite("NOOP")))
        assert marker == "NOOP"
        print("8. AbortWrite ok")
    finally:
        # 9. Delete (idempotent).
        assert appdb.delete_engagement(eid) is True
        assert appdb.load_engagement(eid) is None
        assert appdb.delete_engagement(eid) is False
        print(f"9. deleted {eid}")

    print("ENGAGEMENT DB SMOKE: ALL PASS")


if __name__ == "__main__":
    main()
