"""Pure-logic checks for navsvc resolution + ranking — no Cosmos, no stack.

Run from session-container/:  uv run python ../scripts/navsvc_checks.py
Guards the flagship behaviors: recency breaks the two-Launch tie per user (decide,
don't interrogate), honest ambiguity on cold start, the fail-loud stopword rule,
and quick-links ranking (recency first, Home excluded, overdue boosted).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "session-container"))
import navsvc  # noqa: E402

web = {"id": "eng-website-launch", "name": "Website Launch",
       "tasks": [{"id": "t-1", "title": "Draft launch checklist", "status": "In progress",
                  "priority": "High", "dueDate": "2026-07-16"}],
       "events": []}
prod = {"id": "eng-product-launch", "name": "Product Launch",
        "tasks": [{"id": "t-1", "title": "Finalize pricing tiers", "status": "To do",
                   "priority": "High", "dueDate": "2026-07-15"}],
        "events": []}
personal = {"tasks": [], "events": [], "routes": [
    {"path": "/home", "title": "Home", "keywords": ["home", "dashboard"]},
    {"path": "/todo", "title": "Tasks", "keywords": ["tasks", "todo"]},
    {"path": "/calendar", "title": "Calendar", "keywords": ["calendar", "events"]},
]}

fails = 0
def check(name, cond, extra=""):
    global fails
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails += 1

dan_visits = [{"path": "/engagements/eng-website-launch/tasks", "title": "Website Launch · Tasks", "ts": "t"}]
ava_visits = [{"path": "/engagements/eng-product-launch/tasks", "title": "Product Launch · Tasks", "ts": "t"}]

r_dan = navsvc.resolve(personal, [web, prod], dan_visits, "take me to the launch tasks")
r_ava = navsvc.resolve(personal, [web, prod], ava_visits, "take me to the launch tasks")
check("dan → Website Launch tasks", r_dan["status"] == "resolved" and "website" in r_dan.get("path", ""), str(r_dan)[:90])
check("ava → Product Launch tasks", r_ava["status"] == "resolved" and "product" in r_ava.get("path", ""), str(r_ava)[:90])

# A context-decided (stage-2) resolve carries the beaten rival as an escape-hatch
# alternate — the "Did you mean" chips. Fully bound: every alternate has a path.
check("context tie-break carries alternates",
      any("product" in a["path"] for a in r_dan.get("alternates", []))
      and all(a.get("path", "").startswith("/") for a in r_dan.get("alternates", [])),
      str(r_dan.get("alternates"))[:90])

r_cold = navsvc.resolve(personal, [web, prod], [], "take me to the launch tasks")
check("cold start → honest ambiguity", r_cold["status"] == "ambiguous" and len(r_cold["candidates"]) >= 2)

r_crypto = navsvc.resolve(personal, [web, prod], [], "crypto mining dashboard")
check("'crypto mining dashboard' fails loud", r_crypto["status"] == "not_found", r_crypto["status"])

r_cal = navsvc.resolve(personal, [web, prod], [], "calendar")
check("'calendar' resolves instantly", r_cal["status"] == "resolved" and r_cal["path"] == "/calendar")

r_pricing = navsvc.resolve(personal, [web, prod], [], "finalize pricing tiers")
check("unique engagement task title resolves", r_pricing["status"] == "resolved" and "product-launch" in r_pricing["path"])

# Relevance must still beat familiarity: dan visits Website Launch constantly, but an
# exact ask for the OTHER engagement's page goes there, not to the familiar one.
r_exact = navsvc.resolve(personal, [web, prod], dan_visits, "product launch settings")
check("exact wording beats recency", r_exact["status"] == "resolved" and "product-launch/settings" in r_exact["path"], str(r_exact)[:90])
# ... and a clear lexical win needs no escape hatch: the user's own words picked it.
check("clear lexical win carries no alternates", not r_exact.get("alternates"), str(r_exact.get("alternates"))[:60])

today = "2026-07-20"
ql = navsvc.rank_destinations(personal, [web, prod], dan_visits, None, today, 5)
check("quick links exclude Home", all(d["path"] != "/home" for d in ql))
check("quick links lead with the visited page", "website" in ql[0]["path"], ql[0]["path"])
check("overdue records boosted into quick links", any(d.get("record") for d in ql))

# Mixed-recency regression (the E2E contamination case): user worked in Product a few
# clicks ago but is IN Website now — most recent must still win decisively.
mixed_visits = [
    {"path": "/engagements/eng-website-launch/tasks", "title": "", "ts": "t"},
    {"path": "/engagements/eng-website-launch", "title": "", "ts": "t"},
    {"path": "/engagements", "title": "", "ts": "t"},
    {"path": "/home", "title": "", "ts": "t"},
    {"path": "/todo", "title": "", "ts": "t"},
    {"path": "/engagements/eng-product-launch/tasks", "title": "", "ts": "t"},
]
r_mixedrec = navsvc.resolve(personal, [web, prod], mixed_visits, "take me to the launch tasks")
check("mixed recency: most recent engagement wins", r_mixedrec["status"] == "resolved" and "website" in r_mixedrec["path"], str(r_mixedrec)[:90])

personal2 = dict(personal, tasks=[{"id": "t-9", "title": "Launch day prep", "status": "To do", "dueDate": ""}])
r_mixed = navsvc.resolve(personal2, [web, prod], [], "launch")
check("three-way 'launch' tie stays honest", r_mixed["status"] in ("ambiguous", "not_found"), r_mixed["status"])

print("\n" + ("ALL NAVSVC CHECKS PASSED" if fails == 0 else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
