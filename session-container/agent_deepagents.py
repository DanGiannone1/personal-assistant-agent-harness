"""Standalone LangGraph **Deep Agents** backend for the CSA Workbench session container.

This is a drop-in alternative to `agent.AgentSession` (which wraps the GitHub
Copilot SDK). It exposes the *identical* interface that `server.py` depends on —
constructor `(working_dir, token=, session_id=)`, `__aenter__`/`__aexit__`,
the `.token` and `.raw_sdk_log_path` properties, and an async `send(prompt)`
generator that yields already-formatted **AG-UI SSE strings** — but runs the turn
on a LangChain/LangGraph "deep agent" (`deepagents.create_deep_agent`) against
Azure OpenAI instead of the Copilot SDK.

Design notes (see review/ findings doc for the full comparison):
- **Standalone by choice.** This module shares only `appdb`/`navsvc`/`library`
  (the system of record and its services) and the `ag_ui` event protocol with the
  Copilot path. The CSA Workbench tools and system prompt are ported here as
  native LangChain tools so the two backends never couple. The cost is duplicated
  tool logic; the benefit is a clean, independent implementation that could run
  with the Copilot SDK uninstalled.
- **Full tool parity.** The model sees the same 24 tools as the Copilot backend —
  engagements (status-with-a-why, sharing), engagement-scoped tasks,
  documents/library, and schedules — with the same names, args, marker strings,
  role gating, and ETag-safe writes.
- **"Don't over-plan" parity.** The deep-agent harness ships planning (`write_todos`),
  a scratch filesystem (`ls`/`read_file`/`write_file`/…), subagents (`task`) and
  shell (`execute`). CSA Workbench is deliberately a one-direct-tool-call app, so every
  built-in tool is hidden from the model via `_ToolExclusionMiddleware`.
- **Tool-name fidelity.** The frontend keys off exact tool *and* arg names
  (`write_file`/`p.path`, `navigate`/`p.destination`, …). A user tool named
  `write_file` shadows the built-in of the same name (verified: user `tools=` win
  the name dedupe), so naming is preserved.
"""

import json as _json
import logging as _logging
import os
import re as _re
import sys
import threading
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from ag_ui.core.events import (
    BaseEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from deepagents import create_deep_agent
from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

import appdb
import library
import navsvc
from workbench_core import EngagementService, ProductToolResult, engagement_product_result
from workbench_core.appdb_repository import AppdbEngagementRepository
from mvp_tool_schemas import (
    CreateEngagementCommand, GetEngagementCommand, ListEngagementsCommand, NavigateCommand,
    SetEngagementStatusCommand, ShareEngagementCommand, UpdateEngagementCommand,
)

load_dotenv()

_logger = _logging.getLogger("agent.deepagents")
_trace_logger = _logging.getLogger("trace")


def _trace(event: str, **data) -> None:
    if not _trace_logger.handlers:
        return
    from datetime import datetime, timezone
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "component": "session",
        "event": event,
        "data": data,
    }
    _trace_logger.info(_json.dumps(record, default=str))


# Built-in deep-agent tools hidden from the model so the agent behaves like the
# Copilot one: direct single-tool actions, no planning / scratch-FS / subagents.
# (FilesystemMiddleware itself is protected and cannot be removed, but stripping
# every supplied model-visible tool by name leaves the approved product inventory.)
_EXCLUDED_BUILTINS = frozenset(
    {"write_todos", "task", "execute", "ls", "read_file", "write_file", "edit_file", "glob", "grep"}
)


# ───────────────────────── System prompt (mirrors agent.py) ─────────────────

SYSTEM_PROMPT = """\
You are the CSA Workbench assistant for shared Engagements. Use only these tools:
`navigate`, `list_engagements`, `create_engagement`, `get_engagement`,
`update_engagement`, `set_engagement_status`, and `share_engagement`.

Navigation accepts only these destination IDs: `engagements`, `engagement_overview`,
`engagement_tasks`, `engagement_artifacts`, and `workbench`. For an Engagement destination,
first obtain its stable ID with `list_engagements`; never pass user wording as a destination.

Engagement membership and roles are enforced by tools. Use stable Engagement IDs for get,
update, status, and share. Yellow and red status require a reason. State a change or navigation
only after its typed result is committed or resolved. Be concise, professional, and do not invent
facts that tools did not return.

For questions about dates, deadlines, overdue work, or any detail of an Engagement, read the
full record with `get_engagement` before answering; the `list_engagements` summary is an index
and does not contain tasks, actions, milestones, or their due dates. When asked to read or show
something, present what you found — not a confirmation that you found it. Navigate at most once
per turn, and only when the user asked to go somewhere.
"""

def _user_prompt_line(user_id: str) -> str:
    """One grounding line so the assistant knows WHO it is operating for. Fail-soft to
    the bare id: a Cosmos hiccup here must not block session start."""
    try:
        user = appdb.get_user(user_id)
    except Exception:
        user = None
    name = (user or {}).get("displayName") or user_id
    return f"\n\nYou are assisting {name} (user id: {user_id}). All state you read and mutate is theirs."


# ───────────────────────── SDK-independent helpers (ported) ─────────────────

def _sse_event(event: BaseEvent) -> str:
    """Format an AG-UI event as an SSE data line."""
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _jsonable(model_dump())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {str(k): _jsonable(v) for k, v in vars(value).items() if not str(k).startswith("_")}
        except Exception:
            pass
    return repr(value)


def _args_to_str(args) -> str | None:
    if args is None:
        return None
    if isinstance(args, str):
        return args
    try:
        return _json.dumps(_jsonable(args))
    except Exception:
        return str(args)


def _artifact_result(result) -> ProductToolResult | None:
    """Read LangChain's native artifact only; model-visible content is never parsed."""
    artifact = getattr(result, "artifact", None)
    if artifact is None and isinstance(result, tuple) and len(result) == 2:
        artifact = result[1]
    if not isinstance(artifact, dict) or not isinstance(artifact.get("product_result"), dict):
        return None
    try:
        return ProductToolResult.from_dict(artifact["product_result"])
    except (TypeError, ValueError):
        return None


def _path_within_workspace(workspace: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(workspace)
        return True
    except ValueError:
        return False


def _normalize_workspace_text(text: str) -> str:
    text = _re.sub(r"<!--\s*Page(?:Header|Footer|Break|Number)[^>]*-->", "", text, flags=_re.IGNORECASE)
    text = _re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


# ───────────────────────── CSA Workbench tools as LangChain tools ─────────────────────────

def _build_langchain_tools(working_dir: str, user_id: str) -> list:
    engagement_service = EngagementService(AppdbEngagementRepository(appdb), appdb.find_user)
    """Port of agent._build_flow_tools as native LangChain tools (same names, args,
    marker-string returns, role gating, and ETag-safe writes). Closures over the
    session workspace + user."""
    workspace_root = Path(working_dir).resolve()

    def _load() -> dict:
        return appdb.load_state(user_id)

    def _update(mutator):
        """Concurrency-safe owner-doc mutation (ETag + retry, see appdb.update_state).
        `mutator(data)` mutates and returns the tool's result string; raise
        appdb.AbortWrite(msg) to return a message without writing (validation/no-op)."""
        return appdb.update_state(user_id, mutator)

    def _resolve_task_strict(data: dict, ref: str):
        r = (ref or "").strip().lower()
        exact = [t for t in data["tasks"] if t["id"].lower() == r or t["title"].lower() == r]
        matches = exact if exact else [t for t in data["tasks"] if r in t["title"].lower()]
        if not matches:
            return None, f"TASK_NOT_FOUND: '{ref}'."
        if len(matches) > 1:
            opts = "; ".join(f"[{t['id']}] {t['title']}" for t in matches)
            return None, f"AMBIGUOUS task '{ref}': {opts}. Ask which one."
        return matches[0], None

    def _resolve_event_strict(data: dict, ref: str):
        r = (ref or "").strip().lower()
        exact = [e for e in data["events"] if e["id"].lower() == r or e["title"].lower() == r]
        matches = exact if exact else [e for e in data["events"] if r in e["title"].lower()]
        if not matches:
            return None, f"EVENT_NOT_FOUND: '{ref}'."
        if len(matches) > 1:
            opts = "; ".join(f"[{e['id']}] {e['title']}" for e in matches)
            return None, f"AMBIGUOUS event '{ref}': {opts}. Ask which one."
        return matches[0], None

    def _engagements() -> list[dict]:
        return engagement_service.list(user_id).record["engagements"]

    def _visits() -> list[dict]:
        return appdb.load_context(user_id)["visits"]

    def _resolve_engagement_ref(ref: str):
        outcome = engagement_service.resolve(user_id, ref)
        if outcome.status in ("resolved", "succeeded"):
            return outcome.record, None
        if outcome.status == "ambiguous":
            return None, f"AMBIGUOUS engagement '{ref}'. Ask which one."
        if outcome.status == "invalid":
            return None, "NAME_REQUIRED: which engagement?"
        return None, f"ENGAGEMENT_NOT_FOUND: no engagement of yours matches '{ref}'. Use list_engagements."

    def _tool_result(result: ProductToolResult, text: str) -> tuple[str, dict]:
        return text, {"product_result": result.to_dict()}

    def _confirm_card(action: str, title: str, detail: str) -> str:
        """A PENDING_CONFIRM result: nothing was mutated; the UI renders Confirm/Cancel."""
        card = {"kind": "confirm", "action": action, "title": title, "detail": detail}
        return (
            f"PENDING_CONFIRM: {action} '{title}' requires the user's confirmation. "
            f"Nothing has been changed yet. Ask the user to confirm (the app shows a card), "
            f"then re-call the tool with confirmed=true.\nCARD_JSON: " + _json.dumps(card)
        )

    def _record_card(kind: str, record: dict, scope: str) -> str:
        card = {"kind": "record", "recordKind": kind, "scope": scope,
                "fields": {k: record.get(k) for k in ("id", "title", "status", "priority", "group", "dueDate", "date", "start", "end", "type") if record.get(k)}}
        return "\nCARD_JSON: " + _json.dumps(card)

    def _mutate_engagement_scoped(eng: dict, minimum: str, mutator):
        """ETag-safe engagement mutation with the role re-checked inside the mutator."""
        def _outer(doc):
            role = appdb.member_role(doc, user_id)
            if role is None:
                raise appdb.AbortWrite(f"ENGAGEMENT_NOT_FOUND: '{eng['name']}'")
            if not appdb.role_at_least(doc, user_id, minimum):
                raise appdb.AbortWrite(
                    f"FORBIDDEN: you have {role} access on '{doc['name']}' — {minimum} required.")
            return mutator(doc)
        return appdb.update_engagement(eng["id"], _outer)

    @tool("navigate", description="Navigate to an explicit CSA Workbench catalog destination.", args_schema=NavigateCommand, response_format="content_and_artifact")
    def navigate(destination_id: str, engagement_id: str | None = None) -> tuple[str, dict]:
        result = navsvc.destination_for(user_id, destination_id, engagement_id)
        return _tool_result(result, result.message or "Navigation request processed.")

    @tool("list_engagements", description="List the shared engagements the user belongs to, including stable IDs.", args_schema=ListEngagementsCommand, response_format="content_and_artifact")
    def list_engagements() -> tuple[str, dict]:
        engs = _engagements()
        if not engs:
            return _tool_result(ProductToolResult("succeeded", "engagement.listed", "list"), "No engagements yet.")
        lines = [f"{len(engs)} engagement(s):"]
        for p in engs:
            role = appdb.member_role(p, user_id)
            open_tasks = sum(1 for t in p.get("tasks") or [] if t.get("status") != "Done")
            why = f" ({p['statusNote']})" if p.get("statusNote") else ""
            lines.append(
                f"- [{p['id']}] {p['name']} | your role: {role} | customer={p.get('customer') or 'n/a'} | "
                f"status={p.get('status')}{why} | open tasks={open_tasks} | "
                f"target={p.get('targetDate') or 'n/a'} | docs: {len(p.get('library') or [])}"
            )
        return _tool_result(ProductToolResult("succeeded", "engagement.listed", "list"), "\n".join(lines))

    @tool("create_engagement", description="Create a new shared engagement.", args_schema=CreateEngagementCommand, response_format="content_and_artifact")
    def create_engagement(name: str, description: str = "", customer: str = "", target_date: str = "") -> tuple[str, dict]:
        outcome = engagement_service.create(user_id, {"name": name, "description": description,
                                                       "customer": customer, "targetDate": target_date})
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement creation processed." if outcome.record else result.message)

    @tool("get_engagement", description="Read one visible engagement by stable ID.", args_schema=GetEngagementCommand, response_format="content_and_artifact")
    def get_engagement(engagement_id: str) -> tuple[str, dict]:
        outcome = engagement_service.get(user_id, engagement_id)
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement read processed." if outcome.record else result.message)

    @tool("update_engagement", description="Update an engagement by stable ID.", args_schema=UpdateEngagementCommand, response_format="content_and_artifact")
    def update_engagement(engagement_id: str, name: str | None = None, description: str | None = None, customer: str | None = None,
                          start_date: str | None = None, target_date: str | None = None) -> tuple[str, dict]:
        values = {key: value for key, value in (("name", name), ("description", description),
                  ("customer", customer), ("startDate", start_date), ("targetDate", target_date)) if value is not None}
        outcome = engagement_service.update(user_id, engagement_id, values)
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement update processed." if outcome.status == "committed" else result.message)

    @tool("set_engagement_status", description="Set an engagement status by stable ID.", args_schema=SetEngagementStatusCommand, response_format="content_and_artifact")
    def set_engagement_status(engagement_id: str, status: str, note: str = "") -> tuple[str, dict]:
        outcome = engagement_service.update(user_id, engagement_id, {"status": status, "statusNote": note})
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement status processed." if outcome.status == "committed" else result.message)

    @tool("share_engagement", description="Share an engagement by stable ID.", args_schema=ShareEngagementCommand, response_format="content_and_artifact")
    def share_engagement(engagement_id: str, user: str, role: str = "viewer") -> tuple[str, dict]:
        outcome = engagement_service.share(user_id, engagement_id, user, role)
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement sharing processed." if outcome.status == "committed" else result.message)

    @tool("list_tasks", description="List the tasks with their status, priority, group, due date, a computed overdue flag, and subtask progress.")
    def list_tasks(engagement: str = "") -> str:
        scope_label = "personal"
        if engagement.strip():
            eng, err = _resolve_engagement_ref(engagement)
            if err:
                return err
            tasks = eng["tasks"]
            scope_label = eng["name"]
        else:
            data = _load()
            tasks = data["tasks"]
        if not tasks:
            return f"No tasks yet in {scope_label}."
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        n_over = sum(1 for t in tasks if appdb.is_overdue(t, today))
        lines = [f"{len(tasks)} task(s) in {scope_label} | today={today} | overdue={n_over}:"]
        for t in tasks:
            subs = t.get("subtasks") or []
            done = sum(1 for s in subs if s.get("done"))
            lines.append(
                f"- [{t['id']}] {t['title']} | status={t['status']} | priority={t.get('priority') or 'Medium'} | "
                f"group={t.get('group') or 'General'} | due={t.get('dueDate') or 'n/a'} | "
                f"overdue={'yes' if appdb.is_overdue(t, today) else 'no'} | subtasks={done}/{len(subs)}"
            )
        return "\n".join(lines)

    @tool("create_task", description="Create a task in the to-do list.")
    def create_task(title: str, status: str = "", priority: str = "", group: str = "",
                    due_date: str = "", engagement: str = "") -> str:
        if not title.strip():
            return "TITLE_REQUIRED: a task needs a title."
        if engagement.strip():
            eng, err = _resolve_engagement_ref(engagement)
            if err:
                return err
            def _pmut(doc):
                task = {
                    "id": appdb.new_id("t", doc["tasks"]),
                    "title": title.strip(),
                    "status": status.strip() or "To do",
                    "priority": priority.strip() or "Medium",
                    "group": group.strip() or "General",
                    "dueDate": due_date.strip(),
                    "subtasks": [], "notes": "", "createdAt": appdb._now_iso(),
                }
                doc["tasks"].append(task)
                appdb.log_activity(doc, user_id, "task.created", task["title"])
                return task
            out = _mutate_engagement_scoped(eng, "editor", _pmut)
            if isinstance(out, str):
                return out
            return (
                f"CREATED task [{out['id']}] '{out['title']}' in engagement {eng['name']}, "
                f"status {out['status']}, priority {out['priority']}, due {out['dueDate'] or 'n/a'}."
                + _record_card("task", out, eng["name"])
            )
        def _mut(data):
            task = {
                "id": appdb.new_id("t", data["tasks"]),
                "title": title.strip(),
                "status": status.strip() or "To do",
                "priority": priority.strip() or "Medium",
                "group": group.strip() or "General",
                "dueDate": due_date.strip(),
                "subtasks": [],
                "notes": "",
                "createdAt": appdb._now_iso(),
            }
            data["tasks"].append(task)
            data["currentRoute"] = appdb.task_route(task["id"])
            return (
                f"CREATED task [{task['id']}] '{task['title']}', status {task['status']}, "
                f"priority {task['priority']}, group {task['group']}, due {task['dueDate'] or 'n/a'}."
                + _record_card("task", task, "personal")
            )
        return _update(_mut)

    @tool("update_task", description="Update a task's status, priority, group, or due date.")
    def update_task(task: str, status: str = "", priority: str = "", group: str = "",
                    due_date: str = "", engagement: str = "") -> str:
        if engagement.strip():
            eng, perr = _resolve_engagement_ref(engagement)
            if perr:
                return perr
            def _pmut(doc):
                t, err = _resolve_task_strict(doc, task)
                if err:
                    raise appdb.AbortWrite(err)
                changed = []
                for field, val in (("status", status), ("priority", priority), ("group", group)):
                    if val.strip():
                        t[field] = val.strip()
                        changed.append(f"{field}={t[field]}")
                if due_date.strip():
                    t["dueDate"] = due_date.strip()
                    changed.append(f"due={t['dueDate']}")
                if not changed:
                    raise appdb.AbortWrite("NO_CHANGES: specify a status, priority, group, or due_date to update.")
                appdb.log_activity(doc, user_id, "task.updated", t["title"])
                return (t, changed)
            out = _mutate_engagement_scoped(eng, "editor", _pmut)
            if isinstance(out, str):
                return out
            t, changed = out
            return f"UPDATED task [{t['id']}] '{t['title']}' in {eng['name']}: {', '.join(changed)}."
        def _mut(data):
            t, err = _resolve_task_strict(data, task)
            if err:
                raise appdb.AbortWrite(err)
            changed = []
            if status.strip():
                t["status"] = status.strip()
                changed.append(f"status={t['status']}")
            if priority.strip():
                t["priority"] = priority.strip()
                changed.append(f"priority={t['priority']}")
            if group.strip():
                t["group"] = group.strip()
                changed.append(f"group={t['group']}")
            if due_date.strip():
                t["dueDate"] = due_date.strip()
                changed.append(f"due={t['dueDate']}")
            if not changed:
                raise appdb.AbortWrite("NO_CHANGES: specify a status, priority, group, or due_date to update.")
            data["currentRoute"] = appdb.task_route(t["id"])
            return f"UPDATED task [{t['id']}] '{t['title']}': {', '.join(changed)}."
        return _update(_mut)

    @tool("delete_task", description="Delete a task from the to-do list. Confirm-first: without confirmed=true it returns a confirmation card and changes nothing.")
    def delete_task(task: str, engagement: str = "", confirmed: bool = False) -> str:
        if not confirmed:
            scope_data = _load() if not engagement.strip() else None
            if engagement.strip():
                eng_probe, perr0 = _resolve_engagement_ref(engagement)
                if perr0:
                    return perr0
                scope_data = eng_probe
            t, terr = _resolve_task_strict(scope_data, task)
            if terr:
                return terr
            return _confirm_card("delete_task", t["title"],
                                 f"Delete task [{t['id']}] permanently" + (f" from engagement {scope_data['name']}" if engagement.strip() else ""))
        if engagement.strip():
            eng, perr = _resolve_engagement_ref(engagement)
            if perr:
                return perr
            def _pmut(doc):
                t, err = _resolve_task_strict(doc, task)
                if err:
                    raise appdb.AbortWrite(err)
                doc["tasks"] = [x for x in doc["tasks"] if x["id"] != t["id"]]
                appdb.log_activity(doc, user_id, "task.deleted", t["title"])
                return t
            out = _mutate_engagement_scoped(eng, "editor", _pmut)
            if isinstance(out, str):
                return out
            return f"DELETED task [{out['id']}] '{out['title']}' from {eng['name']}."
        def _mut(data):
            t, err = _resolve_task_strict(data, task)
            if err:
                raise appdb.AbortWrite(err)
            data["tasks"] = [x for x in data["tasks"] if x["id"] != t["id"]]
            data["currentRoute"] = "/todo"
            return f"DELETED task [{t['id']}] '{t['title']}'."
        return _update(_mut)

    @tool("add_subtask", description="Add a subtask to a task.")
    def add_subtask(task: str, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "TEXT_REQUIRED: provide the subtask text."
        def _mut(data):
            t, err = _resolve_task_strict(data, task)
            if err:
                raise appdb.AbortWrite(err)
            t.setdefault("subtasks", []).append({"text": text, "done": False})
            data["currentRoute"] = appdb.task_route(t["id"])
            return f"ADDED subtask to '{t['title']}': {text}."
        return _update(_mut)

    @tool("list_events", description="List the calendar events with their date, time, and type.")
    def list_events() -> str:
        data = _load()
        events = data["events"]
        if not events:
            return "No events yet."
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        ordered = sorted(events, key=lambda e: (e.get("date") or "", e.get("start") or ""))
        lines = [f"{len(events)} event(s) | today={today}:"]
        for e in ordered:
            when = e.get("start") or "all-day"
            if e.get("start") and e.get("end"):
                when = f"{e['start']}-{e['end']}"
            lines.append(
                f"- [{e['id']}] {e['title']} | date={e.get('date') or 'n/a'} | time={when} | type={e.get('type') or 'Meeting'}"
            )
        return "\n".join(lines)

    @tool("create_event", description="Create a calendar event (a meeting, reminder, or focus block). A date is required.")
    def create_event(title: str, date: str, start: str = "", end: str = "", type: str = "") -> str:
        if not title.strip():
            return "TITLE_REQUIRED: an event needs a title."
        if not date.strip():
            return "DATE_REQUIRED: an event needs a date (YYYY-MM-DD)."
        def _mut(data):
            event = {
                "id": appdb.new_id("e", data["events"]),
                "title": title.strip(),
                "date": date.strip(),
                "start": start.strip(),
                "end": end.strip(),
                "type": type.strip() or "Meeting",
                "notes": "",
            }
            data["events"].append(event)
            data["currentRoute"] = appdb.event_route(event["id"])
            when = event["start"] or "all-day"
            if event["start"] and event["end"]:
                when = f"{event['start']}-{event['end']}"
            return (
                f"CREATED event [{event['id']}] '{event['title']}' ({event['type']}) on {event['date']} at {when}."
            )
        return _update(_mut)

    @tool("update_event", description="Update or move a calendar event's title, date, time, or type.")
    def update_event(event: str, title: str = "", date: str = "", start: str = "", end: str = "", type: str = "") -> str:
        def _mut(data):
            e, err = _resolve_event_strict(data, event)
            if err:
                raise appdb.AbortWrite(err)
            changed = []
            if title.strip():
                e["title"] = title.strip()
                changed.append(f"title={e['title']}")
            if date.strip():
                e["date"] = date.strip()
                changed.append(f"date={e['date']}")
            if start.strip():
                e["start"] = start.strip()
                changed.append(f"start={e['start']}")
            if end.strip():
                e["end"] = end.strip()
                changed.append(f"end={e['end']}")
            if type.strip():
                e["type"] = type.strip()
                changed.append(f"type={e['type']}")
            if not changed:
                raise appdb.AbortWrite("NO_CHANGES: specify a title, date, start, end, or type to update.")
            data["currentRoute"] = appdb.event_route(e["id"])
            return f"UPDATED event [{e['id']}] '{e['title']}': {', '.join(changed)}."
        return _update(_mut)

    @tool("delete_event", description="Delete a calendar event. Confirm-first: without confirmed=true it returns a confirmation card and changes nothing.")
    def delete_event(event: str, confirmed: bool = False) -> str:
        if not confirmed:
            e, eerr = _resolve_event_strict(_load(), event)
            if eerr:
                return eerr
            return _confirm_card("delete_event", e["title"], f"Delete event [{e['id']}] permanently")
        def _mut(data):
            e, err = _resolve_event_strict(data, event)
            if err:
                raise appdb.AbortWrite(err)
            data["events"] = [x for x in data["events"] if x["id"] != e["id"]]
            data["currentRoute"] = "/calendar"
            return f"DELETED event [{e['id']}] '{e['title']}'."
        return _update(_mut)

    @tool("list_documents", description="List the documents available in the workspace (provided source documents and generated artifacts) with a one-line descriptor. Use to discover what you can read before answering document questions.")
    def list_documents() -> str:
        docs = []
        for p in sorted(workspace_root.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            descriptor = ""
            try:
                with p.open(encoding="utf-8") as fh:
                    for line in fh:
                        s = line.strip().lstrip("#").strip()
                        if s:
                            descriptor = s[:100]
                            break
            except (UnicodeDecodeError, OSError):
                descriptor = "(non-text file)"
            docs.append(f"- {p.name} — {descriptor}" if descriptor else f"- {p.name}")
        if not docs:
            return "NO_DOCUMENTS: the workspace has no documents yet."
        return "Documents in the workspace:\n" + "\n".join(docs)

    @tool("read_workspace_file", description="Read a complete UTF-8 text or markdown file (e.g. an uploaded document) from the workspace.")
    def read_workspace_file(path: str = "") -> str:
        raw_path = (path or "").strip()
        if raw_path:
            candidate = Path(raw_path)
            resolved = (candidate if candidate.is_absolute() else workspace_root / candidate).resolve()
        else:
            visible = [
                p.resolve() for p in sorted(workspace_root.iterdir())
                if p.is_file() and not p.name.startswith(".")
            ]
            if len(visible) != 1:
                return f"PATH_REQUIRED: workspace has {len(visible)} files: {[p.name for p in visible]}"
            resolved = visible[0]
            raw_path = resolved.name
        if not _path_within_workspace(workspace_root, resolved):
            return "INVALID_PATH: must stay within the workspace"
        if not resolved.exists() or not resolved.is_file():
            return f"FILE_NOT_FOUND: {raw_path}"
        raw_bytes = resolved.read_bytes()
        if b"\x00" in raw_bytes:
            return f"BINARY_FILE_UNSUPPORTED: {raw_path}"
        try:
            decoded = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return f"ENCODING_UNSUPPORTED: {raw_path} is not valid UTF-8 text."
        text = _normalize_workspace_text(decoded)
        return f"PATH: {resolved.name}\n\n{text}"

    @tool("write_file", description="Write a complete UTF-8 text or markdown artifact (e.g. a generated summary) to the workspace.")
    def write_file(path: str, content: str) -> str:
        raw_path = (path or "").strip()
        if not raw_path:
            return "PATH_REQUIRED"
        candidate = Path(raw_path)
        resolved = (candidate if candidate.is_absolute() else workspace_root / candidate).resolve()
        if not _path_within_workspace(workspace_root, resolved):
            return "INVALID_PATH: must stay within the workspace"
        if resolved.name.startswith("."):
            return "INVALID_PATH: hidden files are not valid output targets"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"WROTE {resolved.name} ({resolved.stat().st_size} bytes)."

    @tool("search_documents", description="Semantic search (RAG) over the persistent Library — the user's saved/reference knowledge base. Returns the top matching passages, each with its source filename. Use to answer 'what did I decide about X', 'find … in my library', or 'search my docs'. Note: this searches the PERSISTENT Library only; to read a file the user just uploaded this session, use read_workspace_file instead.")
    def search_documents(query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "QUERY_REQUIRED: provide what to search for."
        return library.search(query)

    @tool("save_to_library", description="Save a session file (an upload or a doc you drafted) into the PERSISTENT Library so it's searchable across all future sessions. Use when the user says 'save this to my library/knowledge base', 'keep this permanently', etc. Session files are otherwise temporary and gone when the session ends.")
    def save_to_library(filename: str) -> str:
        filename = filename.strip()
        if not filename:
            return "FILENAME_REQUIRED: which session file should I save?"
        target = (workspace_root / filename).resolve()
        if not _path_within_workspace(workspace_root, target) or not target.is_file():
            return f"NOT_FOUND: no session file named '{filename}'. Use list_documents to see what's available."
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"UNSUPPORTED: '{filename}' isn't UTF-8 text — only text/markdown documents can be saved to the Library."
        title = library.title_from_filename(filename)
        try:
            n_chunks = library.index_document(filename, title, text)
        except RuntimeError as exc:
            return f"LIBRARY_FAILED: {exc}"
        def _mut(data):
            existing = appdb.find_library_doc(data, filename)
            now = appdb._now_iso()
            if existing:
                existing["savedAt"] = now
                existing["title"] = title
            else:
                data["library"].append({
                    "id": appdb.new_id("lib", data["library"]),
                    "filename": filename, "title": title, "savedAt": now, "source": "upload",
                })
            data["currentRoute"] = "/documents"
            return (
                f"SAVED '{filename}' to the Library ({n_chunks} chunks indexed). "
                "It's now persistent and searchable across all future sessions."
            )
        try:
            return _update(_mut)
        except Exception:
            # Recording the entry failed after indexing — roll back the index write so the
            # two stores can't drift (chunk searchable but not listed/deletable).
            try:
                library.delete_document(filename)
            except Exception:
                _logger.error("save_to_library rollback failed for %s", filename, exc_info=True)
            raise

    @tool("list_library", description="List the documents in the persistent Library (the searchable knowledge base).")
    def list_library() -> str:
        docs = _load()["library"]
        if not docs:
            return "The Library is empty. Upload a document and save it to the Library."
        lines = [f"{len(docs)} document(s) in the Library:"]
        for d in docs:
            lines.append(f"- {d['filename']} ({d.get('source') or 'doc'}, saved {(d.get('savedAt') or '')[:10]})")
        return "\n".join(lines)

    @tool("create_schedule", description="Create a scheduled reminder: a saved instruction the app runs automatically on a daily or weekly cadence and emails the result to the user. Use for 'email me a daily summary', 'remind me every Monday', etc.")
    def create_schedule(title: str, prompt: str, frequency: str, time: str, timezone: str = "", days: str = "") -> str:
        title = title.strip()
        prompt = prompt.strip()
        if not title:
            return "TITLE_REQUIRED: the reminder needs a short name."
        if not prompt:
            return "PROMPT_REQUIRED: the reminder needs an instruction to run."
        frequency = frequency.strip().lower()
        if frequency not in appdb.SCHEDULE_FREQUENCIES:
            return f"BAD_FREQUENCY: use one of {appdb.SCHEDULE_FREQUENCIES}."
        try:
            timezone_name = appdb.normalize_timezone(timezone)
        except ValueError as exc:
            return f"BAD_TIMEZONE: {exc}"
        days_of_week: list[int] = []
        if frequency == "weekly":
            name_to_idx = {n.lower(): i for i, n in enumerate(appdb.DAY_NAMES)}
            bad = []
            for tok in days.split(","):
                raw = tok.strip()
                if not raw:
                    continue
                key = raw.lower()[:3]
                if key in name_to_idx:
                    days_of_week.append(name_to_idx[key])
                else:
                    bad.append(raw)
            if bad:
                return f"BAD_DAYS: unrecognized day(s) {bad}. Use day names like 'Mon,Wed,Fri'."
            days_of_week = sorted(set(days_of_week))
            if not days_of_week:
                return "DAYS_REQUIRED: a weekly reminder needs day(s), e.g. 'Mon,Fri'."
        try:
            next_run = appdb.compute_next_run(frequency, time, timezone_name, days_of_week)
        except (ValueError, RuntimeError) as exc:
            return f"BAD_TIME: {exc}"
        def _mut(data):
            schedule = {
                "id": appdb.new_id("s", data["schedules"]),
                "title": title,
                "prompt": prompt,
                "frequency": frequency,
                "time": time.strip(),
                "timezone": timezone_name,
                "daysOfWeek": days_of_week,
                "enabled": True,
                "channel": "email",
                "createdAt": appdb._now_iso(),
                "lastRunAt": None,
                "lastStatus": None,
                "nextRunAt": next_run.isoformat(),
            }
            data["schedules"].append(schedule)
            data["currentRoute"] = "/reminders"
            return (
                f"CREATED reminder [{schedule['id']}] '{title}' — {appdb.schedule_summary(schedule)}. "
                f"Next run {schedule['nextRunAt']}. It will email the result of: {prompt}"
            )
        return _update(_mut)

    @tool("list_schedules", description="List the scheduled reminders with their cadence, next run time, and status.")
    def list_schedules() -> str:
        schedules = _load()["schedules"]
        if not schedules:
            return "No reminders yet."
        lines = [f"{len(schedules)} reminder(s):"]
        for s in schedules:
            state = "enabled" if s.get("enabled") else "paused"
            last = s.get("lastRunAt") or "never"
            lines.append(
                f"- [{s['id']}] {s['title']} | {appdb.schedule_summary(s)} | {state} | "
                f"next={s.get('nextRunAt') or 'n/a'} | last={last} | runs: {s['prompt']}"
            )
        return "\n".join(lines)

    @tool("delete_schedule", description="Delete a scheduled reminder. Confirm-first: without confirmed=true it returns a confirmation card and changes nothing.")
    def delete_schedule(schedule: str, confirmed: bool = False) -> str:
        if not confirmed:
            sch = appdb.resolve_schedule(_load(), schedule)
            if sch is None:
                return f"NOT_FOUND: no reminder matches '{schedule}'."
            return _confirm_card("delete_schedule", sch["title"], f"Delete reminder [{sch['id']}] permanently")
        def _mut(data):
            s = appdb.resolve_schedule(data, schedule)
            if s is None:
                raise appdb.AbortWrite(f"NOT_FOUND: no reminder matches '{schedule}'.")
            data["schedules"] = [x for x in data["schedules"] if x["id"] != s["id"]]
            data["currentRoute"] = "/reminders"
            return f"DELETED reminder [{s['id']}] '{s['title']}'."
        return _update(_mut)

    return [
        navigate,
        list_engagements, create_engagement, get_engagement, update_engagement, set_engagement_status,
        share_engagement,
    ]


# ───────────────────────── AgentSession (deep-agent backend) ────────────────

def _chunk_text(chunk) -> str:
    """Extract plain assistant text from an AIMessageChunk (ignoring tool-call deltas)."""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


class AgentSession:
    """Async context manager running a turn on a LangGraph deep agent.

    Interface-compatible with `agent.AgentSession` (the Copilot backend): the
    session container's `server.py` consumes both identically.
    """

    def __init__(self, working_dir: str, token: str | None = None, session_id: str = "default",
                 user_id: str = "dan"):
        self._user_id = user_id
        self._working_dir = working_dir
        self._initial_token = token
        self._token = token
        self._session_id = session_id
        self._agent = None
        self._checkpointer = None
        self._tool_names: set[str] = set()
        self._credential: DefaultAzureCredential | None = None

        self._thread_id: str = str(uuid.uuid4())
        self._run_id: str = ""
        self._turn_active: bool = False
        self._status: str = "idle"
        self._navigation_version: int = 0

        self._raw_sdk_log_lock = threading.Lock()
        self._raw_sdk_log_path: str | None = None
        if os.getenv("LOG_RAW_SDK_EVENTS", "").lower() == "true":
            logs_dir = os.getenv("LOG_RAW_SDK_EVENTS_DIR") or os.getenv("LOG_TRACE_DIR")
            if logs_dir:
                raw_dir = Path(logs_dir) / "sdk-events"
                raw_dir.mkdir(parents=True, exist_ok=True)
                self._raw_sdk_log_path = str(raw_dir / f"{self._session_id}.jsonl")

    @property
    def raw_sdk_log_path(self) -> str | None:
        return self._raw_sdk_log_path

    @property
    def status(self) -> str:
        return self._status

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def token(self) -> str | None:
        return self._token

    def _write_raw_sdk_record(self, record: dict) -> None:
        if not self._raw_sdk_log_path:
            return
        from datetime import datetime, timezone
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "session_id": self._session_id, **record}
        line = _json.dumps(payload, default=str)
        with self._raw_sdk_log_lock:
            with open(self._raw_sdk_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    async def __aenter__(self) -> "AgentSession":
        if self._raw_sdk_log_path:
            Path(self._raw_sdk_log_path).write_text("", encoding="utf-8")

        token = self._token or self._initial_token or os.getenv("AZURE_OPENAI_TOKEN")
        if not token:
            self._credential = DefaultAzureCredential()
            tok = await self._credential.get_token("https://cognitiveservices.azure.com/.default")
            token = tok.token
        self._token = token

        # AZURE_ENDPOINT points at the Foundry/Cognitive-Services resource and may be
        # given as `…/openai` or `…/openai/v1/`. AzureChatOpenAI wants the bare resource
        # endpoint plus the deployment + api-version (the classic deployments path,
        # verified working against this resource); derive it defensively by stripping
        # anything from `/openai` onward. The forwarded Cognitive-Services bearer token
        # is passed as azure_ad_token (AAD auth — no key), mirroring the Copilot backend.
        base_endpoint = os.environ["AZURE_ENDPOINT"].split("/openai")[0].rstrip("/")
        deployment = os.environ["AZURE_DEPLOYMENT"]
        api_version = os.getenv("AZURE_API_VERSION", "2024-10-21")
        model = AzureChatOpenAI(
            azure_endpoint=base_endpoint,
            azure_deployment=deployment,
            api_version=api_version,
            azure_ad_token=token,
            streaming=True,
        )

        tools = _build_langchain_tools(self._working_dir, self._user_id)
        self._tool_names = {t.name for t in tools}
        self._checkpointer = InMemorySaver()
        self._agent = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=SYSTEM_PROMPT + _user_prompt_line(self._user_id),
            middleware=[_ToolExclusionMiddleware(excluded=_EXCLUDED_BUILTINS)],
            checkpointer=self._checkpointer,
        )

        _trace(
            "agent.session_initialized",
            session_id=self._session_id,
            working_dir=self._working_dir,
            model=deployment,
            backend="deepagents",
            available_tools=sorted(self._tool_names),
        )
        self._write_raw_sdk_record({"kind": "session_initialized", "backend": "deepagents", "available_tools": sorted(self._tool_names)})
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._agent = None
        if self._credential:
            await self._credential.close()

    async def send(self, prompt: str, navigation_version: int = 0) -> AsyncGenerator[str, None]:
        """Run a deep-agent turn; yield SSE-formatted AG-UI events until completion."""
        self._run_id = str(uuid.uuid4())
        self._status = "thinking"
        self._turn_active = True
        self._navigation_version = navigation_version

        _trace("agent.turn_start", session_id=self._session_id, run_id=self._run_id)
        self._write_raw_sdk_record({"kind": "turn_start", "run_id": self._run_id, "prompt": prompt})

        yield _sse_event(RunStartedEvent(thread_id=self._thread_id, run_id=self._run_id))

        message_started = False
        current_msg_id = ""
        open_tool_calls: dict[str, str] = {}  # run_id -> tool name
        tools_called = 0
        config = {"configurable": {"thread_id": self._thread_id}}
        inp = {"messages": [{"role": "user", "content": prompt}]}

        try:
            async for ev in self._agent.astream_events(inp, config=config, version="v2"):
                kind = ev.get("event")
                self._write_raw_sdk_record({"kind": "sdk_event", "run_id": self._run_id, "event_type": kind, "name": ev.get("name")})

                if kind == "on_chat_model_stream":
                    text = _chunk_text(ev["data"].get("chunk"))
                    if not text:
                        continue
                    self._status = "thinking"
                    if not message_started:
                        current_msg_id = str(uuid.uuid4())
                        message_started = True
                        yield _sse_event(TextMessageStartEvent(message_id=current_msg_id, role="assistant"))
                    yield _sse_event(TextMessageContentEvent(message_id=current_msg_id, delta=text))

                elif kind == "on_chat_model_end":
                    if message_started:
                        yield _sse_event(TextMessageEndEvent(message_id=current_msg_id))
                        message_started = False

                elif kind == "on_tool_start":
                    name = ev.get("name")
                    if name not in self._tool_names:
                        raise RuntimeError(f"Deep Agents exposed an unapproved tool: {name}")
                    call_id = ev.get("run_id") or str(uuid.uuid4())
                    open_tool_calls[call_id] = name
                    self._status = f"tool:{name}"
                    yield _sse_event(ToolCallStartEvent(
                        tool_call_id=call_id,
                        tool_call_name=name,
                        parent_message_id=current_msg_id or None,
                    ))
                    args_str = _args_to_str((ev.get("data") or {}).get("input"))
                    if args_str:
                        yield _sse_event(ToolCallArgsEvent(tool_call_id=call_id, delta=args_str))
                    _trace("agent.tool_start", session_id=self._session_id, run_id=self._run_id, tool=name, call_id=call_id, args=args_str)

                elif kind == "on_tool_end":
                    call_id = ev.get("run_id")
                    name = open_tool_calls.pop(call_id, None)
                    if name is None:
                        raise RuntimeError("Deep Agents emitted an uncorrelated tool result")
                    self._status = "thinking"
                    tools_called += 1
                    result = (ev.get("data") or {}).get("output")
                    product_result = _artifact_result(result)
                    if product_result is None:
                        product_result = ProductToolResult("failed", "tool.missing_native_result", name, "The tool did not return a structured result.")
                    payload = {"type": "TOOL_CALL_RESULT", "tool_call_id": call_id, "result": product_result.to_dict()}
                    yield f"data: {_json.dumps(payload)}\n\n"
                    if product_result.status in {"resolved", "committed"} and product_result.destination:
                        yield f"data: {_json.dumps({'type': 'NAVIGATION_RESOLVED', 'runId': self._run_id, 'destination': dict(product_result.destination), 'requestedAtNavigationVersion': self._navigation_version})}\n\n"
                    yield _sse_event(ToolCallEndEvent(tool_call_id=call_id))
                    _trace("agent.tool_end", session_id=self._session_id, run_id=self._run_id, tool=name, call_id=call_id, result=product_result.to_dict())

            if message_started:
                yield _sse_event(TextMessageEndEvent(message_id=current_msg_id))
            self._status = "idle"
            _trace("agent.turn_end", session_id=self._session_id, run_id=self._run_id, tools_called=tools_called)
            yield _sse_event(RunFinishedEvent(thread_id=self._thread_id, run_id=self._run_id))

        except Exception as exc:
            self._status = "error"
            msg = str(exc) or "Unknown error"
            low = msg.lower()
            if "too many requests" in low or "429" in msg or "rate limit" in low:
                msg = "The AI service is temporarily rate-limited. Please wait 30–60 seconds and try again."
            elif "content_filter" in low or "content management policy" in low or "responsible ai" in low or "filtered" in low:
                msg = "I can't act on that request — it was flagged by the safety filter. I won't take actions that try to override my guardrails or operate outside your workspace."
            self._write_raw_sdk_record({"kind": "turn_exception", "run_id": self._run_id, "error": repr(exc)})
            _trace("agent.error", session_id=self._session_id, run_id=self._run_id, message=msg)
            yield _sse_event(RunErrorEvent(message=msg))
        finally:
            self._turn_active = False
            self._write_raw_sdk_record({"kind": "turn_finalized", "run_id": self._run_id, "status": self._status})
