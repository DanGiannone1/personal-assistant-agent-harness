"""AgentSession wrapping the GitHub Copilot SDK (1.0.x) with an event queue.

Provides a streaming async generator interface for running agent turns against
Azure OpenAI. Translates SDK session events into AG-UI protocol events.

The agent operates on a per-session workspace folder. Application state (the mock
CSA Workbench data) lives in a JSON doc in that workspace (see appdb.py); the
tools read and mutate it, and the frontend renders it via /app/state.
"""

import asyncio
import json as _json
import logging as _logging
import os
import re as _re
import sys
import threading
import time as _time
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
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from copilot import CopilotClient, SessionHooks, define_tool
from copilot.tools import ToolResult
from copilot.session import PermissionHandler
from copilot.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    AssistantReasoningData,
    AssistantReasoningDeltaData,
    SessionErrorData,
    SessionIdleData,
    SessionInfoData,
    SkillInvokedData,
    ToolExecutionCompleteData,
    ToolExecutionStartData,
)

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

_LOG = os.getenv("LOG_AGENT_EVENTS", "").lower() == "true"
_logger = _logging.getLogger("agent.events")
_trace_logger = _logging.getLogger("trace")


def _log_event(msg: str) -> None:
    if _LOG:
        _logger.info(msg)


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


def _sse_event(event: BaseEvent) -> str:
    """Format an AG-UI event as an SSE data line."""
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


def _jsonable(value):
    """Best-effort conversion of SDK event payloads into JSON-safe structures."""
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
            return {
                str(k): _jsonable(v)
                for k, v in vars(value).items()
                if not str(k).startswith("_")
            }
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


def _telemetry_result(result) -> ProductToolResult | None:
    """Read only the SDK's native telemetry field; never inspect model-visible text."""
    telemetry = getattr(result, "tool_telemetry", None)
    if telemetry is None and isinstance(result, dict):
        telemetry = result.get("tool_telemetry")
    if not isinstance(telemetry, dict) or not isinstance(telemetry.get("product_result"), dict):
        return None
    try:
        return ProductToolResult.from_dict(telemetry["product_result"])
    except (TypeError, ValueError):
        return None


def _path_within_workspace(workspace: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(workspace)
        return True
    except ValueError:
        return False


# Document Library search (RAG) lives in library.py — see search_documents tool below.


def _normalize_workspace_text(text: str) -> str:
    text = _re.sub(r"<!--\s*Page(?:Header|Footer|Break|Number)[^>]*-->", "", text, flags=_re.IGNORECASE)
    text = _re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


# ── Tool parameter models ───────────────────────────────────────────────────

class ReadFileParams(BaseModel):
    path: str = Field(
        default="",
        description=(
            "Optional path to a UTF-8 text or markdown file in the workspace. If omitted "
            "and there is exactly one uploaded file, that file is read."
        ),
    )


class WriteFileParams(BaseModel):
    path: str = Field(description="Path to a UTF-8 text or markdown artifact in the workspace")
    content: str = Field(description="Complete text content to write to the file")


class ListDocumentsParams(BaseModel):
    pass


class NavigateParams(BaseModel):
    destination_id: str = Field(description="One catalog destination ID.")
    engagement_id: str | None = Field(default=None, description="Required for engagement destinations.")


class ListTasksParams(BaseModel):
    engagement: str = Field(default="", description="Engagement name or id to list tasks from a shared engagement; empty = the personal space.")


class CreateTaskParams(BaseModel):
    title: str = Field(description="Task title, e.g. 'Draft Q3 planning doc'")
    engagement: str = Field(default="", description="Engagement name or id when the task belongs in a shared engagement (say the engagement the user meant, e.g. from '[Current view: …]' or their words); empty = personal space.")
    status: str = Field(default="", description="Status: 'To do', 'In progress', 'Blocked', or 'Done' (defaults to 'To do')")
    priority: str = Field(default="", description="Priority: 'Low', 'Medium', or 'High' (defaults to 'Medium')")
    group: str = Field(default="", description="Group/bucket, e.g. 'Work', 'Personal' (defaults to 'General')")
    due_date: str = Field(default="", description="Due date (YYYY-MM-DD), if known")


class UpdateTaskParams(BaseModel):
    task: str = Field(description="Task id or a distinctive part of its title")
    engagement: str = Field(default="", description="Engagement name or id when the task lives in a shared engagement; empty = personal space.")
    status: str = Field(default="", description="New status: 'To do', 'In progress', 'Blocked', or 'Done'")
    priority: str = Field(default="", description="New priority: 'Low', 'Medium', or 'High'")
    group: str = Field(default="", description="New group/bucket")
    due_date: str = Field(default="", description="New due date (YYYY-MM-DD)")


class DeleteTaskParams(BaseModel):
    task: str = Field(description="Task id or a distinctive part of its title")
    engagement: str = Field(default="", description="Engagement name or id when the task lives in a shared engagement; empty = personal space.")
    confirmed: bool = Field(default=False, description="Set true ONLY after the user has explicitly confirmed this deletion (e.g. by replying to the confirmation card).")


class AddSubtaskParams(BaseModel):
    task: str = Field(description="Task id or a distinctive part of its title")
    text: str = Field(description="The subtask to add")


class ListEventsParams(BaseModel):
    pass


class CreateEventParams(BaseModel):
    title: str = Field(description="Event title, e.g. 'Team standup'")
    date: str = Field(description="Event date (YYYY-MM-DD) — required")
    start: str = Field(default="", description="Start time (24h HH:MM), if known")
    end: str = Field(default="", description="End time (24h HH:MM), if known")
    type: str = Field(default="", description="Event type: 'Meeting', 'Reminder', 'Focus', … (defaults to 'Meeting')")


class UpdateEventParams(BaseModel):
    event: str = Field(description="Event id or a distinctive part of its title")
    title: str = Field(default="", description="New title")
    date: str = Field(default="", description="New date (YYYY-MM-DD)")
    start: str = Field(default="", description="New start time (24h HH:MM)")
    end: str = Field(default="", description="New end time (24h HH:MM)")
    type: str = Field(default="", description="New type: 'Meeting', 'Reminder', 'Focus', …")


class DeleteEventParams(BaseModel):
    event: str = Field(description="Event id or a distinctive part of its title")
    confirmed: bool = Field(default=False, description="Set true ONLY after the user has explicitly confirmed this deletion.")


class ListEngagementsParams(BaseModel):
    pass


class CreateEngagementParams(BaseModel):
    name: str = Field(description="Engagement name, e.g. 'Website Launch'")
    description: str = Field(default="", description="One-line description of the engagement")
    customer: str = Field(default="", description="Customer name, e.g. 'Contoso Retail' (free text, not a system of record)")
    target_date: str = Field(default="", description="Target/go-live date, YYYY-MM-DD")


class ShareEngagementParams(BaseModel):
    engagement_id: str = Field(description="Stable engagement ID to share")
    user: str = Field(description="Username to add, e.g. 'ava'")
    role: str = Field(default="viewer", description="Role to grant: 'viewer', 'editor', or 'owner'")


class GetEngagementParams(BaseModel):
    engagement_id: str = Field(description="Stable engagement ID to read")


class UpdateEngagementParams(BaseModel):
    engagement_id: str = Field(description="Stable engagement ID to update")
    name: str | None = Field(default=None, description="New name (owners only; omit to leave unchanged)")
    description: str | None = Field(default=None, description="New description (editors/owners; pass empty string to clear)")
    customer: str | None = Field(default=None, description="New customer name (editors/owners; pass empty string to clear)")
    start_date: str | None = Field(default=None, description="New start date YYYY-MM-DD (editors/owners; pass empty string to clear)")
    target_date: str | None = Field(default=None, description="New target date YYYY-MM-DD (editors/owners; pass empty string to clear)")


class SetEngagementStatusParams(BaseModel):
    engagement_id: str = Field(description="Stable engagement ID")
    status: str = Field(description="'green', 'yellow', or 'red'")
    note: str = Field(default="", description="The why — REQUIRED for yellow/red (e.g. 'security review rejected the network design')")


class SearchDocumentsParams(BaseModel):
    query: str = Field(description="What to look for in the Library, in natural language, e.g. 'what did we decide about the budget' or 'standard NDA term'")


class SaveToLibraryParams(BaseModel):
    filename: str = Field(description="The session file to save into the persistent Library (e.g. 'acme-standard-nda.md'). Use the filename shown in Documents.")


class ListLibraryParams(BaseModel):
    pass


class CreateScheduleParams(BaseModel):
    title: str = Field(description="Short name for the reminder, e.g. 'Daily agenda email'")
    prompt: str = Field(description="The instruction to run on the schedule, phrased as you'd ask the assistant, e.g. 'Summarize my agenda and any tasks or events due in the next 3 days'. Its output is emailed to the user.")
    frequency: str = Field(description="'daily' or 'weekly'")
    time: str = Field(description="Time of day to run, 24h HH:MM, e.g. '08:00'")
    timezone: str = Field(default="UTC", description="IANA timezone for the time, e.g. 'America/New_York'. Defaults to UTC if unknown.")
    days: str = Field(default="", description="For weekly only: comma-separated day names, e.g. 'Mon,Wed,Fri'. Ignored for daily.")


class ListSchedulesParams(BaseModel):
    pass


class DeleteScheduleParams(BaseModel):
    schedule: str = Field(description="Schedule id or a distinctive part of its title")
    confirmed: bool = Field(default=False, description="Set true ONLY after the user has explicitly confirmed this deletion.")


# ── Tool builders (closures over the session workspace) ─────────────────────

# The legacy parameter classes below remain for inactive tools.  Active tools use
# this one shared contract catalog so Copilot and Deep Agents cannot drift.
NavigateParams = NavigateCommand
ListEngagementsParams = ListEngagementsCommand
CreateEngagementParams = CreateEngagementCommand
GetEngagementParams = GetEngagementCommand
UpdateEngagementParams = UpdateEngagementCommand
SetEngagementStatusParams = SetEngagementStatusCommand
ShareEngagementParams = ShareEngagementCommand

def _build_flow_tools(working_dir: str, user_id: str) -> list:
    engagement_service = EngagementService(AppdbEngagementRepository(appdb), appdb.find_user)
    workspace_root = Path(working_dir).resolve()

    def _load() -> dict:
        return appdb.load_state(user_id)

    def _update(mutator):
        """Concurrency-safe owner-doc mutation (ETag + retry, see appdb.update).
        `mutator(data)` mutates and returns the tool's result string; raise
        appdb.AbortWrite(msg) to return a message without writing (validation/no-op).

        Validation rule for tools: input-only checks (no doc needed — empty title, bad
        frequency) return early BEFORE _update; checks that inspect the current doc
        (resolve-by-ref, ambiguity, not-found) raise AbortWrite INSIDE the mutator so they
        re-evaluate against the fresh read on each retry."""
        return appdb.update_state(user_id, mutator)

    def _resolve_task_strict(data: dict, ref: str):
        """Resolve a task ref to (task, error). Prefer exact id/title; fall back to a
        unique substring. Returns (None, error_string) when not found / ambiguous."""
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

    def _engagement_detail_text(record: dict) -> str:
        """Model-visible detail for one Engagement: the facts a user would ask about.
        The typed ProductToolResult stays the control-plane truth; this is the data."""
        lines = [
            f"Engagement [{record['id']}] {record.get('name', '')}",
            f"customer={record.get('customer') or 'n/a'} | status={record.get('status', 'green')}"
            + (f" ({record['statusNote']})" if record.get("statusNote") else "")
            + f" | start={record.get('startDate') or 'n/a'} | target={record.get('targetDate') or 'n/a'}",
            "members: " + (", ".join(f"{m.get('userId')}({m.get('role')})" for m in record.get("members") or []) or "none"),
        ]
        if record.get("description"):
            lines.append(f"description: {record['description']}")
        for label, key, fields in (
            ("tasks", "tasks", ("title", "status", "priority", "dueDate")),
            ("actions", "actions", ("title", "status", "owner", "dueDate")),
            ("milestones", "milestones", ("title", "status", "dueDate")),
            ("risks", "risks", ("title", "severity", "status")),
        ):
            items = record.get(key) or []
            if items:
                lines.append(f"{label}:")
                for item in items:
                    parts = [str(item.get(field)) for field in fields if item.get(field)]
                    lines.append(f"- [{item.get('id')}] " + " | ".join(parts))
        artifacts = record.get("library") or []
        lines.append(f"artifacts: {len(artifacts)}")
        conventions = record.get("conventions") or []
        if conventions:
            lines.append("conventions: " + "; ".join(c.get("text", "") for c in conventions))
        return "\n".join(lines)

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

    def _tool_result(result: ProductToolResult, text: str) -> ToolResult:
        return ToolResult(text_result_for_llm=text, tool_telemetry={"product_result": result.to_dict()})

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

    @define_tool(name="navigate", description="Navigate to an explicit CSA Workbench catalog destination.")
    def navigate(params: NavigateParams) -> ToolResult:
        result = navsvc.destination_for(user_id, params.destination_id, params.engagement_id)
        return _tool_result(result, result.message or "Navigation request processed.")

    @define_tool(name="list_tasks", description="List the tasks with their status, priority, group, due date, a computed overdue flag, and subtask progress.")
    def list_tasks(params: ListTasksParams) -> str:
        scope_label = "personal"
        if params.engagement.strip():
            eng, err = _resolve_engagement_ref(params.engagement)
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

    @define_tool(name="create_task", description="Create a task in the to-do list.")
    def create_task(params: CreateTaskParams) -> str:
        if not params.title.strip():
            return "TITLE_REQUIRED: a task needs a title."
        if params.engagement.strip():
            eng, err = _resolve_engagement_ref(params.engagement)
            if err:
                return err
            def _pmut(doc):
                task = {
                    "id": appdb.new_id("t", doc["tasks"]),
                    "title": params.title.strip(),
                    "status": params.status.strip() or "To do",
                    "priority": params.priority.strip() or "Medium",
                    "group": params.group.strip() or "General",
                    "dueDate": params.due_date.strip(),
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
                "title": params.title.strip(),
                "status": params.status.strip() or "To do",
                "priority": params.priority.strip() or "Medium",
                "group": params.group.strip() or "General",
                "dueDate": params.due_date.strip(),
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

    @define_tool(name="update_task", description="Update a task's status, priority, group, or due date.")
    def update_task(params: UpdateTaskParams) -> str:
        if params.engagement.strip():
            eng, perr = _resolve_engagement_ref(params.engagement)
            if perr:
                return perr
            def _pmut(doc):
                t, err = _resolve_task_strict(doc, params.task)
                if err:
                    raise appdb.AbortWrite(err)
                changed = []
                for field, val in (("status", params.status), ("priority", params.priority),
                                   ("group", params.group)):
                    if val.strip():
                        t[field] = val.strip()
                        changed.append(f"{field}={t[field]}")
                if params.due_date.strip():
                    t["dueDate"] = params.due_date.strip()
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
            t, err = _resolve_task_strict(data, params.task)
            if err:
                raise appdb.AbortWrite(err)
            changed = []
            if params.status.strip():
                t["status"] = params.status.strip()
                changed.append(f"status={t['status']}")
            if params.priority.strip():
                t["priority"] = params.priority.strip()
                changed.append(f"priority={t['priority']}")
            if params.group.strip():
                t["group"] = params.group.strip()
                changed.append(f"group={t['group']}")
            if params.due_date.strip():
                t["dueDate"] = params.due_date.strip()
                changed.append(f"due={t['dueDate']}")
            if not changed:
                raise appdb.AbortWrite("NO_CHANGES: specify a status, priority, group, or due_date to update.")
            data["currentRoute"] = appdb.task_route(t["id"])
            return f"UPDATED task [{t['id']}] '{t['title']}': {', '.join(changed)}."
        return _update(_mut)

    @define_tool(name="delete_task", description="Delete a task from the to-do list.")
    def delete_task(params: DeleteTaskParams) -> str:
        if not params.confirmed:
            data = _load() if not params.engagement.strip() else None
            scope_data = data
            if params.engagement.strip():
                eng_probe, perr0 = _resolve_engagement_ref(params.engagement)
                if perr0:
                    return perr0
                scope_data = eng_probe
            t, terr = _resolve_task_strict(scope_data, params.task)
            if terr:
                return terr
            return _confirm_card("delete_task", t["title"],
                                 f"Delete task [{t['id']}] permanently" + (f" from engagement {scope_data['name']}" if params.engagement.strip() else ""))
        if params.engagement.strip():
            eng, perr = _resolve_engagement_ref(params.engagement)
            if perr:
                return perr
            def _pmut(doc):
                t, err = _resolve_task_strict(doc, params.task)
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
            t, err = _resolve_task_strict(data, params.task)
            if err:
                raise appdb.AbortWrite(err)
            data["tasks"] = [x for x in data["tasks"] if x["id"] != t["id"]]
            data["currentRoute"] = "/todo"
            return f"DELETED task [{t['id']}] '{t['title']}'."
        return _update(_mut)

    @define_tool(name="add_subtask", description="Add a subtask to a task.")
    def add_subtask(params: AddSubtaskParams) -> str:
        text = params.text.strip()
        if not text:
            return "TEXT_REQUIRED: provide the subtask text."
        def _mut(data):
            t, err = _resolve_task_strict(data, params.task)
            if err:
                raise appdb.AbortWrite(err)
            t.setdefault("subtasks", []).append({"text": text, "done": False})
            data["currentRoute"] = appdb.task_route(t["id"])
            return f"ADDED subtask to '{t['title']}': {text}."
        return _update(_mut)

    @define_tool(name="list_events", description="List the calendar events with their date, time, and type.")
    def list_events(params: ListEventsParams) -> str:
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

    @define_tool(name="create_event", description="Create a calendar event (a meeting, reminder, or focus block). A date is required.")
    def create_event(params: CreateEventParams) -> str:
        if not params.title.strip():
            return "TITLE_REQUIRED: an event needs a title."
        if not params.date.strip():
            return "DATE_REQUIRED: an event needs a date (YYYY-MM-DD)."
        def _mut(data):
            event = {
                "id": appdb.new_id("e", data["events"]),
                "title": params.title.strip(),
                "date": params.date.strip(),
                "start": params.start.strip(),
                "end": params.end.strip(),
                "type": params.type.strip() or "Meeting",
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

    @define_tool(name="update_event", description="Update or move a calendar event's title, date, time, or type.")
    def update_event(params: UpdateEventParams) -> str:
        def _mut(data):
            e, err = _resolve_event_strict(data, params.event)
            if err:
                raise appdb.AbortWrite(err)
            changed = []
            if params.title.strip():
                e["title"] = params.title.strip()
                changed.append(f"title={e['title']}")
            if params.date.strip():
                e["date"] = params.date.strip()
                changed.append(f"date={e['date']}")
            if params.start.strip():
                e["start"] = params.start.strip()
                changed.append(f"start={e['start']}")
            if params.end.strip():
                e["end"] = params.end.strip()
                changed.append(f"end={e['end']}")
            if params.type.strip():
                e["type"] = params.type.strip()
                changed.append(f"type={e['type']}")
            if not changed:
                raise appdb.AbortWrite("NO_CHANGES: specify a title, date, start, end, or type to update.")
            data["currentRoute"] = appdb.event_route(e["id"])
            return f"UPDATED event [{e['id']}] '{e['title']}': {', '.join(changed)}."
        return _update(_mut)

    @define_tool(name="delete_event", description="Delete a calendar event.")
    def delete_event(params: DeleteEventParams) -> str:
        if not params.confirmed:
            e, eerr = _resolve_event_strict(_load(), params.event)
            if eerr:
                return eerr
            return _confirm_card("delete_event", e["title"], f"Delete event [{e['id']}] permanently")
        def _mut(data):
            e, err = _resolve_event_strict(data, params.event)
            if err:
                raise appdb.AbortWrite(err)
            data["events"] = [x for x in data["events"] if x["id"] != e["id"]]
            data["currentRoute"] = "/calendar"
            return f"DELETED event [{e['id']}] '{e['title']}'."
        return _update(_mut)

    @define_tool(name="list_documents", description="List the documents available in the workspace (provided source documents and generated artifacts) with a one-line descriptor. Use to discover what you can read before answering document questions.")
    def list_documents(params: ListDocumentsParams) -> str:
        docs = []
        for p in sorted(workspace_root.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            descriptor = ""
            try:
                # Read line-by-line and stop at the first descriptor — don't slurp whole
                # (possibly multi-MB) files just to grab one line.
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

    @define_tool(name="read_workspace_file", description="Read a complete UTF-8 text or markdown file (e.g. an uploaded document) from the workspace.")
    def read_workspace_file(params: ReadFileParams) -> str:
        raw_path = params.path.strip()
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
            # Fail loud: never feed silently-mangled (U+FFFD-substituted) content to
            # the model, which would then assert facts grounded in corrupted text.
            return f"ENCODING_UNSUPPORTED: {raw_path} is not valid UTF-8 text."
        text = _normalize_workspace_text(decoded)
        return f"PATH: {resolved.name}\n\n{text}"

    @define_tool(name="write_file", description="Write a complete UTF-8 text or markdown artifact (e.g. a generated summary) to the workspace.")
    def write_file(params: WriteFileParams) -> str:
        raw_path = params.path.strip()
        if not raw_path:
            return "PATH_REQUIRED"
        candidate = Path(raw_path)
        resolved = (candidate if candidate.is_absolute() else workspace_root / candidate).resolve()
        if not _path_within_workspace(workspace_root, resolved):
            return "INVALID_PATH: must stay within the workspace"
        if resolved.name.startswith("."):
            return "INVALID_PATH: hidden files are not valid output targets"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(params.content, encoding="utf-8")
        return f"WROTE {resolved.name} ({resolved.stat().st_size} bytes)."

    @define_tool(name="list_engagements", description="List the shared engagements the user belongs to, including their stable IDs.")
    def list_engagements(params: ListEngagementsParams) -> ToolResult:
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

    @define_tool(name="create_engagement", description="Create a new shared engagement (customer delivery workspace). The user becomes its owner. New engagements start green.")
    def create_engagement(params: CreateEngagementParams) -> ToolResult:
        outcome = engagement_service.create(user_id, {"name": params.name, "description": params.description,
                                                       "customer": params.customer, "targetDate": params.target_date})
        result = engagement_product_result(outcome)
        text = f"Engagement [{outcome.record['id']}] is available." if outcome.record else result.message
        return _tool_result(result, text)

    @define_tool(name="get_engagement", description="Read one visible engagement by stable ID.")
    def get_engagement(params: GetEngagementParams) -> ToolResult:
        outcome = engagement_service.get(user_id, params.engagement_id)
        result = engagement_product_result(outcome)
        text = _engagement_detail_text(outcome.record) if outcome.record else result.message
        return _tool_result(result, text)

    @define_tool(name="update_engagement", description="Update description, customer, or dates as an editor/owner; changing name requires owner access. Omit fields to leave them unchanged; empty optional fields clear them.")
    def update_engagement(params: UpdateEngagementParams) -> ToolResult:
        values = {key: value for key, value in (("name", params.name), ("description", params.description),
                  ("customer", params.customer), ("startDate", params.start_date), ("targetDate", params.target_date)) if value is not None}
        outcome = engagement_service.update(user_id, params.engagement_id, values)
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement update processed." if outcome.status == "committed" else result.message)

    @define_tool(name="set_engagement_status", description="Set an engagement's status (green/yellow/red). Yellow and red REQUIRE a note saying why — ask the user for the reason if they didn't give one. Requires editor access.")
    def set_engagement_status(params: SetEngagementStatusParams) -> ToolResult:
        outcome = engagement_service.update(user_id, params.engagement_id, {"status": params.status, "statusNote": params.note})
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement status processed." if outcome.status == "committed" else result.message)

    @define_tool(name="share_engagement", description="Share a engagement with another user (grant viewer, editor, or owner access). Only a engagement owner can share.")
    def share_engagement(params: ShareEngagementParams) -> ToolResult:
        outcome = engagement_service.share(user_id, params.engagement_id, params.user, params.role)
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement sharing processed." if outcome.status == "committed" else result.message)

    @define_tool(name="search_documents", description="Semantic search (RAG) over the persistent Library — the user's saved/reference knowledge base. Returns the top matching passages, each with its source filename. Use to answer 'what did I decide about X', 'find … in my library', or 'search my docs'. Note: this searches the PERSISTENT Library only; to read a file the user just uploaded this session, use read_workspace_file instead.")
    def search_documents(params: SearchDocumentsParams) -> str:
        query = params.query.strip()
        if not query:
            return "QUERY_REQUIRED: provide what to search for."
        return library.search(query)

    @define_tool(name="save_to_library", description="Save a session file (an upload or a doc you drafted) into the PERSISTENT Library so it's searchable across all future sessions. Use when the user says 'save this to my library/knowledge base', 'keep this permanently', etc. Session files are otherwise temporary and gone when the session ends.")
    def save_to_library(params: SaveToLibraryParams) -> str:
        filename = params.filename.strip()
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
                _logging.getLogger(__name__).error("save_to_library rollback failed for %s", filename, exc_info=True)
            raise

    @define_tool(name="list_library", description="List the documents in the persistent Library (the searchable knowledge base).")
    def list_library(params: ListLibraryParams) -> str:
        docs = _load()["library"]
        if not docs:
            return "The Library is empty. Upload a document and save it to the Library."
        lines = [f"{len(docs)} document(s) in the Library:"]
        for d in docs:
            lines.append(f"- {d['filename']} ({d.get('source') or 'doc'}, saved {(d.get('savedAt') or '')[:10]})")
        return "\n".join(lines)

    @define_tool(name="create_schedule", description="Create a scheduled reminder: a saved instruction the app runs automatically on a daily or weekly cadence and emails the result to the user. Use for 'email me a daily summary', 'remind me every Monday', etc.")
    def create_schedule(params: CreateScheduleParams) -> str:
        title = params.title.strip()
        prompt = params.prompt.strip()
        if not title:
            return "TITLE_REQUIRED: the reminder needs a short name."
        if not prompt:
            return "PROMPT_REQUIRED: the reminder needs an instruction to run."
        frequency = params.frequency.strip().lower()
        if frequency not in appdb.SCHEDULE_FREQUENCIES:
            return f"BAD_FREQUENCY: use one of {appdb.SCHEDULE_FREQUENCIES}."
        try:
            timezone_name = appdb.normalize_timezone(params.timezone)
        except ValueError as exc:
            return f"BAD_TIMEZONE: {exc}"
        days_of_week: list[int] = []
        if frequency == "weekly":
            name_to_idx = {n.lower(): i for i, n in enumerate(appdb.DAY_NAMES)}
            bad = []
            for tok in params.days.split(","):
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
            next_run = appdb.compute_next_run(frequency, params.time, timezone_name, days_of_week)
        except (ValueError, RuntimeError) as exc:
            return f"BAD_TIME: {exc}"
        def _mut(data):
            schedule = {
                "id": appdb.new_id("s", data["schedules"]),
                "title": title,
                "prompt": prompt,
                "frequency": frequency,
                "time": params.time.strip(),
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

    @define_tool(name="list_schedules", description="List the scheduled reminders with their cadence, next run time, and status.")
    def list_schedules(params: ListSchedulesParams) -> str:
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

    @define_tool(name="delete_schedule", description="Delete a scheduled reminder.")
    def delete_schedule(params: DeleteScheduleParams) -> str:
        if not params.confirmed:
            sch = appdb.resolve_schedule(_load(), params.schedule)
            if sch is None:
                return f"NOT_FOUND: no reminder matches '{params.schedule}'."
            return _confirm_card("delete_schedule", sch["title"], f"Delete reminder [{sch['id']}] permanently")
        def _mut(data):
            s = appdb.resolve_schedule(data, params.schedule)
            if s is None:
                raise appdb.AbortWrite(f"NOT_FOUND: no reminder matches '{params.schedule}'.")
            data["schedules"] = [x for x in data["schedules"] if x["id"] != s["id"]]
            data["currentRoute"] = "/reminders"
            return f"DELETED reminder [{s['id']}] '{s['title']}'."
        return _update(_mut)

    return [
        navigate,
        list_engagements, create_engagement, get_engagement, update_engagement, set_engagement_status,
        share_engagement,
    ]


# Internal tool names never surfaced to the frontend (the "skill" tool is handled
# separately via SkillInvokedData). Empty today; kept for easy extension.
_HIDDEN_TOOLS: set[str] = set()


class AgentSession:
    """Async context manager holding a persistent Copilot session (SDK 1.0.x)."""

    def __init__(self, working_dir: str, token: str | None = None, session_id: str = "default",
                 user_id: str = "dan"):
        self._working_dir = working_dir
        self._initial_token = token
        self._token = token
        self._session_id = session_id
        self._user_id = user_id
        self._client: CopilotClient | None = None
        self._session = None
        self._unsubscribe = None
        self._queue: asyncio.Queue[BaseEvent | None] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tool_names: dict[str, tuple[str, float]] = {}
        self._tools_called: int = 0
        self._turn_start: float = 0.0
        self._status: str = "idle"
        self._turn_active: bool = False
        self._credential: DefaultAzureCredential | None = None

        self._thread_id: str = str(uuid.uuid4())
        self._run_id: str = ""
        self._current_message_id: str = ""
        self._message_started: bool = False
        self._reasoning_active: bool = False
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

    def _write_raw_sdk_record(self, record: dict) -> None:
        if not self._raw_sdk_log_path:
            return
        from datetime import datetime, timezone
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self._session_id,
            **record,
        }
        line = _json.dumps(payload, default=str)
        with self._raw_sdk_log_lock:
            with open(self._raw_sdk_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    @property
    def status(self) -> str:
        return self._status

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def user_id(self) -> str:
        return self._user_id

    async def __aenter__(self) -> "AgentSession":
        if self._raw_sdk_log_path:
            Path(self._raw_sdk_log_path).write_text("", encoding="utf-8")

        token = self._token or self._initial_token or os.getenv("AZURE_OPENAI_TOKEN")
        if not token:
            self._credential = DefaultAzureCredential()
            tok = await self._credential.get_token("https://cognitiveservices.azure.com/.default")
            token = tok.token
        self._token = token

        self._client = CopilotClient(use_logged_in_user=False)
        await self._client.start()
        self._loop = asyncio.get_running_loop()

        skills_dir = str(Path(__file__).parent / "skills")
        custom_tools = _build_flow_tools(self._working_dir, self._user_id)
        available_tools = [t.name for t in custom_tools]

        deployment = os.environ["AZURE_DEPLOYMENT"]
        # Reasoning models (the gpt-5 family, excluding the *-chat variants) emit visible
        # reasoning summaries through the Responses API; plain chat models use completions.
        is_reasoning = deployment.startswith("gpt-5") and "chat" not in deployment
        provider = {
            "type": "azure",
            "base_url": os.environ["AZURE_ENDPOINT"],
            "bearer_token": token,
            "wire_api": "responses" if is_reasoning else "completions",
            "azure": {"api_version": os.getenv("AZURE_API_VERSION", "2024-10-21")},
        }
        reasoning_kwargs = {}
        if is_reasoning:
            reasoning_kwargs = {
                "reasoning_effort": os.getenv("REASONING_EFFORT", "medium"),
                "reasoning_summary": "concise",
            }

        self._session = await self._client.create_session(
            model=deployment,
            provider=provider,
            **reasoning_kwargs,
            system_message={"mode": "replace", "content": SYSTEM_PROMPT + _user_prompt_line(self._user_id)},
            working_directory=self._working_dir,
            tools=custom_tools,
            available_tools=available_tools,
            streaming=True,
            skip_custom_instructions=True,
            enable_skills=False,
            on_permission_request=PermissionHandler.approve_all,
            hooks=SessionHooks(on_pre_tool_use=self._pre_tool_use),
            on_event=self._on_event,
        )

        _trace(
            "agent.session_initialized",
            session_id=self._session_id,
            working_dir=self._working_dir,
            model=os.environ.get("AZURE_DEPLOYMENT"),
            available_tools=available_tools,
            skill_directories=[],
        )
        self._write_raw_sdk_record({"kind": "session_initialized", "available_tools": available_tools})
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session:
            try:
                await self._session.disconnect()
            except Exception:
                _logger.warning("session disconnect failed", exc_info=True)
        if self._client:
            await self._client.stop()
        if self._credential:
            await self._credential.close()

    async def _pre_tool_use(self, hook_input, _context):
        """Trace tool calls before execution. Permission is handled by approve_all.

        The SDK calls this as ``handler(input_dict, {"session_id": ...})``; ``input_dict``
        is a TypedDict-shaped dict with ``toolName`` / ``toolArgs`` keys.
        """
        _trace(
            "agent.pre_tool_use",
            session_id=self._session_id,
            run_id=self._run_id,
            tool=hook_input.get("toolName") if isinstance(hook_input, dict) else None,
            args=_jsonable(hook_input.get("toolArgs") if isinstance(hook_input, dict) else None),
        )
        return {"permissionDecision": "allow"}

    def _enqueue(self, event: BaseEvent) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def _enqueue_sse(self, payload: dict) -> None:
        """Enqueue an already-formatted SSE line (for custom AG-UI-style events)."""
        self._loop.call_soon_threadsafe(self._queue.put_nowait, f"data: {_json.dumps(payload)}\n\n")

    def _finish(self) -> None:
        self._turn_active = False
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)

    def _on_event(self, event) -> None:
        """Translate SDK session events (1.0.x *Data classes) into AG-UI events."""
        data = getattr(event, "data", None)
        self._write_raw_sdk_record(
            {
                "kind": "sdk_event",
                "run_id": self._run_id,
                "event_type": type(data).__name__ if data is not None else str(getattr(event, "type", "?")),
                "data": _jsonable(data),
            }
        )

        if isinstance(data, AssistantReasoningDeltaData):
            self._status = "thinking"
            delta = data.delta_content or ""
            if not delta:
                return
            if not self._reasoning_active:
                self._reasoning_active = True
                self._enqueue_sse({"type": "REASONING_START"})
            self._enqueue_sse({"type": "REASONING_DELTA", "delta": delta})
            return

        if isinstance(data, AssistantReasoningData):
            if self._reasoning_active:
                self._enqueue_sse({"type": "REASONING_END"})
                self._reasoning_active = False
            return

        if isinstance(data, AssistantMessageDeltaData):
            self._status = "thinking"
            delta = data.delta_content or ""
            if not delta:
                return
            # assistant prose begins — close any open reasoning block first
            if self._reasoning_active:
                self._enqueue_sse({"type": "REASONING_END"})
                self._reasoning_active = False
            if not self._message_started:
                self._current_message_id = str(uuid.uuid4())
                self._message_started = True
                self._enqueue(TextMessageStartEvent(message_id=self._current_message_id, role="assistant"))
            self._enqueue(TextMessageContentEvent(message_id=self._current_message_id, delta=delta))

        elif isinstance(data, AssistantMessageData):
            final = data.content or ""
            if not self._message_started and final:
                self._current_message_id = str(uuid.uuid4())
                self._message_started = True
                self._enqueue(TextMessageStartEvent(message_id=self._current_message_id, role="assistant"))
                self._enqueue(TextMessageContentEvent(message_id=self._current_message_id, delta=final))
            if self._message_started:
                self._enqueue(TextMessageEndEvent(message_id=self._current_message_id))
                self._message_started = False

        elif isinstance(data, ToolExecutionStartData):
            tool = data.tool_name or "tool"
            call_id = data.tool_call_id or str(uuid.uuid4())
            self._tool_names[call_id] = (tool, _time.monotonic())
            if tool in _HIDDEN_TOOLS or tool == "skill":
                return
            self._status = f"tool:{tool}"
            self._enqueue(ToolCallStartEvent(
                tool_call_id=call_id,
                tool_call_name=tool,
                parent_message_id=self._current_message_id or None,
            ))
            args_str = _args_to_str(data.arguments)
            if args_str:
                self._enqueue(ToolCallArgsEvent(tool_call_id=call_id, delta=args_str))
            _trace("agent.tool_start", session_id=self._session_id, run_id=self._run_id, tool=tool, call_id=call_id, args=args_str)

        elif isinstance(data, ToolExecutionCompleteData):
            call_id = data.tool_call_id
            entry = self._tool_names.pop(call_id, None) if call_id else None
            tool = entry[0] if entry else "tool"
            if tool in _HIDDEN_TOOLS or tool == "skill":
                return
            self._status = "thinking"
            self._tools_called += 1
            result = getattr(data, "result", None)
            product_result = _telemetry_result(data)
            if product_result is None:
                product_result = ProductToolResult("failed", "tool.missing_native_result", tool, "The tool did not return a structured result.")
            if call_id:
                payload = {"type": "TOOL_CALL_RESULT", "tool_call_id": call_id, "result": product_result.to_dict()}
                self._enqueue_sse(payload)
                if product_result.status in {"resolved", "committed"} and product_result.destination:
                    self._enqueue_sse({"type": "NAVIGATION_RESOLVED", "runId": self._run_id, "destination": dict(product_result.destination), "requestedAtNavigationVersion": self._navigation_version})
                self._enqueue(ToolCallEndEvent(tool_call_id=call_id))
            _trace("agent.tool_end", session_id=self._session_id, run_id=self._run_id, tool=tool, call_id=call_id, result=product_result.to_dict())

        elif isinstance(data, SkillInvokedData):
            # Surface skill loads as a lightweight step so the user-facing trace shows them.
            call_id = str(uuid.uuid4())
            self._enqueue(ToolCallStartEvent(
                tool_call_id=call_id,
                tool_call_name="skill",
                parent_message_id=self._current_message_id or None,
            ))
            self._enqueue(ToolCallArgsEvent(tool_call_id=call_id, delta=_json.dumps({"name": data.name})))
            self._enqueue(ToolCallEndEvent(tool_call_id=call_id))
            _trace("agent.skill_invoked", session_id=self._session_id, run_id=self._run_id, skill=data.name)

        elif isinstance(data, SessionInfoData):
            _trace("agent.session_info", session_id=self._session_id, run_id=self._run_id, info_type=getattr(data, "info_type", None), message=getattr(data, "message", None))

        elif isinstance(data, SessionIdleData):
            self._status = "idle"
            _trace("agent.turn_end", session_id=self._session_id, run_id=self._run_id, tools_called=self._tools_called)
            self._enqueue(RunFinishedEvent(thread_id=self._thread_id, run_id=self._run_id))
            self._finish()

        elif isinstance(data, SessionErrorData):
            self._status = "error"
            msg = getattr(data, "message", None) or "Unknown error"
            low = msg.lower()
            if "too many requests" in low or "429" in msg or "rate limit" in low:
                msg = "The AI service is temporarily rate-limited. Please wait 30–60 seconds and try again."
            elif "content management policy" in low or "content_filter" in low or "responsible ai" in low or "filtered" in low:
                # Surface a contained, on-brand refusal instead of leaking the raw Azure 400 +
                # support URL — the request tripped a safety filter; we decline plainly.
                msg = "I can't act on that request — it was flagged by the safety filter. I won't take actions that try to override my guardrails or operate outside your workspace."
            _trace("agent.error", session_id=self._session_id, run_id=self._run_id, message=msg)
            self._enqueue(RunErrorEvent(message=msg))
            self._finish()

    async def send(self, prompt: str, navigation_version: int = 0) -> AsyncGenerator[str, None]:
        """Send a prompt; yield SSE-formatted AG-UI events until the session is idle."""
        while not self._queue.empty():
            self._queue.get_nowait()

        self._run_id = str(uuid.uuid4())
        self._current_message_id = ""
        self._message_started = False
        self._reasoning_active = False
        self._tools_called = 0
        self._tool_names.clear()
        self._turn_start = _time.monotonic()
        self._status = "thinking"
        self._turn_active = True
        self._navigation_version = navigation_version

        _trace("agent.turn_start", session_id=self._session_id, run_id=self._run_id)
        self._write_raw_sdk_record({"kind": "turn_start", "run_id": self._run_id, "prompt": prompt})

        yield _sse_event(RunStartedEvent(thread_id=self._thread_id, run_id=self._run_id))

        try:
            await self._session.send(prompt)
            while True:
                item = await self._queue.get()
                if item is None:
                    break
                yield item if isinstance(item, str) else _sse_event(item)
        except Exception as exc:
            self._write_raw_sdk_record({"kind": "turn_exception", "run_id": self._run_id, "error": repr(exc)})
            raise
        finally:
            # If the consumer was torn down mid-turn (client abort / new chat / timeout),
            # the SDK turn is still running on its own thread and its tools would keep
            # mutating the workspace. Interrupt it so Stop/New-Chat actually stop work.
            if self._turn_active and self._session is not None:
                try:
                    self._session.abort()
                except Exception:
                    _logger.warning("session abort failed", exc_info=True)
                self._turn_active = False
            self._write_raw_sdk_record({"kind": "turn_finalized", "run_id": self._run_id, "status": self._status})
