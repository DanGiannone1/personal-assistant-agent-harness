# Data-layer smoke for the engagement delivery record (stage/health/milestones/risks/
# actions) on the multi-user appdb. Runs against live Cosmos (emulator or real):
#   COSMOS_ENDPOINT=http://localhost:8081 COSMOS_KEY=... python3 scripts/engagement_domain_smoke.py
# Self-contained: creates a throwaway engagement, exercises it, then archives nothing —
# the doc is removed at the end via the raw container (no delete API exists by design).
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "session-container"))

import appdb  # noqa: E402

FAILURES = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global FAILURES
    print(f"{'PASS' if cond else 'FAIL'}  {name}{f' — {extra}' if extra else ''}")
    if not cond:
        FAILURES += 1


def main() -> None:
    appdb.ensure_seeded()

    # 1. Creation carries the domain layer; stage/health validate loud.
    eng = appdb.new_engagement("dan", "Domain Smoke", "throwaway",
                               customer="Smoke Co", stage="Build",
                               target_date="2026-09-01")
    eid = eng["id"]
    check("create carries domain fields",
          eng["customer"] == "Smoke Co" and eng["stage"] == "Build"
          and eng["health"] == "green" and eng["milestones"] == [])
    try:
        appdb.new_engagement("dan", "Bad Stage", stage="Sideways")
        check("invalid stage raises", False)
    except ValueError:
        check("invalid stage raises", True)

    # 2. Seeded fixtures got the domain layer (idempotent seed keeps ids).
    engs = {e["id"]: e for e in appdb.list_engagements_for("dan")}
    wl = engs.get("eng-website-launch")
    check("seeded Website Launch is amber with a why",
          wl is not None and wl["health"] == "amber" and bool(wl["healthNote"].strip()))
    check("seeded milestones/risks/actions present",
          wl is not None and len(wl["milestones"]) == 2 and len(wl["risks"]) == 1
          and len(wl["actions"]) == 1)

    # 3. Items via update_engagement + find_engagement_item.
    def _add_risk(doc):
        items = doc["risks"]
        items.append({"id": appdb.new_id("r", items), "title": "Vendor slippage",
                      "severity": "High", "status": "Open", "mitigation": "", "owner": "dan"})
        appdb.log_activity(doc, "dan", "risk.added", "Vendor slippage")
    appdb.update_engagement(eid, _add_risk)
    fresh = appdb.load_engagement(eid)
    item = appdb.find_engagement_item(fresh, "risk", "vendor")
    check("find_engagement_item resolves by substring",
          item is not None and item["severity"] == "High")
    check("activity logged inside the mutation",
          any(a["action"] == "risk.added" for a in fresh["activity"]))

    # 4. Six concurrent writers all land (ETag retry — no lost updates).
    def _writer(n: int):
        def _mut(doc):
            doc["actions"].append({"id": f"a-c{n}", "title": f"concurrent {n}",
                                   "owner": "", "dueDate": "", "status": "Open", "notes": ""})
        appdb.update_engagement(eid, _mut)
    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fresh = appdb.load_engagement(eid)
    check("6 concurrent writers, 0 lost updates", len(fresh["actions"]) == 6,
          f"got {len(fresh['actions'])}")

    # 5. Health + why commit atomically (one doc, one write).
    def _amber(doc):
        doc["health"] = "amber"
        doc["healthNote"] = "smoke: dependency slipped"
    appdb.update_engagement(eid, _amber)
    fresh = appdb.load_engagement(eid)
    check("health and why land together",
          fresh["health"] == "amber" and fresh["healthNote"] == "smoke: dependency slipped")

    # 6. AbortWrite returns without writing.
    def _abort(doc):
        doc["health"] = "red"  # would be a lie
        raise appdb.AbortWrite("aborted")
    out = appdb.update_engagement(eid, _abort)
    check("AbortWrite skips the write",
          out == "aborted" and appdb.load_engagement(eid)["health"] == "amber")

    # 7. Membership: sam (not a member) can't see the throwaway engagement.
    check("non-member doesn't list it",
          all(e["id"] != eid for e in appdb.list_engagements_for("sam")))
    check("role helpers gate writes",
          appdb.role_at_least(fresh, "dan", "editor")
          and not appdb.role_at_least(fresh, "sam", "viewer"))

    # Cleanup: raw container delete (there is deliberately no delete API).
    appdb._container().delete_item(item=eid, partition_key=eid)
    check("cleanup removed the throwaway doc", appdb.load_engagement(eid) is None)

    print()
    if FAILURES:
        print(f"ENGAGEMENT DOMAIN SMOKE: {FAILURES} FAILURE(S)")
        sys.exit(1)
    print("ENGAGEMENT DOMAIN SMOKE: ALL PASS")


if __name__ == "__main__":
    main()
