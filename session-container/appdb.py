"""Personal Assistant application data store.

App state (currentRoute/tasks/events/schedules/library/routes) lives in **Azure Cosmos DB**
as ONE document **per user**, keyed by the signed-in user's id — bound per request/turn via
`set_current_user()` and NEVER guessed (an unbound call fails loud). A `users` container
holds the seeded demo accounts (username + salted PBKDF2 password hash). Each user's
document loads on every visit and survives new tabs, reloads, and restarts.
Documents/files stay in the per-session workspace folder. The agent's tools read and
mutate this store and the frontend renders it verbatim via the `/app/state` endpoint,
so "the agent says it did something" and "the record actually exists" are the same fact.

Personal Assistant is a small personal-productivity app. Two record types live here:
a *Task* (a to-do with a status, priority, group bucket, optional due date, and a list
of subtasks) and an *Event* (a calendar entry — a meeting, reminder, or focus block on
a given day). Documents (drafts the assistant writes) live as files in the workspace and
are surfaced separately.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import os
import random
import re
import secrets
import threading
import time
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
# Multi-user: the owner of app state is the SIGNED-IN USER, bound per request/turn via
# `set_current_user()` (the orchestrator middleware and the session container both set it
# from the authenticated caller). `COSMOS_OWNER_ID` remains as an explicit single-user
# escape hatch (admin scripts, legacy deploys) — but there is NO implicit default: an
# appdb call with neither set is a bug and fails loud rather than silently sharing one doc.
_CURRENT_USER: contextvars.ContextVar[str | None] = contextvars.ContextVar("appdb_user", default=None)
_container_singleton = None
_users_singleton = None


def set_current_user(user_id: str | None) -> contextvars.Token:
    """Bind the signed-in user for this request/turn context. Returns the reset token."""
    return _CURRENT_USER.set(user_id)


def reset_current_user(token: contextvars.Token) -> None:
    _CURRENT_USER.reset(token)


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
        client = CosmosClient(endpoint, credential=DefaultAzureCredential())
        _container_singleton = client.get_database_client(database).get_container_client(container)
        return _container_singleton


def _owner_id() -> str:
    """The signed-in user whose app state this request touches. Fail loud when unbound."""
    uid = _CURRENT_USER.get()
    if uid:
        return uid
    env = os.getenv("COSMOS_OWNER_ID")
    if env:
        return env
    raise RuntimeError(
        "No user bound for this appdb call — set_current_user() was not called for this "
        "request/turn (and COSMOS_OWNER_ID is unset). Refusing to guess whose data this is."
    )


# ── Users (accounts) ─────────────────────────────────────────────────────────
# Demo-grade accounts per the projects spec: seeded users, salted PBKDF2 password hashes,
# no self-registration. The seam to a real identity provider is the login handler only.

def _users_container():
    global _users_singleton
    if _users_singleton is not None:
        return _users_singleton
    with _LOCK:
        if _users_singleton is not None:
            return _users_singleton
        endpoint = os.getenv("COSMOS_ENDPOINT")
        if not endpoint:
            raise RuntimeError("COSMOS_ENDPOINT is not set — Cosmos is required for accounts.")
        database = os.getenv("COSMOS_DATABASE", "flow")
        client = CosmosClient(endpoint, credential=DefaultAzureCredential())
        _users_singleton = client.get_database_client(database).get_container_client(
            os.getenv("COSMOS_USERS_CONTAINER", "users")
        )
        return _users_singleton


_PBKDF2_ITERATIONS = 300_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2-sha256$%d$%s$%s" % (
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_b64, hash_b64 = stored.split("$")
        if scheme != "pbkdf2-sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), base64.b64decode(salt_b64), int(iters)
        )
        return secrets.compare_digest(digest, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def get_user(username: str) -> dict | None:
    """Look up a user by username (usernames are unique by seed construction)."""
    rows = list(_users_container().query_items(
        query="SELECT * FROM c WHERE c.username = @u",
        parameters=[{"name": "@u", "value": (username or "").strip().lower()}],
        enable_cross_partition_query=True,
    ))
    return rows[0] if rows else None


def get_user_by_id(user_id: str) -> dict | None:
    try:
        return _users_container().read_item(item=user_id, partition_key=user_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return None


# Demo fixture per the projects spec: dan / ava / sam. Passwords are demo-grade on purpose.
_SEED_USERS = [
    {"id": "u-dan", "username": "dan", "displayName": "Dan", "password": "dan-demo-1"},
    {"id": "u-ava", "username": "ava", "displayName": "Ava", "password": "ava-demo-1"},
    {"id": "u-sam", "username": "sam", "displayName": "Sam", "password": "sam-demo-1"},
]


def list_users() -> list[dict]:
    """All seeded users (the scheduler iterates these; volumes are tiny by design)."""
    return list(_users_container().query_items(
        query="SELECT * FROM c", enable_cross_partition_query=True,
    ))


def ensure_seeded_users() -> int:
    """Create the seeded demo users if absent (idempotent). Returns how many were created."""
    created = 0
    for spec in _SEED_USERS:
        if get_user_by_id(spec["id"]) is None:
            _users_container().create_item({
                "id": spec["id"], "username": spec["username"],
                "displayName": spec["displayName"],
                "passwordHash": hash_password(spec["password"]),
                "persona": {}, "createdAt": _now_iso(),
            })
            created += 1
    return created

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


def _etag_update(container, doc_id: str, mutator, to_state, to_body, on_missing=None):
    """Read-modify-write ANY doc with optimistic concurrency (ETag) + retry.

    `mutator(data)` mutates `data` in place and returns a result. It may raise
    `AbortWrite(result)` to return without writing. If another writer commits between our
    read and write (ETag mismatch), we re-read and re-run the mutator — safe because the
    mutator has no side effects until the commit. Jittered backoff de-correlates retrying
    writers; fails loud (rather than silently dropping the write) if contention persists.
    `on_missing` (if given) is called when the doc doesn't exist yet, then we retry.
    """
    last_exc = None
    for attempt in range(_MAX_UPDATE_RETRIES):
        try:
            doc = container.read_item(item=doc_id, partition_key=doc_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            if on_missing is None:
                raise
            on_missing()
            continue
        data = to_state(doc)
        try:
            result = mutator(data)
        except AbortWrite as abort:
            return abort.result
        try:
            container.replace_item(
                item=doc_id, body=to_body(data),
                etag=doc["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            return result
        except cosmos_exceptions.CosmosAccessConditionFailedError as exc:
            last_exc = exc  # a concurrent writer committed first — back off, re-read, retry
            time.sleep(random.uniform(0.02, 0.08) * (attempt + 1))
    raise RuntimeError(
        f"doc '{doc_id}' update failed after {_MAX_UPDATE_RETRIES} retries (write contention)"
    ) from last_exc


def update(mutator):
    """ETag-safe read-modify-write of the signed-in user's personal-space doc."""
    oid = _owner_id()
    return _etag_update(
        _container(), oid, mutator,
        to_state=_doc_to_state,
        to_body=lambda data: {"id": oid, "sessionId": oid, **{k: data.get(k) for k in _STATE_KEYS}},
        on_missing=ensure_seeded,
    )


# ── Projects (spec F2/F3): shared scopes with membership ────────────────────
# One Cosmos document per project — records + conventions + members in one doc, so the
# same ETag-safe mutation path protects concurrent edits by different members.

_projects_singleton = None
PROJECT_ROLES = ("owner", "editor", "viewer")
# Roles that may mutate records / manage members. Viewers only read.
_WRITE_ROLES = ("owner", "editor")


def _projects_container():
    global _projects_singleton
    if _projects_singleton is not None:
        return _projects_singleton
    with _LOCK:
        if _projects_singleton is not None:
            return _projects_singleton
        endpoint = os.getenv("COSMOS_ENDPOINT")
        if not endpoint:
            raise RuntimeError("COSMOS_ENDPOINT is not set — Cosmos is required for projects.")
        database = os.getenv("COSMOS_DATABASE", "flow")
        client = CosmosClient(endpoint, credential=DefaultAzureCredential())
        _projects_singleton = client.get_database_client(database).get_container_client(
            os.getenv("COSMOS_PROJECTS_CONTAINER", "projects")
        )
        return _projects_singleton


_PROJECT_KEYS = ("name", "description", "archived", "members", "conventions",
                 "tasks", "events", "library", "createdAt")


def _project_to_state(doc: dict) -> dict:
    state = {"id": doc["id"], **{k: doc.get(k) for k in _PROJECT_KEYS}}
    for k in ("members", "conventions", "tasks", "events", "library"):
        if state.get(k) is None:
            state[k] = []
    state["archived"] = bool(state.get("archived"))
    return state


def project_role(project: dict, user_id: str) -> str | None:
    """The user's role in the project, or None when not a member."""
    for m in project.get("members", []):
        if m.get("userId") == user_id:
            return m.get("role")
    return None


def can_write(role: str | None) -> bool:
    return role in _WRITE_ROLES


def create_project(name: str, user_id: str, description: str = "") -> dict:
    project = {
        "id": f"p-{secrets.token_hex(4)}",
        "name": name.strip(),
        "description": (description or "").strip(),
        "archived": False,
        "members": [{"userId": user_id, "role": "owner"}],
        "conventions": [],
        "tasks": [], "events": [], "library": [],
        "createdAt": _now_iso(),
    }
    _projects_container().create_item(project)
    return _project_to_state(project)


def get_project(project_id: str) -> dict | None:
    """Raw project read WITHOUT membership gating — callers must gate on project_role."""
    try:
        return _project_to_state(
            _projects_container().read_item(item=project_id, partition_key=project_id)
        )
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return None


def get_project_for(project_id: str, user_id: str) -> tuple[dict, str] | None:
    """Membership-gated read: (project, role), or None when absent OR not a member —
    deliberately indistinguishable (a non-member gets a 404, not a hidden button)."""
    project = get_project(project_id)
    if project is None:
        return None
    role = project_role(project, user_id)
    if role is None:
        return None
    return project, role


def list_projects_for(user_id: str, include_archived: bool = False) -> list[dict]:
    """All projects the user is a member of (full docs; demo volumes are tiny)."""
    rows = _projects_container().query_items(
        query=("SELECT * FROM c WHERE EXISTS("
               "SELECT VALUE m FROM m IN c.members WHERE m.userId = @u)"),
        parameters=[{"name": "@u", "value": user_id}],
        enable_cross_partition_query=True,
    )
    projects = [_project_to_state(doc) for doc in rows]
    if not include_archived:
        projects = [p for p in projects if not p["archived"]]
    return sorted(projects, key=lambda p: p["name"].lower())


def update_project(project_id: str, mutator):
    """ETag-safe read-modify-write of one project doc (missing project raises)."""
    return _etag_update(
        _projects_container(), project_id, mutator,
        to_state=_project_to_state,
        to_body=lambda data: {"id": project_id, **{k: data.get(k) for k in _PROJECT_KEYS}},
    )


def resolve_project(ref: str, user_id: str) -> dict | None:
    """Resolve a project by id, exact name, then unique substring — among the USER'S
    projects only (membership is a query-scope property, not an afterthought filter)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    projects = list_projects_for(user_id)
    low = ref.lower()
    by_id = [p for p in projects if p["id"] == ref]
    if by_id:
        return by_id[0]
    exact = [p for p in projects if p["name"].lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [p for p in projects if low in p["name"].lower()]
    return partial[0] if len(partial) == 1 else None


# Demo fixture per the projects spec: two similarly-named "Launch" projects (the M3
# ambiguity fixture), different membership/roles per user, one French convention (F7/F8).
def ensure_seeded_projects() -> int:
    """Create the seeded demo projects if absent (idempotent by name). Returns # created."""
    existing = {p["name"] for p in list_projects_for("u-dan", include_archived=True)}
    existing |= {p["name"] for p in list_projects_for("u-ava", include_archived=True)}
    created = 0
    if "Website Launch" not in existing:
        p = create_project("Website Launch", "u-dan", "Marketing site relaunch")
        def _seed_site(d):
            d["members"].append({"userId": "u-sam", "role": "viewer"})
            d["tasks"].append({
                "id": "t-1", "title": "Draft launch checklist", "status": "In progress",
                "priority": "High", "group": "General", "dueDate": "",
                "subtasks": [], "notes": "", "createdAt": _now_iso(),
            })
            d["events"].append({
                "id": "e-1", "title": "Launch go/no-go", "date": "2026-07-17",
                "start": "10:00", "end": "10:30", "type": "Meeting", "notes": "",
            })
        update_project(p["id"], _seed_site)
        created += 1
    if "Product Launch" not in existing:
        p = create_project("Product Launch", "u-ava", "v2 product launch")
        def _seed_prod(d):
            d["members"].append({"userId": "u-dan", "role": "editor"})
            d["conventions"].append("Status docs in French")
            d["tasks"].append({
                "id": "t-1", "title": "Finalize launch pricing", "status": "To do",
                "priority": "High", "group": "General", "dueDate": "",
                "subtasks": [], "notes": "", "createdAt": _now_iso(),
            })
        update_project(p["id"], _seed_prod)
        created += 1
    if "Q3 Budget" not in existing:
        create_project("Q3 Budget", "u-ava", "Quarterly budget planning")
        created += 1
    return created


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


def resolve_destination(data: dict, destination: str) -> dict:
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
    if not q:
        return {"status": "not_found", "candidates": _all_destinations(data)[:8]}

    # 1) Exact static route path or title.
    for route in data["routes"]:
        if q == route["path"].lower() or q == route["title"].lower():
            return {"status": "resolved", "path": route["path"], "title": route["title"]}

    # 2) Tasks / events by exact title.
    t_exact = [t for t in data["tasks"] if t["title"].lower() == q]
    e_exact = [e for e in data["events"] if e["title"].lower() == q]
    if len(t_exact) + len(e_exact) == 1:
        if t_exact:
            t = t_exact[0]
            return {"status": "resolved", "path": task_route(t["id"]), "title": t["title"]}
        e = e_exact[0]
        return {"status": "resolved", "path": event_route(e["id"]), "title": e["title"]}

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

    seen: set[str] = set()
    deduped = [m for m in matches if not (m["path"] in seen or seen.add(m["path"]))]

    if len(deduped) == 1:
        return {"status": "resolved", "path": deduped[0]["path"], "title": deduped[0]["title"]}
    if len(deduped) > 1:
        return {"status": "ambiguous", "candidates": deduped}
    return {"status": "not_found", "candidates": _all_destinations(data)[:8]}


def _all_destinations(data: dict) -> list[dict]:
    dests = [{"path": r["path"], "title": r["title"]} for r in data["routes"]]
    dests += [{"path": task_route(t["id"]), "title": t["title"]} for t in data["tasks"]]
    dests += [{"path": event_route(e["id"]), "title": e["title"]} for e in data["events"]]
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
