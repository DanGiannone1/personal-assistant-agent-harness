"""Personal Assistant application data store — multi-user.

App state lives in **Azure Cosmos DB** as a set of documents in one container:

- ``users``            — the account registry: seeded users with password hashes + persona.
- ``space-{userId}``   — one **personal space** per user: the flat workspace
  (currentRoute/tasks/events/routes/schedules/library) that used to be the single
  owner doc. Keyed by the stable user id, so it persists across sessions/tabs/restarts.
- ``eng-*``           — shared **engagement** documents (M2+): records + members + conventions.

Every mutation goes through the optimistic-ETag ``_update_doc`` path, one document at a
time — concurrent writers (agent tools, manual UI, the reminder scheduler) can never
clobber each other. AAD-only (no key): DefaultAzureCredential.

Auth here is **demo-grade by design**: seeded username/password accounts (PBKDF2), no
self-registration, no lockout/reset/MFA. The seam to a real identity provider is the
login handler in the orchestrator — nothing in this module would change.
"""

from __future__ import annotations

import hashlib
import hmac
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
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos import exceptions as cosmos_exceptions
from azure.identity import DefaultAzureCredential

_LOCK = threading.Lock()

_STATE_KEYS = ("currentRoute", "tasks", "events", "routes", "schedules", "library")
_USERS_DOC_ID = "users"
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
        key = os.getenv("COSMOS_KEY")
        if key:
            # Local dev against the Cosmos **emulator** (the real account is
            # private-endpoint-only; laptops use the emulator by design). Key auth is
            # emulator-only; production stays AAD via DefaultAzureCredential. The
            # emulator starts empty, so create the db/container here.
            client = CosmosClient(endpoint, credential=key)
            db = client.create_database_if_not_exists(database)
            _container_singleton = db.create_container_if_not_exists(
                id=container, partition_key=PartitionKey(path="/sessionId")
            )
        else:
            client = CosmosClient(endpoint, credential=DefaultAzureCredential())
            _container_singleton = client.get_database_client(database).get_container_client(container)
        return _container_singleton


# Task lifecycle. A "Done" task is considered complete / not overdue.
TASK_STATUSES = ["To do", "In progress", "Blocked", "Done"]
TASK_PRIORITIES = ["Low", "Medium", "High"]
DONE_STATUSES = {"done", "complete", "completed", "closed"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Accounts ─────────────────────────────────────────────────────────────────
# Seeded demo users. Same demo password for all three (documented, demo-grade):
# it keeps the sign-in demo focused on *who you are* changing the app, not on
# credential management. PBKDF2-HMAC-SHA256 (stdlib) — no plaintext at rest.

_DEMO_PASSWORD = "demo1234"
_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt).split("$", 1)[1]
    return hmac.compare_digest(candidate, expected)


def _seed_users() -> list[dict]:
    def user(uid: str, name: str, role: str, tone: str) -> dict:
        return {
            "id": uid,
            "username": uid,
            "passwordHash": hash_password(_DEMO_PASSWORD),
            "displayName": name,
            "persona": {"role": role, "tone": tone, "outputPrefs": "", "language": "English"},
        }
    return [
        user("dan", "Dan", "Product lead", "concise and direct"),
        user("ava", "Ava", "Program manager", "friendly, detail-oriented"),
        user("sam", "Sam", "Stakeholder (read-mostly)", "brief"),
    ]


def ensure_seeded() -> None:
    """Idempotently create the users registry and every user's personal space."""
    container = _container()
    try:
        users_doc = container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        users_doc = {"id": _USERS_DOC_ID, "sessionId": _USERS_DOC_ID, "users": _seed_users()}
        try:
            container.create_item(users_doc)
        except cosmos_exceptions.CosmosResourceExistsError:
            users_doc = container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
    for u in users_doc["users"]:
        _ensure_space_seeded(u["id"])
    _seed_engagements()


def list_users() -> list[dict]:
    """All user records, password hashes stripped."""
    container = _container()
    try:
        doc = container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        ensure_seeded()
        doc = container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
    return [{k: v for k, v in u.items() if k != "passwordHash"} for u in doc["users"]]


def get_user(user_id: str) -> dict | None:
    return next((u for u in list_users() if u["id"] == user_id), None)


def verify_login(username: str, password: str) -> dict | None:
    """Check credentials → sanitized user record, or None. Fail closed on any mismatch."""
    container = _container()
    try:
        doc = container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        ensure_seeded()
        doc = container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
    uname = (username or "").strip().lower()
    for u in doc["users"]:
        if u["username"] == uname and verify_password(password or "", u["passwordHash"]):
            return {k: v for k, v in u.items() if k != "passwordHash"}
    return None


def update_user(user_id: str, mutator) -> dict | None:
    """ETag-safe mutation of one user record inside the users doc (persona edits)."""
    def _mut(doc):
        u = next((x for x in doc["users"] if x["id"] == user_id), None)
        if u is None:
            raise AbortWrite(None)
        return mutator(u)
    return _update_raw(_USERS_DOC_ID, _mut)


# ── Personal spaces ──────────────────────────────────────────────────────────

def _space_id(user_id: str) -> str:
    return f"space-{user_id}"


def _valid_user(user_id: str) -> str:
    """Every state access is keyed by a real user — fail loud on anything else."""
    uid = (user_id or "").strip().lower()
    if not uid or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", uid):
        raise ValueError(f"invalid user id: {user_id!r}")
    return uid


def _seed_library() -> list[dict]:
    """Personal spaces start with the reference docs in seed_docs/ (already indexed)."""
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


def _seed_space() -> dict:
    """A fresh personal space — empty records, seeded Library, the static route catalog."""
    return {
        "currentRoute": "/home",
        "tasks": [],
        "events": [],
        "schedules": [],
        "library": _seed_library(),
        # Catalog of navigable pages. `keywords` help the navigate tool resolve
        # free-text destinations deterministically without a separate LLM routing pass.
        "routes": [
            {"path": "/home", "title": "Home", "keywords": ["home", "today", "overview", "agenda", "start", "dashboard"]},
            {"path": "/todo", "title": "Tasks", "keywords": ["todo", "to do", "to-do", "tasks", "task", "list", "checklist"]},
            {"path": "/calendar", "title": "Calendar", "keywords": ["calendar", "schedule", "events", "event", "meetings", "agenda"]},
            {"path": "/documents", "title": "Documents", "keywords": ["documents", "docs", "notes", "files", "drafts", "library"]},
            {"path": "/reminders", "title": "Reminders", "keywords": ["reminders", "reminder", "schedules", "scheduled", "recurring", "digest", "summary email"]},
        ],
    }


def _doc_to_state(doc: dict) -> dict:
    """Strip Cosmos system fields → just the app-state shape; null-safe collections."""
    state = {k: doc.get(k) for k in _STATE_KEYS}
    for k in ("tasks", "events", "routes", "schedules", "library"):
        if state.get(k) is None:
            state[k] = []
    if state.get("currentRoute") is None:
        state["currentRoute"] = "/home"
    return state


def _ensure_space_seeded(user_id: str) -> dict:
    uid = _valid_user(user_id)
    sid = _space_id(uid)
    container = _container()
    try:
        return _doc_to_state(container.read_item(item=sid, partition_key=sid))
    except cosmos_exceptions.CosmosResourceNotFoundError:
        data = _seed_space()
        try:
            container.create_item({"id": sid, "sessionId": sid, **data})
            return data
        except cosmos_exceptions.CosmosResourceExistsError:
            return _doc_to_state(container.read_item(item=sid, partition_key=sid))


def load_state(user_id: str) -> dict:
    """Load a user's personal-space state, seeding first if absent."""
    uid = _valid_user(user_id)
    sid = _space_id(uid)
    container = _container()
    try:
        return _doc_to_state(container.read_item(item=sid, partition_key=sid))
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return _ensure_space_seeded(uid)


def save_state(user_id: str, data: dict) -> None:
    """Overwrite a user's space unconditionally (last-write-wins).

    NOT concurrency-safe — for seeding/admin/tests only. Concurrent mutations MUST go
    through `update_state()` so a write can't clobber another writer's change.
    """
    uid = _valid_user(user_id)
    sid = _space_id(uid)
    _container().upsert_item({"id": sid, "sessionId": sid, **{k: data.get(k) for k in _STATE_KEYS}})


class AbortWrite(Exception):
    """Raised by an update mutator to return a result WITHOUT writing (validation/no-op)."""

    def __init__(self, result=None):
        super().__init__("aborted")
        self.result = result


_MAX_UPDATE_RETRIES = 10


def _update_raw(doc_id: str, mutator, body_keys: tuple | None = None):
    """Read-modify-write any doc with optimistic concurrency (ETag) + retry.

    `mutator(doc)` mutates the doc in place and returns a result; may raise
    `AbortWrite(result)` to return without writing. Safe to re-run on conflict because
    the mutator has no side effects until the commit. Fails loud on persistent contention.
    """
    container = _container()
    last_exc = None
    for attempt in range(_MAX_UPDATE_RETRIES):
        try:
            doc = container.read_item(item=doc_id, partition_key=doc_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            raise RuntimeError(f"document {doc_id!r} does not exist — seed before updating")
        try:
            result = mutator(doc)
        except AbortWrite as abort:
            return abort.result
        body = {k: v for k, v in doc.items() if not k.startswith("_")}
        try:
            container.replace_item(
                item=doc_id, body=body,
                etag=doc["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            return result
        except cosmos_exceptions.CosmosAccessConditionFailedError as exc:
            last_exc = exc  # a concurrent writer committed first — back off, re-read, retry
            time.sleep(random.uniform(0.02, 0.08) * (attempt + 1))
    raise RuntimeError(
        f"doc {doc_id!r} update failed after {_MAX_UPDATE_RETRIES} retries (write contention)"
    ) from last_exc


def update_state(user_id: str, mutator):
    """ETag-safe read-modify-write of a user's personal space.

    `mutator(data)` receives the plain state dict (no Cosmos fields), mutates in place,
    returns the tool/endpoint result. May raise AbortWrite(result) to skip the write.
    """
    uid = _valid_user(user_id)
    _ensure_space_seeded(uid)

    def _mut(doc):
        data = _doc_to_state(doc)
        result = mutator(data)
        doc.update({k: data.get(k) for k in _STATE_KEYS})
        return result

    return _update_raw(_space_id(uid), _mut)



# ── Engagements ─────────────────────────────────────────────────────────────────
# Shared workspaces: one Cosmos doc per engagement (records + members + conventions +
# activity), mutated through the same ETag-safe path as personal spaces. Membership is
# authorization: every read/write checks the caller's role — in the REST layer AND the
# tool layer, so neither the UI nor the model can cross a membership boundary.

ENGAGEMENT_ROLES = ["owner", "editor", "viewer"]

# Delivery-record vocabulary. Status is never just a color: yellow/red must carry a
# non-empty statusNote (the "why") — enforced at the tool, REST, and UI layers.
# Stage and the milestone/risk/action collections are parked out of the v1 surface
# (docs/mvp-requirements.md R7) but stay in the data layer, dormant.
ENGAGEMENT_STAGES = ["Discovery", "Design", "Build", "Deploy", "Live", "Closed"]
ENGAGEMENT_STATUSES = ["green", "yellow", "red"]
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

# Domain fields added to every engagement doc (older docs get these on read).
_ENGAGEMENT_DOMAIN_DEFAULTS = {
    "customer": "", "stage": ENGAGEMENT_STAGES[0], "status": "green", "statusNote": "",
    "startDate": "", "targetDate": "", "milestones": [], "risks": [], "actions": [],
}


def _with_domain_defaults(eng: dict) -> dict:
    """Fill missing delivery-record fields so pre-domain docs read uniformly."""
    # Legacy mapping: docs written before the G/Y/R rename carried health/healthNote
    # with "amber" for the middle level.
    if eng.get("status") is None and eng.get("health") is not None:
        legacy = eng.get("health")
        eng["status"] = "yellow" if legacy == "amber" else legacy
        eng["statusNote"] = eng.get("healthNote") or ""
    for k, v in _ENGAGEMENT_DOMAIN_DEFAULTS.items():
        if eng.get(k) is None:
            eng[k] = list(v) if isinstance(v, list) else v
    return eng


def _valid_stage(stage: str) -> str:
    stage = (stage or "").strip() or ENGAGEMENT_STAGES[0]
    if stage not in ENGAGEMENT_STAGES:
        raise ValueError(f"stage must be one of {ENGAGEMENT_STAGES}")
    return stage


def _valid_status(status: str) -> str:
    status = (status or "").strip().lower() or "green"
    if status not in ENGAGEMENT_STATUSES:
        raise ValueError(f"status must be one of {ENGAGEMENT_STATUSES}")
    return status


def _engagement_doc_id(engagement_id: str) -> str:
    pid = (engagement_id or "").strip()
    return pid if pid.startswith("eng-") else f"eng-{pid}"


def new_engagement(creator_id: str, name: str, description: str = "",
                   customer: str = "", status: str = "",
                   status_note: str = "", start_date: str = "",
                   target_date: str = "") -> dict:
    """Create an engagement; the creator is its first owner. Returns the engagement doc.

    Raises ValueError on a bad status. Callers enforce the status-note rule
    (yellow/red need a why) before getting here.
    """
    uid = _valid_user(creator_id)
    name = (name or "").strip()
    if not name:
        raise ValueError("engagement name is required")
    container = _container()
    pid = f"eng-{secrets.token_hex(4)}"
    doc = {
        "id": pid, "sessionId": pid,
        "name": name, "description": (description or "").strip(),
        "customer": (customer or "").strip(),
        "stage": ENGAGEMENT_STAGES[0], "status": _valid_status(status),
        "statusNote": (status_note or "").strip(),
        "startDate": (start_date or "").strip(), "targetDate": (target_date or "").strip(),
        "milestones": [], "risks": [], "actions": [],
        "members": [{"userId": uid, "role": "owner"}],
        "conventions": [],
        "tasks": [], "events": [], "library": [],
        "activity": [],
        "createdAt": _now_iso(), "createdBy": uid,
    }
    container.create_item(doc)
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def load_engagement(engagement_id: str) -> dict | None:
    container = _container()
    pid = _engagement_doc_id(engagement_id)
    try:
        doc = container.read_item(item=pid, partition_key=pid)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        return None
    return _with_domain_defaults({k: v for k, v in doc.items() if not k.startswith("_")})


def update_engagement(engagement_id: str, mutator):
    """ETag-safe read-modify-write of one engagement doc (same contract as update_state)."""
    def _mut(doc):
        return mutator(_with_domain_defaults(doc))

    return _update_raw(_engagement_doc_id(engagement_id), _mut)


def list_engagements_for(user_id: str) -> list[dict]:
    """Every engagement where the user is a member (any role), as full docs."""
    uid = _valid_user(user_id)
    container = _container()
    rows = container.query_items(
        query="SELECT * FROM c WHERE STARTSWITH(c.id, 'eng-')",
        enable_cross_partition_query=True,
    )
    out = []
    for doc in rows:
        if member_role(doc, uid) is not None:
            out.append(_with_domain_defaults({k: v for k, v in doc.items() if not k.startswith("_")}))
    out.sort(key=lambda d: d.get("name", "").lower())
    return out


def member_role(engagement: dict, user_id: str) -> str | None:
    uid = (user_id or "").strip().lower()
    m = next((m for m in engagement.get("members", []) if m.get("userId") == uid), None)
    return m.get("role") if m else None


# Role gates: owner ⊃ editor ⊃ viewer.
_ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}


def role_at_least(engagement: dict, user_id: str, minimum: str) -> bool:
    role = member_role(engagement, user_id)
    return role is not None and _ROLE_RANK[role] >= _ROLE_RANK[minimum]


def log_activity(engagement: dict, user_id: str, action: str, detail: str) -> None:
    """Append to the engagement's activity feed (call inside an update_engagement mutator)."""
    engagement.setdefault("activity", []).insert(0, {
        "ts": _now_iso(), "userId": user_id, "action": action, "detail": detail[:240],
    })
    del engagement["activity"][100:]  # bounded feed


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


def _seed_engagements() -> None:
    """Demo fixture (idempotent): two similarly-named engagements for the ambiguity demo,
    different membership shapes, one French-deliverables convention."""
    container = _container()
    fixtures = [
        {
            "id": "eng-website-launch", "name": "Website Launch",
            "description": "Marketing site refresh and launch",
            "customer": "Contoso Retail", "stage": "Build",
            "status": "yellow",
            "statusNote": "CMS migration slipped a week; launch date at risk until content freeze lands.",
            "targetDate": "2026-07-24",
            "milestones": [
                {"id": "m-1", "title": "Design sign-off", "dueDate": "2026-07-01",
                 "status": "Done", "notes": ""},
                {"id": "m-2", "title": "Content freeze", "dueDate": "2026-07-18",
                 "status": "In progress", "notes": ""},
            ],
            "risks": [
                {"id": "r-1", "title": "CMS migration overrun", "severity": "Medium",
                 "status": "Open", "mitigation": "Parallel-run old CMS until cutover.",
                 "owner": "dan"},
            ],
            "actions": [
                {"id": "a-1", "title": "Confirm CDN contract renewal", "owner": "dan",
                 "dueDate": "2026-07-15", "status": "Open", "notes": ""},
            ],
            "members": [{"userId": "dan", "role": "owner"}, {"userId": "sam", "role": "viewer"}],
            "conventions": [],
            "tasks": [
                {"id": "t-1", "title": "Draft launch checklist", "status": "In progress",
                 "priority": "High", "group": "Launch", "dueDate": "2026-07-16",
                 "subtasks": [], "notes": "", "createdAt": _now_iso()},
                {"id": "t-2", "title": "Review homepage copy", "status": "To do",
                 "priority": "Medium", "group": "Content", "dueDate": "2026-07-14",
                 "subtasks": [], "notes": "", "createdAt": _now_iso()},
            ],
            "events": [
                {"id": "e-1", "title": "Launch go/no-go", "date": "2026-07-17",
                 "start": "10:00", "end": "10:30", "type": "Meeting", "notes": ""},
            ],
        },
        {
            "id": "eng-product-launch", "name": "Product Launch",
            "description": "V2 product rollout",
            "customer": "Fabrikam", "stage": "Design",
            "targetDate": "2026-08-28",
            "milestones": [
                {"id": "m-1", "title": "Pricing model approved", "dueDate": "2026-07-22",
                 "status": "Planned", "notes": ""},
            ],
            "members": [{"userId": "ava", "role": "owner"}, {"userId": "dan", "role": "editor"}],
            "conventions": [
                {"id": "c-1", "text": "Status documents are written in French.", "createdBy": "ava",
                 "createdAt": _now_iso()},
            ],
            "tasks": [
                {"id": "t-1", "title": "Finalize pricing tiers", "status": "To do",
                 "priority": "High", "group": "Launch", "dueDate": "2026-07-15",
                 "subtasks": [], "notes": "", "createdAt": _now_iso()},
            ],
            "events": [],
        },
        {
            "id": "eng-q3-budget", "name": "Q3 Budget",
            "description": "Quarterly budget planning",
            "members": [{"userId": "ava", "role": "owner"}],
            "conventions": [],
            "tasks": [],
            "events": [],
        },
    ]
    for f in fixtures:
        doc = {
            **{k: (list(v) if isinstance(v, list) else v)
               for k, v in _ENGAGEMENT_DOMAIN_DEFAULTS.items()},
            **f, "sessionId": f["id"], "library": [], "activity": [],
            "createdAt": _now_iso(), "createdBy": f["members"][0]["userId"],
        }
        try:
            container.create_item(doc)
        except cosmos_exceptions.CosmosResourceExistsError:
            pass


# ── Per-user context (visit log, working context, memories, approvals) ───────
# The context store that personalizes navigation and (M5) the turn bundle. Small,
# per-user, same ETag machinery. Visits are a capped ring buffer, newest first.

_VISIT_CAP = 50


def _ctx_id(user_id: str) -> str:
    return f"ctx-{_valid_user(user_id)}"


_CTX_DEFAULTS = {"visits": [], "workingContext": {}, "memories": [], "standingApprovals": []}


def _ensure_ctx(user_id: str) -> dict:
    cid = _ctx_id(user_id)
    container = _container()
    try:
        doc = container.read_item(item=cid, partition_key=cid)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        doc = {"id": cid, "sessionId": cid, **_CTX_DEFAULTS}
        try:
            container.create_item(doc)
        except cosmos_exceptions.CosmosResourceExistsError:
            doc = container.read_item(item=cid, partition_key=cid)
    return {k: doc.get(k, list(v) if isinstance(v, list) else dict(v)) for k, v in _CTX_DEFAULTS.items()}


def load_context(user_id: str) -> dict:
    return _ensure_ctx(user_id)


def update_context(user_id: str, mutator):
    _ensure_ctx(user_id)

    def _mut(doc):
        for k, v in _CTX_DEFAULTS.items():
            doc.setdefault(k, list(v) if isinstance(v, list) else dict(v))
        return mutator(doc)

    return _update_raw(_ctx_id(user_id), _mut)


def record_visit(user_id: str, path: str, title: str) -> None:
    """Append to the user's visit log (newest first, deduping consecutive repeats)."""
    path = (path or "").strip()
    if not path:
        return

    def _mut(doc):
        visits = doc["visits"]
        if visits and visits[0].get("path") == path:
            visits[0]["ts"] = _now_iso()
            return
        visits.insert(0, {"path": path, "title": (title or "")[:120], "ts": _now_iso()})
        del visits[_VISIT_CAP:]

    update_context(user_id, _mut)


def set_working_context(user_id: str, **fields) -> None:
    def _mut(doc):
        doc["workingContext"].update({k: v for k, v in fields.items() if v is not None})

    update_context(user_id, _mut)


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
