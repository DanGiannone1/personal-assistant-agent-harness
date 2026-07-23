"""CSA Workbench application data store — multi-user.

App state lives in **Azure Cosmos DB** as a set of documents in one container:

- ``users``            — the account registry: seeded users with password hashes + persona.
- ``personal-{uid}``   — one private aggregate per authenticated actor for Tasks,
  Calendar events, and in-app Reminders.
- ``eng-*``           — shared **engagement** documents (M2+): records + members + conventions.

Every mutation goes through the optimistic-ETag ``_update_doc`` path, one document at a
time — concurrent writers (agent tools and manual UI) can never
clobber each other. AAD-only (no key): DefaultAzureCredential.

Demo accounts are seeded only by the demo-mode startup path. Entra actors are
provisioned only from already validated tenant/object identifiers.
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
from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos import exceptions as cosmos_exceptions
from azure.identity import DefaultAzureCredential

_LOCK = threading.Lock()

_USERS_DOC_ID = "users"
_container_singleton = None

_PERSONAL_STATE_KEYS = ("currentRoute", "personalTasks", "calendarEvents", "reminders")


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
        database = os.getenv("COSMOS_DATABASE", "csa-workbench")
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


# Engagement-task lifecycle vocabulary.
TASK_STATUSES = ["To do", "In progress", "Blocked", "Done"]
TASK_PRIORITIES = ["Low", "Medium", "High"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Accounts ─────────────────────────────────────────────────────────────────
# Passwords are deployment/test secrets. PBKDF2-HMAC-SHA256 is stdlib only.
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


def _seed_users(demo_password: str) -> list[dict]:
    def user(uid: str, name: str, role: str, tone: str) -> dict:
        return {
            "id": uid,
            "username": uid,
            "passwordHash": hash_password(demo_password),
            "displayName": name,
            "identity": "demo",
            "identitySubject": f"demo:{uid}",
            "persona": {"role": role, "tone": tone, "outputPrefs": "", "language": "English"},
        }
    return [
        user("dan", "Dan", "Product lead", "concise and direct"),
        user("ava", "Ava", "Program manager", "friendly, detail-oriented"),
        user("sam", "Sam", "Stakeholder (read-mostly)", "brief"),
    ]


def _ensure_user_registry() -> dict:
    container = _container()
    try:
        return container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        users_doc = {"id": _USERS_DOC_ID, "sessionId": _USERS_DOC_ID, "users": []}
        try:
            container.create_item(users_doc)
        except cosmos_exceptions.CosmosResourceExistsError:
            users_doc = container.read_item(item=_USERS_DOC_ID, partition_key=_USERS_DOC_ID)
        return users_doc


class IdentityRegistryError(ValueError):
    """A registry has actors from the wrong exclusive identity mode."""


def validate_identity_registry(mode: str, tenant_id: str | None = None) -> dict:
    """Reject accidental reuse of a registry across exclusive identity modes."""
    users_doc = _ensure_user_registry()
    users = users_doc["users"]
    if mode == "demo":
        for user in users:
            actor_id = user.get("id")
            if user.get("identity") != "demo":
                raise IdentityRegistryError("demo mode cannot use a registry containing non-demo actors")
            if not isinstance(actor_id, str) or user.get("identitySubject") != f"demo:{actor_id}":
                raise IdentityRegistryError("demo actors require their canonical demo identity subject")
        return users_doc
    if mode != "entra":
        raise ValueError("identity mode must be demo or entra")

    tenant = (tenant_id or "").strip().lower()
    if not tenant:
        raise IdentityRegistryError("entra mode requires a configured tenant")
    for user in users:
        actor_id = user.get("id")
        oid = actor_id[2:] if isinstance(actor_id, str) and actor_id.startswith("u-") else ""
        if (
            user.get("identity") != "entra"
            or not oid
            or user.get("identitySubject") != f"{tenant}:{oid}"
        ):
            raise IdentityRegistryError("entra actors require the configured tenant's canonical identity subject")
    return users_doc


def ensure_seeded(demo_password: str) -> None:
    """Create deterministic demo actors and fixtures only in demo mode."""
    if not demo_password:
        raise ValueError("demo password is required for demo seeding")
    users_doc = validate_identity_registry("demo")
    if not users_doc["users"]:
        users_doc = {"id": _USERS_DOC_ID, "sessionId": _USERS_DOC_ID, "users": _seed_users(demo_password)}
        try:
            _container().replace_item(item=_USERS_DOC_ID, body=users_doc)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            _container().create_item(users_doc)
    for user in users_doc["users"]:
        _ensure_personal_workspace_seeded(user["id"], demo=True)
    _seed_engagements()


def list_users() -> list[dict]:
    """All user records, password hashes stripped."""
    doc = _ensure_user_registry()
    return [{k: v for k, v in u.items() if k != "passwordHash"} for u in doc["users"]]


def get_user(user_id: str) -> dict | None:
    return next((u for u in list_users() if u["id"] == user_id), None)


def find_user(ref: str) -> dict | None:
    """Resolve a user by id OR username, case-insensitive (Entra users are addressable
    by their sign-in name, not just the opaque u-<oid>). Sanitized record or None."""
    needle = (ref or "").strip().lower()
    if not needle:
        return None
    for u in list_users():
        if u["id"].lower() == needle or (u.get("username") or "").lower() == needle:
            return u
    return None


def verify_login(username: str, password: str) -> dict | None:
    """Check credentials → sanitized user record, or None. Fail closed on any mismatch."""
    doc = _ensure_user_registry()
    uname = (username or "").strip().lower()
    for u in doc["users"]:
        if (
            u.get("identity") == "demo"
            and u.get("username") == uname
            and verify_password(password or "", u.get("passwordHash", ""))
        ):
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


def ensure_entra_user(tid: str, oid: str, username: str, display_name: str) -> dict:
    """Idempotently provision the app user for a validated Entra principal.

    Keyed `u-<oid>` within the configured tenant; no password hash — this account
    can only ever be reached through a validated Entra token.
    Starts with no engagement memberships (they create or get invited like anyone).
    """
    tid = (tid or "").strip().lower()
    oid = (oid or "").strip().lower()
    if not tid or not oid:
        raise ValueError("validated Entra tid and oid are required")
    uid = _valid_user(f"u-{oid}")
    existing = get_user(uid)
    if existing is not None:
        if existing.get("identity") != "entra" or existing.get("identitySubject") != f"{tid}:{oid}":
            raise ValueError("existing actor does not match validated Entra subject")
        return existing

    record = {
        "id": uid,
        "username": (username or uid).strip().lower(),
        "displayName": (display_name or username or uid).strip(),
        "identity": "entra",
        "identitySubject": f"{tid}:{oid}",
        "persona": {"role": "", "tone": "", "outputPrefs": "", "language": "English"},
    }

    def _mut(doc):
        if any(u["id"] == uid for u in doc["users"]):
            raise AbortWrite(None)  # lost a provisioning race — the winner's record stands
        doc["users"].append(record)
        return record

    _ensure_user_registry()
    _update_raw(_USERS_DOC_ID, _mut)
    _ensure_personal_workspace_seeded(uid, demo=False)
    return get_user(uid)


def _valid_user(user_id: str) -> str:
    """Every state access is keyed by a real user — fail loud on anything else."""
    uid = (user_id or "").strip().lower()
    if not uid or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", uid):
        raise ValueError(f"invalid user id: {user_id!r}")
    return uid


class AbortWrite(Exception):
    """Raised by an update mutator to return a result WITHOUT writing (validation/no-op)."""

    def __init__(self, result=None):
        super().__init__("aborted")
        self.result = result


_MAX_UPDATE_RETRIES = 10


def _update_raw(doc_id: str, mutator):
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


# ── Personal workspaces ──────────────────────────────────────────────────────
# Private data is deliberately a separate document from shared Engagements.
# Its ID and partition key are deterministically derived only from the authenticated
# actor ID supplied by the app tier; records themselves carry no caller-controlled owner.
def _personal_workspace_id(user_id: str) -> str:
    return f"personal-{_valid_user(user_id)}"


def _new_personal_workspace(user_id: str, *, demo: bool) -> dict:
    uid = _valid_user(user_id)
    doc = {
        "id": _personal_workspace_id(uid),
        "sessionId": _personal_workspace_id(uid),
        "currentRoute": "/home",
        "personalTasks": [],
        "calendarEvents": [],
        "reminders": [],
    }
    if demo:
        # Deterministic, harmless fixtures make each demo account's private
        # workspace demonstrable without implying any external delivery.
        doc["personalTasks"] = [{
            "id": "t-1", "title": "Review personal workspace", "status": "To do",
            "priority": "Medium", "group": "Personal", "dueDate": "2030-01-15",
            "notes": "Seeded private demo task.", "subtasks": [],
            "createdAt": "2030-01-01T00:00:00+00:00",
        }]
        doc["calendarEvents"] = [{
            "id": "e-1", "title": "Personal planning", "date": "2030-01-15",
            "start": "09:00", "end": "09:30", "type": "Focus",
            "notes": "Seeded private demo event.",
        }]
        doc["reminders"] = [{
            "id": "s-1", "title": "Weekly planning reminder", "message": "Plan the week.",
            "frequency": "weekly", "dueDate": "2030-01-07", "time": "09:00",
            "timezone": "UTC", "daysOfWeek": [0], "enabled": True,
            "nextDueAt": "2030-01-07T09:00:00+00:00", "createdAt": "2030-01-01T00:00:00+00:00",
        }]
    return doc


def _ensure_personal_workspace_seeded(user_id: str, *, demo: bool) -> None:
    doc = _new_personal_workspace(user_id, demo=demo)
    try:
        _container().create_item(doc)
    except cosmos_exceptions.CosmosResourceExistsError:
        pass


def _personal_state(doc: dict) -> dict:
    """Return only the public personal-state fields, with null-safe collections."""
    state = {key: doc.get(key) for key in _PERSONAL_STATE_KEYS}
    # Workspaces created before Home became the default persisted /engagements.
    # Normalize that one legacy seed value at the read boundary so an upgrade
    # lands existing users on Home without deleting or rewriting their records.
    if not state["currentRoute"] or state["currentRoute"] == "/engagements":
        state["currentRoute"] = "/home"
    for key in ("personalTasks", "calendarEvents", "reminders"):
        if state[key] is None:
            state[key] = []
    return state


def load_personal_workspace(user_id: str) -> dict | None:
    uid = _valid_user(user_id)
    if get_user(uid) is None:
        return None
    doc_id = _personal_workspace_id(uid)
    try:
        doc = _container().read_item(item=doc_id, partition_key=doc_id)
    except cosmos_exceptions.CosmosResourceNotFoundError:
        # An existing actor from before this aggregate was introduced gets an
        # empty private workspace; demo fixture seeding remains startup-only.
        _ensure_personal_workspace_seeded(uid, demo=False)
        try:
            doc = _container().read_item(item=doc_id, partition_key=doc_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None
    return _personal_state({key: value for key, value in doc.items() if not key.startswith("_")})


def update_personal_workspace(user_id: str, mutator):
    """ETag-safe update of exactly one authenticated actor's private aggregate."""
    uid = _valid_user(user_id)
    if get_user(uid) is None:
        raise LookupError("unknown user")
    doc_id = _personal_workspace_id(uid)
    _ensure_personal_workspace_seeded(uid, demo=False)

    def _mut(doc):
        state = _personal_state(doc)
        result = mutator(state)
        doc.update(state)
        return result

    return _update_raw(doc_id, _mut)


# ── Engagements ─────────────────────────────────────────────────────────────────
# Shared workspaces: one Cosmos doc per engagement (records + members + conventions +
# activity). Membership is authorization: every read/write checks the caller's role — in the REST layer AND the
# tool layer, so neither the UI nor the model can cross a membership boundary.

ENGAGEMENT_ROLES = ["owner", "editor", "viewer"]

# Delivery-record vocabulary. Status is never just a color: yellow/red must carry a
# non-empty statusNote (the "why") — enforced at the tool, REST, and UI layers.
# Stage and the milestone/risk/action collections are parked out of the MVP
# surface but remain in the data layer for existing Engagement records.
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
    pid = f"eng-{secrets.token_hex(8)}"
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
        "tasks": [], "library": [],
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
    """ETag-safe read-modify-write of one engagement document."""
    def _mut(doc):
        return mutator(_with_domain_defaults(doc))

    return _update_raw(_engagement_doc_id(engagement_id), _mut)


def list_engagements_for(user_id: str) -> list[dict]:
    """Every engagement where the user is a member (any role), as full docs.

    The membership test runs in the query (Cosmos indexes /members/[]/userId by
    default) so the app tier receives only this user's engagements instead of
    scanning every engagement doc — this path runs on every app-state load.
    """
    uid = _valid_user(user_id)
    container = _container()
    rows = container.query_items(
        query=(
            "SELECT * FROM c WHERE STARTSWITH(c.id, 'eng-') "
            "AND EXISTS(SELECT VALUE m FROM m IN c.members WHERE m.userId = @uid)"
        ),
        parameters=[{"name": "@uid", "value": uid}],
        enable_cross_partition_query=True,
    )
    out = [_with_domain_defaults({k: v for k, v in doc.items() if not k.startswith("_")}) for doc in rows]
    out.sort(key=lambda d: d.get("name", "").lower())
    return out


def supported_app_state_for(user_id: str) -> dict:
    """Return the signed-in user's private data and visible shared Engagements."""
    uid = _valid_user(user_id)
    user = get_user(uid)
    if user is None:
        raise LookupError("unknown user")
    personal = load_personal_workspace(uid)
    if personal is None:
        raise LookupError("personal workspace missing")
    return {
        "currentRoute": personal["currentRoute"],
        "personalTasks": personal["personalTasks"],
        "calendarEvents": personal["calendarEvents"],
        "reminders": personal["reminders"],
        "engagements": list_engagements_for(uid),
        "user": {
            "id": user["id"],
            "username": user["username"],
            "displayName": user["displayName"],
            "persona": user.get("persona", {}),
        },
    }


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
        },
        {
            "id": "eng-q3-budget", "name": "Q3 Budget",
            "description": "Quarterly budget planning",
            "members": [{"userId": "ava", "role": "owner"}],
            "conventions": [],
            "tasks": [],
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


def find_engagement_task(engagement: dict, task_id: str) -> dict | None:
    return next((task for task in engagement.get("tasks", []) if task["id"] == task_id), None)


def new_id(prefix: str, existing: list[dict]) -> str:
    ids = {item["id"] for item in existing}
    n = len(existing) + 1
    while f"{prefix}-{n}" in ids:
        n += 1
    return f"{prefix}-{n}"
