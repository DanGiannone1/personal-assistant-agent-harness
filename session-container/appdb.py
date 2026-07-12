"""Mock Personal Assistant application data store for the POC.

The app state (currentRoute/tasks/events/routes) lives in **Azure Cosmos DB** as ONE
document for the single owner, keyed by a stable owner id (`COSMOS_OWNER_ID`, default
`"owner"`) — NOT the ephemeral per-session id. Personal Assistant is one person's workspace, so the
same document loads on every visit and survives new tabs, reloads, and restarts.
Documents/files stay in the per-session workspace folder. The agent's tools read and
mutate this store and the frontend renders it verbatim via the `/app/state` endpoint,
so "the agent says it did something" and "the record actually exists" are the same fact.

Personal Assistant is a small personal-productivity app. Two record types live here:
a *Task* (a to-do with a status, priority, group bucket, optional due date, and a list
of subtasks) and an *Event* (a calendar entry — a meeting, reminder, or focus block on
a given day). Documents (drafts the assistant writes) live as files in the workspace and
are surfaced separately. There is no user/account hierarchy — it's one person's workspace.
"""

from __future__ import annotations

import os
import random
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from azure.core import MatchConditions
from azure.cosmos import CosmosClient
from azure.cosmos import exceptions as cosmos_exceptions
from azure.identity import DefaultAzureCredential

_LOCK = threading.Lock()

# The app state (currentRoute/tasks/events/routes) is stored as ONE Cosmos document
# keyed by a STABLE owner id (single-user app), so it persists across sessions/tabs/
# restarts. Documents/files stay in the per-session workspace folder. AAD-only (no
# account key): DefaultAzureCredential — az login locally, managed identity in ACA.
_STATE_KEYS = ("currentRoute", "tasks", "events", "routes", "schedules", "library")
# The Engagements page's static route — shared by _seed() and the on-read migration
# in _doc_to_state() so pre-existing owner docs pick the page up without a backfill.
_ENGAGEMENTS_ROUTE = {
    "path": "/engagements",
    "title": "Engagements",
    "keywords": ["engagements", "engagement", "customers", "accounts", "portfolio", "health"],
}
# Single-user POC: one stable key for the owner's data. Swap to the Entra `oid` here
# when multi-user accounts are introduced — nothing else in this module changes.
_OWNER_ID = os.getenv("COSMOS_OWNER_ID", "owner")
_container_singleton = None


def _container():
    """Lazily build (and cache) the Cosmos container client. Fail loud if unconfigured."""
    global _container_singleton
    if _container_singleton is not None:
        return _container_singleton
    with _LOCK:
        if _container_singleton is not None:
            return _container_singleton
        endpoint = os.getenv("COSMOS_ENDPOINT")
        if not endpoint:
            raise RuntimeError(
                "COSMOS_ENDPOINT is not set — Cosmos is required for app state; "
                "refusing to silently fall back to a local file."
            )
        database = os.getenv("COSMOS_DATABASE", "flow")
        container = os.getenv("COSMOS_CONTAINER", "appstate")
        # AAD-only in real environments (az login locally, managed identity in ACA).
        # COSMOS_KEY exists ONLY for the local emulator (real Cosmos is
        # private-endpoint-only and key auth is disabled account-wide).
        key = os.getenv("COSMOS_KEY")
        client = CosmosClient(endpoint, credential=key or DefaultAzureCredential())
        _container_singleton = client.get_database_client(database).get_container_client(container)
        return _container_singleton


def _owner_id() -> str:
    # Single stable key for the one owner's app state — independent of the per-session
    # workspace folder, so the same document loads on every visit.
    return _OWNER_ID

# Task lifecycle. A "Done" task is considered complete / not overdue.
TASK_STATUSES = ["To do", "In progress", "Blocked", "Done"]
TASK_PRIORITIES = ["Low", "Medium", "High"]
DONE_STATUSES = {"done", "complete", "completed", "closed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_library() -> list[dict]:
    """The persistent Library starts pre-loaded with the reference docs in seed_docs/ —
    these are the owner's existing knowledge base (already indexed for RAG). Session
    uploads are added later via Save to Library."""
    seed_dir = Path(__file__).resolve().parent / "seed_docs"
    if not seed_dir.is_dir():
        return []
    return [
        {
            "id": f"lib-{i + 1}",
            "filename": p.name,
            "title": p.stem.replace("-", " ").replace("_", " "),
            "savedAt": _now_iso(),
            "source": "reference",
        }
        for i, p in enumerate(sorted(seed_dir.glob("*.md")))
    ]


def _seed() -> dict:
    """A fresh seeded Personal Assistant dataset — a small set of tasks and calendar events."""
    return {
        "currentRoute": "/home",
        # New sessions start empty — tasks and events are created by the user
        # (manual UI) or the agent, then persisted to Cosmos.
        "tasks": [],
        "events": [],
        # Scheduled reminders — saved prompts the orchestrator runs on a cadence and
        # emails the result. Created by the user (via the agent) and persisted to Cosmos.
        "schedules": [],
        # Persistent document Library (the searchable KB) — pre-loaded with reference docs;
        # session files are promoted in via Save to Library. See library.py.
        "library": _seed_library(),
        # Catalog of navigable pages. `keywords` help the navigate tool resolve
        # free-text destinations deterministically without a separate LLM routing pass.
        # NOTE: the AI Workbench (/assistant) is a frontend-only route and is intentionally
        # NOT listed here.
        "routes": [
            {"path": "/home", "title": "Home", "keywords": ["home", "today", "overview", "agenda", "start", "dashboard"]},
            {"path": "/todo", "title": "To-Do", "keywords": ["todo", "to do", "to-do", "tasks", "task", "list", "checklist"]},
            {"path": "/calendar", "title": "Calendar", "keywords": ["calendar", "schedule", "events", "event", "meetings", "agenda"]},
            {"path": "/documents", "title": "Documents", "keywords": ["documents", "docs", "notes", "files", "drafts", "library"]},
            {"path": "/reminders", "title": "Reminders", "keywords": ["reminders", "reminder", "schedules", "scheduled", "recurring", "digest", "summary email"]},
            _ENGAGEMENTS_ROUTE.copy(),
        ],
    }


def _doc_to_state(doc: dict) -> dict:
    """Strip Cosmos system fields (_rid/_etag/_ts/id/sessionId) → just the app-state shape.

    Collections missing from older docs (e.g. `schedules` added after first seed) are
    coerced to [] so callers never have to null-check.
    """
    state = {k: doc.get(k) for k in _STATE_KEYS}
    for k in ("tasks", "events", "routes", "schedules", "library"):
        if state.get(k) is None:
            state[k] = []
    if state.get("currentRoute") is None:
        state["currentRoute"] = "/home"
    # Self-healing route migration: owner docs seeded before the Engagements page
    # existed lack its route; normalize on read so navigation works without a migration.
    if not any(r.get("path") == "/engagements" for r in state["routes"]):
        state["routes"].append(_ENGAGEMENTS_ROUTE.copy())
    return state


def ensure_seeded() -> dict:
    """Return the owner's state from Cosmos, creating a seeded doc if absent."""
    oid = _owner_id()
    container = _container()
    try:
        return _doc_to_state(container.read_item(item=oid, partition_key=oid))
    except cosmos_exceptions.CosmosResourceNotFoundError:
        data = _seed()
        try:
            container.create_item({"id": oid, "sessionId": oid, **data})
            return data
        except cosmos_exceptions.CosmosResourceExistsError:
            # Lost the create race to another writer — read the winner's doc.
            return _doc_to_state(container.read_item(item=oid, partition_key=oid))


def load() -> dict:
    """Load the owner's state document from Cosmos, seeding first if absent."""
    oid = _owner_id()
    container = _container()
    try:
        return _doc_to_state(container.read_item(item=oid, partition_key=oid))
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return ensure_seeded()


def save(data: dict) -> None:
    """Overwrite the owner doc unconditionally (last-write-wins).

    NOT concurrency-safe — for seeding/admin/tests only. Concurrent mutations (agent
    tools, the reminder scheduler) MUST go through `update()` so a write can't clobber
    another writer's change.
    """
    oid = _owner_id()
    container = _container()
    container.upsert_item({"id": oid, "sessionId": oid, **{k: data.get(k) for k in _STATE_KEYS}})


class AbortWrite(Exception):
    """Raised by an `update()` mutator to return a result WITHOUT writing (validation/no-op)."""

    def __init__(self, result=None):
        super().__init__("aborted")
        self.result = result


_MAX_UPDATE_RETRIES = 10


def update(mutator):
    """Read-modify-write the owner doc with optimistic concurrency (ETag) + retry.

    `mutator(data)` mutates `data` in place and returns a result. It may raise
    `AbortWrite(result)` to return without writing. If another writer commits between our
    read and write (ETag mismatch), we re-read and re-run the mutator — safe because the
    mutator has no side effects until the commit. Jittered backoff de-correlates retrying
    writers; fails loud (rather than silently dropping the write) if contention persists.
    """
    oid = _owner_id()
    container = _container()
    last_exc = None
    for attempt in range(_MAX_UPDATE_RETRIES):
        try:
            doc = container.read_item(item=oid, partition_key=oid)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            ensure_seeded()
            continue
        data = _doc_to_state(doc)
        try:
            result = mutator(data)
        except AbortWrite as abort:
            return abort.result
        body = {"id": oid, "sessionId": oid, **{k: data.get(k) for k in _STATE_KEYS}}
        try:
            container.replace_item(
                item=oid, body=body,
                etag=doc["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            return result
        except cosmos_exceptions.CosmosAccessConditionFailedError as exc:
            last_exc = exc  # a concurrent writer committed first — back off, re-read, retry
            time.sleep(random.uniform(0.02, 0.08) * (attempt + 1))
    raise RuntimeError(
        f"owner doc update failed after {_MAX_UPDATE_RETRIES} retries (write contention)"
    ) from last_exc


# ── Derived helpers ─────────────────────────────────────────────────────────

def task_route(task_id: str) -> str:
    return f"/todo/{task_id}"


def event_route(event_id: str) -> str:
    return f"/calendar/{event_id}"


def find_task(data: dict, task_id: str) -> dict | None:
    return next((t for t in data["tasks"] if t["id"] == task_id), None)


def find_event(data: dict, event_id: str) -> dict | None:
    return next((e for e in data["events"] if e["id"] == event_id), None)


def resolve_task(data: dict, ref: str) -> dict | None:
    """Resolve a task by id, then exact title, then case-insensitive substring."""
    ref = (ref or "").strip()
    if not ref:
        return None
    by_id = find_task(data, ref)
    if by_id:
        return by_id
    low = ref.lower()
    exact = [t for t in data["tasks"] if t["title"].lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [t for t in data["tasks"] if low in t["title"].lower()]
    return partial[0] if len(partial) == 1 else None


def resolve_event(data: dict, ref: str) -> dict | None:
    """Resolve an event by id, then exact title, then case-insensitive substring."""
    ref = (ref or "").strip()
    if not ref:
        return None
    by_id = find_event(data, ref)
    if by_id:
        return by_id
    low = ref.lower()
    exact = [e for e in data["events"] if e["title"].lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [e for e in data["events"] if low in e["title"].lower()]
    return partial[0] if len(partial) == 1 else None


def is_overdue(task: dict, today: str | None = None) -> bool:
    """A task is overdue iff its due date is past today and it isn't done."""
    if str(task.get("status", "")).lower() in DONE_STATUSES:
        return False
    d = (task.get("dueDate") or "")[:10]
    today = today or datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.strptime(d, "%Y-%m-%d").date() < datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return False


def resolve_destination(data: dict, destination: str, engagements: list[dict] | None = None) -> dict:
    """Resolve a free-text destination to a concrete route.

    Returns one of:
      {"status": "resolved", "path": str, "title": str}
      {"status": "ambiguous", "candidates": [{"path","title"}...]}
      {"status": "not_found", "candidates": [...]}

    Deterministic matching only — no LLM. This is the contrast to a multi-call
    navigation-agent design: the agent makes ONE navigate call and gets a grounded
    answer (or a small candidate list to disambiguate). It matches over the static
    routes plus individual tasks and events by title.
    """
    q = (destination or "").strip().lower()
    engagements = engagements or []
    if not q:
        return {"status": "not_found", "candidates": _all_destinations(data, engagements)[:8]}

    # 1) Exact static route path or title.
    for route in data["routes"]:
        if q == route["path"].lower() or q == route["title"].lower():
            return {"status": "resolved", "path": route["path"], "title": route["title"]}

    # 2) Tasks / events / engagements by exact title.
    t_exact = [t for t in data["tasks"] if t["title"].lower() == q]
    e_exact = [e for e in data["events"] if e["title"].lower() == q]
    g_exact = [g for g in engagements if g["title"].lower() == q]
    if len(t_exact) + len(e_exact) + len(g_exact) == 1:
        if t_exact:
            t = t_exact[0]
            return {"status": "resolved", "path": task_route(t["id"]), "title": t["title"]}
        if e_exact:
            e = e_exact[0]
            return {"status": "resolved", "path": event_route(e["id"]), "title": e["title"]}
        g = g_exact[0]
        return {"status": "resolved", "path": engagement_route(g["id"]), "title": g["title"]}

    # 3) Word-boundary / keyword matching across routes + tasks + events. Deliberately NOT
    # raw bidirectional substring (a 1-2 char query like "x" must not match inside a word).
    def _word_in(needle: str, hay: str) -> bool:
        needle = needle.strip().lower()
        return bool(needle) and re.search(r"\b" + re.escape(needle) + r"\b", hay) is not None

    # Filler words that may surround a real destination ("my calendar", "the documents
    # page"). A keyword match is only trusted if, after removing the matched keyword and
    # these stopwords, NO content words remain — otherwise "crypto mining dashboard" would
    # resolve to Home via the "dashboard" keyword instead of failing loud.
    _STOPWORDS = {"my", "the", "a", "an", "to", "go", "goto", "take", "me", "please",
                  "page", "section", "view", "tab", "screen", "area", "open", "show",
                  "of", "for", "in", "on", "into", "us", "back"}
    q_tokens = set(re.findall(r"[a-z0-9]+", q))

    matches: list[dict] = []
    for route in data["routes"]:
        title = route["title"].lower()
        kws = [k.lower() for k in route.get("keywords", [])]
        title_sub = len(q) >= 3 and q in title
        kw_hits = [kw for kw in kws if _word_in(kw, q)]
        q_in_kw = len(q) >= 3 and any(q in kw for kw in kws)
        if not (title_sub or kw_hits or q_in_kw):
            continue
        # Guard: a match resting ONLY on a keyword must not leave unexplained content words.
        if kw_hits and not title_sub and not q_in_kw:
            kw_tokens = {t for kw in kw_hits for t in re.findall(r"[a-z0-9]+", kw)}
            residual = q_tokens - kw_tokens - _STOPWORDS
            if residual:
                continue
        matches.append({"path": route["path"], "title": route["title"]})
    for t in data["tasks"]:
        if len(q) >= 3 and q in t["title"].lower():
            matches.append({"path": task_route(t["id"]), "title": t["title"]})
    for e in data["events"]:
        if len(q) >= 3 and q in e["title"].lower():
            matches.append({"path": event_route(e["id"]), "title": e["title"]})
    for g in engagements:
        if len(q) >= 3 and q in g["title"].lower():
            matches.append({"path": engagement_route(g["id"]), "title": g["title"]})

    seen: set[str] = set()
    deduped = [m for m in matches if not (m["path"] in seen or seen.add(m["path"]))]

    if len(deduped) == 1:
        return {"status": "resolved", "path": deduped[0]["path"], "title": deduped[0]["title"]}
    if len(deduped) > 1:
        return {"status": "ambiguous", "candidates": deduped}
    return {"status": "not_found", "candidates": _all_destinations(data, engagements)[:8]}


def _all_destinations(data: dict, engagements: list[dict] | None = None) -> list[dict]:
    dests = [{"path": r["path"], "title": r["title"]} for r in data["routes"]]
    dests += [{"path": task_route(t["id"]), "title": t["title"]} for t in data["tasks"]]
    dests += [{"path": event_route(e["id"]), "title": e["title"]} for e in data["events"]]
    dests += [{"path": engagement_route(g["id"]), "title": g["title"]} for g in (engagements or [])]
    return dests


def new_id(prefix: str, existing: list[dict]) -> str:
    ids = {item["id"] for item in existing}
    n = len(existing) + 1
    while f"{prefix}-{n}" in ids:
        n += 1
    return f"{prefix}-{n}"


# ── Scheduled reminders ──────────────────────────────────────────────────────
# A schedule is a saved prompt the orchestrator runs on a cadence, emailing the
# result. Cadence is intentionally simple (daily / weekly at HH:MM in a timezone) —
# no cron dependency. `nextRunAt` is a UTC ISO timestamp the scheduler compares to now.

SCHEDULE_FREQUENCIES = ["daily", "weekly"]
# Monday=0 … Sunday=6 (matches datetime.weekday()).
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def find_schedule(data: dict, schedule_id: str) -> dict | None:
    return next((s for s in data.get("schedules", []) if s["id"] == schedule_id), None)


def find_library_doc(data: dict, filename: str) -> dict | None:
    return next((d for d in data.get("library", []) if d["filename"] == filename), None)


def resolve_schedule(data: dict, ref: str) -> dict | None:
    """Resolve a schedule by id, then exact title, then case-insensitive substring."""
    ref = (ref or "").strip()
    if not ref:
        return None
    by_id = find_schedule(data, ref)
    if by_id:
        return by_id
    low = ref.lower()
    schedules = data.get("schedules", [])
    exact = [s for s in schedules if s["title"].lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [s for s in schedules if low in s["title"].lower()]
    return partial[0] if len(partial) == 1 else None


def _parse_hhmm(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' (24h) → (hour, minute); raises ValueError on bad input."""
    parts = (time_str or "").strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"time must be HH:MM (24h), got {time_str!r}")
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"time out of range: {time_str!r}")
    return hh, mm


def normalize_timezone(timezone_name: str) -> str:
    """Validate a tz name, returning it normalized; raises ValueError if unknown."""
    tz = (timezone_name or "UTC").strip() or "UTC"
    try:
        ZoneInfo(tz)
    except Exception as exc:  # ZoneInfoNotFoundError + others
        raise ValueError(f"unknown timezone {tz!r}") from exc
    return tz


def compute_next_run(frequency: str, time_str: str, timezone_name: str,
                     days_of_week: list[int] | None = None,
                     after: datetime | None = None) -> datetime:
    """Return the next UTC datetime a schedule should fire, strictly after `after`.

    `time_str` is HH:MM in the schedule's own timezone. daily = every day at that
    time; weekly = on each listed day-of-week (Mon=0…Sun=6) at that time.
    """
    hh, mm = _parse_hhmm(time_str)
    tz = ZoneInfo(normalize_timezone(timezone_name))
    after = (after or datetime.now(timezone.utc)).astimezone(timezone.utc)
    local_after = after.astimezone(tz)
    if (frequency or "daily").lower() == "weekly":
        days = sorted(set(days_of_week or []))
        if not days:
            raise ValueError("weekly schedule requires at least one day of week")
    else:
        days = list(range(7))  # daily = every day
    # Scan forward up to 8 days for the next matching (day, time) strictly after `after`.
    for delta in range(0, 8):
        d = (local_after + timedelta(days=delta)).date()
        if d.weekday() not in days:
            continue
        candidate = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(timezone.utc)
        if candidate > after:
            return candidate
    raise RuntimeError("could not compute next run within 8 days")  # unreachable


def schedule_summary(s: dict) -> str:
    """One-line human description of a schedule's cadence, e.g. 'Daily at 08:00 (UTC)'."""
    freq = (s.get("frequency") or "daily").lower()
    tz = s.get("timezone") or "UTC"
    when = s.get("time") or "??:??"
    if freq == "weekly":
        days = ", ".join(DAY_NAMES[d] for d in sorted(s.get("daysOfWeek") or []) if 0 <= d <= 6)
        return f"Weekly on {days or '—'} at {when} ({tz})"
    return f"Daily at {when} ({tz})"


# ── Engagements (shared scope) ───────────────────────────────────────────────
# One Cosmos doc PER engagement (id == sessionId == "eng-<8 hex>", so each
# engagement is its own partition), in the same container as the owner doc.
# Engagements are the collaboration surface: they are shared by construction —
# nothing in them is keyed by the owner. Same optimistic-ETag discipline as the
# owner doc, so a health change and its explanatory note commit atomically and
# concurrent editors converge through the retry loop. See docs/engagements.md.

ENGAGEMENT_STAGES = ["Discovery", "Design", "Build", "Deploy", "Live", "Closed"]
HEALTH_LEVELS = ["green", "amber", "red"]
MILESTONE_STATUSES = ["Planned", "In progress", "Done", "Slipped"]
RISK_SEVERITIES = ["Low", "Medium", "High"]
RISK_STATUSES = ["Open", "Mitigating", "Closed"]
ACTION_STATUSES = ["Open", "Done"]
# kind → (list field on the doc, id prefix). The item tools take a `kind`
# argument rather than spawning nine near-identical tools.
ENGAGEMENT_ITEM_KINDS = {
    "milestone": ("milestones", "m"),
    "risk": ("risks", "r"),
    "action": ("actions", "a"),
}

_ENGAGEMENT_FIELDS = (
    "title", "customer", "stage", "health", "healthNote", "members",
    "startDate", "targetDate", "notes", "milestones", "risks", "actions",
    "createdAt", "updatedAt",
)


def _engagement_to_state(doc: dict) -> dict:
    """Strip Cosmos system fields → the engagement shape; coerce missing collections."""
    eng = {"id": doc["id"]}
    for k in _ENGAGEMENT_FIELDS:
        eng[k] = doc.get(k)
    for k in ("milestones", "risks", "actions", "members"):
        if eng.get(k) is None:
            eng[k] = []
    if not eng.get("stage"):
        eng["stage"] = ENGAGEMENT_STAGES[0]
    if not eng.get("health"):
        eng["health"] = "green"
    for k in ("title", "customer", "healthNote", "notes", "startDate", "targetDate"):
        if eng.get(k) is None:
            eng[k] = ""
    return eng


def engagement_route(engagement_id: str) -> str:
    return f"/engagements/{engagement_id}"


def create_engagement(title: str, customer: str = "", stage: str = "",
                      health: str = "", health_note: str = "",
                      start_date: str = "", target_date: str = "",
                      notes: str = "") -> dict:
    """Create a new engagement doc. Raises ValueError on bad stage/health."""
    title = (title or "").strip()
    if not title:
        raise ValueError("engagement title is required")
    stage = (stage or ENGAGEMENT_STAGES[0]).strip() or ENGAGEMENT_STAGES[0]
    if stage not in ENGAGEMENT_STAGES:
        raise ValueError(f"stage must be one of {ENGAGEMENT_STAGES}")
    health = (health or "green").strip().lower() or "green"
    if health not in HEALTH_LEVELS:
        raise ValueError(f"health must be one of {HEALTH_LEVELS}")
    eid = "eng-" + uuid.uuid4().hex[:8]
    now = _now_iso()
    doc = {
        "id": eid, "sessionId": eid, "type": "engagement",
        "title": title, "customer": (customer or "").strip(), "stage": stage,
        "health": health, "healthNote": (health_note or "").strip(),
        "members": [], "startDate": (start_date or "").strip(),
        "targetDate": (target_date or "").strip(), "notes": (notes or "").strip(),
        "milestones": [], "risks": [], "actions": [],
        "createdAt": now, "updatedAt": now,
    }
    _container().create_item(doc)
    return _engagement_to_state(doc)


def list_engagements() -> list[dict]:
    """All engagement docs (cross-partition query — fine at team scale), oldest first."""
    docs = _container().query_items(
        query="SELECT * FROM c WHERE c.type = 'engagement'",
        enable_cross_partition_query=True,
    )
    return sorted((_engagement_to_state(d) for d in docs),
                  key=lambda e: (e.get("createdAt") or "", e["id"]))


def load_engagement(engagement_id: str) -> dict | None:
    try:
        doc = _container().read_item(item=engagement_id, partition_key=engagement_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return None
    if doc.get("type") != "engagement":
        return None
    return _engagement_to_state(doc)


def update_engagement(engagement_id: str, mutator):
    """Read-modify-write ONE engagement doc — same ETag+retry semantics as `update()`.

    Raises KeyError if the engagement doesn't exist; callers map that to 404 (REST)
    or an `error` outcome (tools). `mutator(eng)` mutates in place; AbortWrite works
    exactly as it does for the owner doc.
    """
    container = _container()
    last_exc = None
    for attempt in range(_MAX_UPDATE_RETRIES):
        try:
            doc = container.read_item(item=engagement_id, partition_key=engagement_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            raise KeyError(f"engagement {engagement_id!r} not found")
        if doc.get("type") != "engagement":
            raise KeyError(f"engagement {engagement_id!r} not found")
        eng = _engagement_to_state(doc)
        try:
            result = mutator(eng)
        except AbortWrite as abort:
            return abort.result
        eng["updatedAt"] = _now_iso()
        body = {"id": engagement_id, "sessionId": engagement_id, "type": "engagement",
                **{k: eng.get(k) for k in _ENGAGEMENT_FIELDS}}
        try:
            container.replace_item(
                item=engagement_id, body=body,
                etag=doc["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            return result
        except cosmos_exceptions.CosmosAccessConditionFailedError as exc:
            last_exc = exc  # a concurrent writer committed first — back off, re-read, retry
            time.sleep(random.uniform(0.02, 0.08) * (attempt + 1))
    raise RuntimeError(
        f"engagement doc update failed after {_MAX_UPDATE_RETRIES} retries (write contention)"
    ) from last_exc


def delete_engagement(engagement_id: str) -> bool:
    """Delete an engagement doc; True if it existed."""
    try:
        _container().delete_item(item=engagement_id, partition_key=engagement_id)
        return True
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return False


def resolve_engagement(ref: str, engagements: list[dict] | None = None) -> dict | None:
    """Resolve an engagement by id, then exact title, then unique title substring."""
    ref = (ref or "").strip()
    if not ref:
        return None
    engs = engagements if engagements is not None else list_engagements()
    by_id = next((g for g in engs if g["id"] == ref), None)
    if by_id:
        return by_id
    low = ref.lower()
    exact = [g for g in engs if g["title"].lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [g for g in engs if low in g["title"].lower()]
    return partial[0] if len(partial) == 1 else None


def find_engagement_item(eng: dict, kind: str, ref: str) -> dict | None:
    """Resolve a milestone/risk/action within an engagement by id, exact title, or
    unique title substring."""
    field, _prefix = ENGAGEMENT_ITEM_KINDS[kind]
    items = eng.get(field) or []
    ref = (ref or "").strip()
    if not ref:
        return None
    by_id = next((i for i in items if i["id"] == ref), None)
    if by_id:
        return by_id
    low = ref.lower()
    exact = [i for i in items if i["title"].lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [i for i in items if low in i["title"].lower()]
    return partial[0] if len(partial) == 1 else None
