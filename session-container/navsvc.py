"""Navigation service — the route registry and destination ranking.

Implements the bare-bones design from docs/navigation-reference-architecture.md:

- A **route registry** in code: static personal pages + parameterized engagement pages +
  individual records. Destinations are always derived from live state — never stored.
- ``rank_destinations(context, utterance?)`` — ONE scoring function, two consumers:
  with an utterance it powers the navigate tool's resolution; without one it powers
  the no-AI quick links.
- Resolution **selects, never generates**: every candidate comes from the registry, so
  no caller (model included) can produce a route that doesn't exist.

Matching is deterministic (lexical + context ranking). The in-tool LLM tie-break slot
sits behind ``resolve()``'s margin check — when the top candidates are genuinely close
the result is honest candidates, which the navigate tool may pass to a bounded decide
step or surface as chips.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import appdb

# ── Registry ─────────────────────────────────────────────────────────────────

_STATIC = [
    {"path": "/home", "title": "Home", "keywords": ["home", "today", "overview", "agenda", "start", "dashboard"]},
    {"path": "/todo", "title": "Tasks", "keywords": ["todo", "to do", "to-do", "tasks", "task", "list", "checklist"]},
    {"path": "/calendar", "title": "Calendar", "keywords": ["calendar", "schedule", "events", "event", "meetings", "agenda"]},
    {"path": "/documents", "title": "Documents", "keywords": ["documents", "docs", "notes", "files", "drafts", "library"]},
    {"path": "/reminders", "title": "Reminders", "keywords": ["reminders", "reminder", "schedules", "scheduled", "recurring", "digest", "summary email"]},
    {"path": "/engagements", "title": "Engagements", "keywords": ["engagements", "engagement list", "workspaces", "shared"]},
]

_ENGAGEMENT_PAGES = [
    ("", "{name}", ["engagement", "overview"]),
    ("/tasks", "{name} · Tasks", ["tasks", "todo", "to-do", "checklist"]),
    ("/documents", "{name} · Documents", ["documents", "docs", "files", "artifacts"]),
    ("/settings", "{name} · Settings", ["settings", "members", "sharing", "conventions"]),
]


def destinations(personal: dict, engagements: list[dict]) -> list[dict]:
    """Every real destination for this user, derived live: static pages, personal
    records, each member engagement's pages and records."""
    dests: list[dict] = [dict(d, kind="page") for d in _STATIC]
    for t in personal.get("tasks", []):
        dests.append({"path": appdb.task_route(t["id"]), "title": t["title"], "kind": "task",
                      "keywords": [], "record": t})
    for e in personal.get("events", []):
        dests.append({"path": appdb.event_route(e["id"]), "title": e["title"], "kind": "event",
                      "keywords": [], "record": e})
    for p in engagements:
        base = f"/engagements/{p['id']}"
        pname = p["name"]
        for suffix, title_tpl, kws in _ENGAGEMENT_PAGES:
            dests.append({
                "path": base + suffix, "title": title_tpl.format(name=pname),
                "kind": "engagement-page", "keywords": [*kws, pname.lower()],
                "engagementId": p["id"], "engagementName": pname,
            })
        for t in p.get("tasks", []):
            dests.append({"path": f"{base}/tasks/{t['id']}", "title": f"{t['title']} ({pname})",
                          "kind": "task", "keywords": [pname.lower()], "engagementId": p["id"],
                          "record": t, "bareTitle": t["title"]})
    return dests


# ── Ranking ──────────────────────────────────────────────────────────────────

_STOPWORDS = {"my", "the", "a", "an", "to", "go", "goto", "take", "me", "please",
              "page", "section", "view", "tab", "screen", "area", "open", "show",
              "of", "for", "in", "on", "into", "us", "back",
              "engagement", "engagements", "project", "projects"}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _lexical_score(dest: dict, q: str, q_tokens: set[str]) -> float:
    """0 = no match. Exact title/path > full-phrase substring > token overlap."""
    title = (dest.get("bareTitle") or dest["title"]).lower()
    full_title = dest["title"].lower()
    if q == title or q == full_title or q == dest["path"].lower():
        return 100.0
    score = 0.0
    if len(q) >= 3 and (q in title or q in full_title):
        score += 40.0
    kws = [k.lower() for k in dest.get("keywords", [])]
    kw_tokens = set()
    for kw in kws:
        kw_tokens |= _tokens(kw)
    title_tokens = _tokens(title) | _tokens(dest.get("engagementName", ""))
    matchable = title_tokens | kw_tokens
    content = q_tokens - _STOPWORDS
    if not content:
        return score
    hits = content & matchable
    if not hits:
        return score
    coverage = len(hits) / len(content)          # how much of the ask we explain
    specificity = len(hits) / max(len(title_tokens) or 1, 1)
    score += 30.0 * coverage + 10.0 * min(specificity, 1.0)
    # Fail-loud guard (the "crypto mining dashboard" rule): a keyword-only match that
    # leaves content words unexplained is NOT a match unless something else scored.
    residual = content - matchable
    if residual and score < 40.0:
        return 0.0
    return score


def _context_boost(dest: dict, visits: list[dict], today: str) -> float:
    """Recency + salience. Bounded so lexical relevance stays dominant for asks."""
    boost = 0.0
    path = dest["path"]
    for i, v in enumerate(visits[:30]):
        if v.get("path") == path:
            # Steep, most-recent-heavy decay ("start with last visited"): the page the
            # user is coming FROM must decisively out-rank one they touched a few
            # clicks earlier, or lexically-tied asks degrade into interrogation.
            boost += max(6.0 - i * 1.0, 0.5)
            break
    rec = dest.get("record")
    if rec is not None and "status" in rec and appdb.is_overdue(rec, today):
        boost += 4.0                              # overdue tasks float up
    due = (rec or {}).get("dueDate") or (rec or {}).get("date") or ""
    if due[:10] == today:
        boost += 3.0
    return boost


def rank_destinations(personal: dict, engagements: list[dict], visits: list[dict],
                      utterance: str | None = None, today: str | None = None,
                      limit: int = 8) -> list[dict]:
    """The one scoring layer, two consumers.

    With `utterance`: candidates for resolution (lexical dominates, context breaks ties).
    Without: the quick-links ranking (context only — recency, salience).
    """
    today = today or datetime.now(timezone.utc).date().isoformat()
    dests = destinations(personal, engagements)
    q = (utterance or "").strip().lower()
    q_tokens = _tokens(q)
    scored = []
    for d in dests:
        lex = _lexical_score(d, q, q_tokens) if q else 0.0
        if q and lex <= 0.0:
            continue
        ctx = _context_boost(d, visits, today)
        if not q and d["kind"] == "page" and d["path"] == "/home":
            continue                              # quick links never suggest Home (you're on it)
        scored.append({**d, "score": round(lex + ctx, 2), "lex": lex})
    scored.sort(key=lambda x: -x["score"])
    return scored[:limit]


def resolve(personal: dict, engagements: list[dict], visits: list[dict],
            utterance: str, today: str | None = None) -> dict:
    """Grounded resolution with a decisive bias (decide, don't interrogate).

    resolved  — a single candidate, or a clear winner by score margin
    ambiguous — top candidates are genuinely close (the tool may LLM-tie-break or chip)
    not_found — nothing plausible; returns real fallback options
    """
    ranked = rank_destinations(personal, engagements, visits, utterance, today, limit=8)
    if not ranked:
        fallback = rank_destinations(personal, engagements, visits, None, today, limit=8)
        return {"status": "not_found", "candidates": _strip(fallback)}
    if len(ranked) == 1:
        return {"status": "resolved", **_pub(ranked[0])}
    top, second = ranked[0], ranked[1]
    # Two-stage decision (deterministic first, context as tie-break — never the reverse):
    # 1. A clear LEXICAL winner resolves outright — relevance beats familiarity, so a
    #    strong wording match can't be overridden by "you visit that other page a lot".
    if top["lex"] >= second["lex"] + 12.0 or (second["lex"] > 0 and top["lex"] / second["lex"] >= 1.6):
        return {"status": "resolved", **_pub(top)}
    # 2. Lexically tied (the "two Launch engagements" case): user context settles it with a
    #    much smaller margin — recency/salience exist exactly to break these ties. This
    #    is the decide-don't-interrogate rule; genuinely context-less ties stay honest
    #    and return candidates.
    if abs(top["lex"] - second["lex"]) < 12.0 and top["score"] >= second["score"] + 3.0:
        # Context (not wording) decided — carry the beaten rivals as `alternates`, the
        # escape hatch the UI renders as "Did you mean" chips. A stage-1 lexical win
        # deliberately carries none: the user's own words picked it.
        ties = [r for r in ranked[1:] if abs(top["lex"] - r["lex"]) < 12.0]
        return {"status": "resolved", **_pub(top), "alternates": _strip(ties[:5])}
    close = [r for r in ranked if r["score"] >= top["score"] - 12.0]
    return {"status": "ambiguous", "candidates": _strip(close)}


def _pub(d: dict) -> dict:
    return {"path": d["path"], "title": d["title"]}


def _strip(ds: list[dict]) -> list[dict]:
    return [_pub(d) for d in ds]
