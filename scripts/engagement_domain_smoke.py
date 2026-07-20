# Data-layer smoke for the v1 engagement delivery record (G/Y/R status-with-a-why +
# engagement tasks) on the multi-user appdb. Runs against live Cosmos (emulator or real):
#   COSMOS_ENDPOINT=http://localhost:8081 COSMOS_KEY=... python3 scripts/engagement_domain_smoke.py
# Self-contained: creates a throwaway engagement, exercises it, then removes it at the
# end via the raw container (no delete API exists by design).
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "session-container"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import appdb  # noqa: E402
import artifact_store  # noqa: E402

FAILURES = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global FAILURES
    print(f"{'PASS' if cond else 'FAIL'}  {name}{f' — {extra}' if extra else ''}")
    if not cond:
        FAILURES += 1


def main() -> None:
    password = os.environ.get("DEMO_PASSWORD", "")
    if not password:
        raise RuntimeError("DEMO_PASSWORD is required for the demo smoke")
    appdb.ensure_seeded(password)

    # 1. Creation carries the domain layer; status validates loud.
    eng = appdb.new_engagement("dan", "Domain Smoke", "throwaway",
                               customer="Smoke Co", target_date="2026-09-01")
    eid = eng["id"]
    check("create carries domain fields",
          eng["customer"] == "Smoke Co" and eng["status"] == "green"
          and eng["statusNote"] == "" and eng["tasks"] == [])
    try:
        appdb.new_engagement("dan", "Bad Status", status="chartreuse")
        check("invalid status raises", False)
    except ValueError:
        check("invalid status raises", True)

    # 2. Seeded fixtures got the domain layer (idempotent seed keeps ids).
    engs = {e["id"]: e for e in appdb.list_engagements_for("dan")}
    wl = engs.get("eng-website-launch")
    check("seeded Website Launch is yellow with a why",
          wl is not None and wl["status"] == "yellow" and bool(wl["statusNote"].strip()))
    check("seeded engagement tasks present",
          wl is not None and len(wl["tasks"]) == 2)

    # 2b. Legacy mapping: a pre-rename doc (health/amber) reads as status/yellow.
    legacy = {"id": "eng-legacy-probe", "name": "Legacy", "members": [],
              "health": "amber", "healthNote": "old why"}
    mapped = appdb._with_domain_defaults(dict(legacy))
    check("legacy health/amber maps to status/yellow on read",
          mapped["status"] == "yellow" and mapped["statusNote"] == "old why")

    # 3. Engagement tasks via update_engagement (the v1 record type inside the doc).
    def _add_task(doc):
        items = doc["tasks"]
        items.append({"id": appdb.new_id("t", items), "title": "Smoke probe task",
                      "status": "To do", "priority": "Medium", "group": "General",
                      "dueDate": "", "subtasks": [], "notes": ""})
        appdb.log_activity(doc, "dan", "task.created", "Smoke probe task")
    appdb.update_engagement(eid, _add_task)
    fresh = appdb.load_engagement(eid)
    check("engagement task lands in the doc",
          any(t["title"] == "Smoke probe task" for t in fresh["tasks"]))
    check("activity logged inside the mutation",
          any(a["action"] == "task.created" for a in fresh["activity"]))

    # 4. Six concurrent writers all land (ETag retry — no lost updates).
    def _writer(n: int):
        def _mut(doc):
            doc["tasks"].append({"id": f"t-c{n}", "title": f"concurrent {n}",
                                 "status": "To do", "priority": "Low", "group": "General",
                                 "dueDate": "", "subtasks": [], "notes": ""})
        appdb.update_engagement(eid, _mut)
    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fresh = appdb.load_engagement(eid)
    concurrent = [t for t in fresh["tasks"] if t["title"].startswith("concurrent")]
    check("6 concurrent writers, 0 lost updates", len(concurrent) == 6,
          f"got {len(concurrent)}")

    # 5. Status + why commit atomically (one doc, one write).
    def _yellow(doc):
        doc["status"] = "yellow"
        doc["statusNote"] = "smoke: dependency slipped"
    appdb.update_engagement(eid, _yellow)
    fresh = appdb.load_engagement(eid)
    check("status and why land together",
          fresh["status"] == "yellow" and fresh["statusNote"] == "smoke: dependency slipped")

    # 6. AbortWrite returns without writing.
    def _abort(doc):
        doc["status"] = "red"  # would be a lie
        raise appdb.AbortWrite("aborted")
    out = appdb.update_engagement(eid, _abort)
    check("AbortWrite skips the write",
          out == "aborted" and appdb.load_engagement(eid)["status"] == "yellow")

    # 7. Membership: sam (not a member) can't see the throwaway engagement.
    check("non-member doesn't list it",
          all(e["id"] != eid for e in appdb.list_engagements_for("sam")))
    check("role helpers gate writes",
          appdb.role_at_least(fresh, "dan", "editor")
          and not appdb.role_at_least(fresh, "sam", "viewer"))

    # 8. Artifacts: bytes roundtrip through the adapter, metadata via the ETag mutator.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["ARTIFACTS_DIR"] = tmp
        payload = b"# smoke artifact\n" * 100
        artifact_store.put(eid, "art-smoke01", payload, "text/markdown")
        check("artifact bytes roundtrip", artifact_store.get(eid, "art-smoke01") == payload)

        def _add_meta(doc):
            doc.setdefault("library", []).insert(0, {
                "id": "art-smoke01", "name": "smoke.md", "size": len(payload),
                "contentType": "text/markdown", "uploadedBy": "dan",
                "uploadedAt": appdb._now_iso()})
            appdb.log_activity(doc, "dan", "artifact.added", "smoke.md")
        appdb.update_engagement(eid, _add_meta)
        after = appdb.load_engagement(eid)
        check("artifact metadata lands with activity",
              any(a["id"] == "art-smoke01" for a in after["library"])
              and after["activity"][0]["action"] == "artifact.added")
        try:
            artifact_store.put("../evil", "art-x", b"x", "text/plain")
            check("path-shaped ids are refused", False)
        except ValueError:
            check("path-shaped ids are refused", True)
        check("artifact delete removes bytes",
              artifact_store.delete(eid, "art-smoke01")
              and artifact_store.get(eid, "art-smoke01") is None)
        os.environ.pop("ARTIFACTS_DIR", None)

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
