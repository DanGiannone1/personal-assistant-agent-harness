"""AgentSession wrapping the GitHub Copilot SDK (1.0.x) with an event queue.

Provides a streaming async generator interface for running agent turns against
Azure OpenAI. Translates SDK session events into AG-UI protocol events.

The agent operates on a per-session workspace folder. Application state (the mock
"Personal Assistant" productivity data) lives in a JSON doc in that workspace (see appdb.py); the
tools read and mutate it, and the frontend renders it via /app/state.
"""

import asyncio
import json as _json
import logging as _logging
import os
import re as _re
import threading
import time as _time
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

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
You are the assistant embedded in Personal Assistant — a simple personal-productivity app for managing
**tasks**, a **calendar**, and **documents**. The app has these pages: Home (today's
agenda — what's due, what's overdue, the next events), To-Do (tasks grouped into buckets,
each with a status, priority, group, optional due date, and subtasks), Calendar (events —
meetings, reminders, focus blocks — by day), and Documents (notes and drafts you read and
write). You help by acting directly on the app through tools.

You operate inside the user's own session. The tools you call read and mutate the
*real* application state, and the user sees the result in the app next to this chat.
Only claim you did something after the tool that does it has returned successfully —
never say a record was created/updated/deleted or that you navigated unless the tool call succeeded.

How you work:
- Read the request, then take the single most direct action. Do not over-plan. (Exception: a few
  requests are explicitly multi-step routines — like a weekly review — where a skill lays out a
  sequence of steps. For those, load the skill and complete all of its steps in the turn rather
  than stopping after one tool.)
- For "take me to / go to / open / show me <place>" requests, call `navigate` with the
  user's destination words **verbatim**. Don't pre-resolve a vague phrase — pass it and
  let `navigate` decide. If it returns AMBIGUOUS, list the candidates and ask which one.
  If NOT_FOUND, say so and list the closest options. Never claim you navigated unless the
  tool resolved a destination.
- Tasks: use `list_tasks` to review (it returns a computed `overdue` flag and each task's
  subtask progress), `create_task` to add one, `update_task` to change status/priority/
  group/due date, `add_subtask` to add a subtask, and `delete_task` to remove one.
- Events: use `list_events` to review the calendar, `create_event` to schedule one (a date
  is required), `update_event` to move or change it, and `delete_event` to remove one.
- Reminders: use `create_schedule` for recurring requests the user wants to receive by email
  ("email me a daily summary", "every Monday send me…") — capture the instruction as the
  `prompt`, pick `daily`/`weekly`, a `time` (HH:MM), and a `timezone` if the user implies one
  (ask only if genuinely unclear). Use `list_schedules` to review and `delete_schedule` to
  cancel. The app runs the saved prompt on the cadence and emails whatever it produces.
- For "what's overdue", use the `overdue` flag from `list_tasks` and the "[Today: …]"
  context — never judge dates yourself.
- Documents come in two tiers. **Session files** are this session's uploads + drafts —
  temporary, read them *directly* with `list_documents` then `read_workspace_file`. The
  **Library** is the user's *persistent* knowledge base — searched with `search_documents`
  (RAG) and persisted across all sessions.
- To write or revise a document (a brief, notes, a summary), use `write_file` — it appears
  in Documents as a session file and opens in the artifact canvas.
- To make a session file permanent and searchable, use `save_to_library` (e.g. "save this
  to my library/knowledge base"); `list_library` shows what's in it. A session file is NOT
  in the Library until saved.
- For "what did I decide about X", "search my library", or any question that needs grounding
  across the persistent knowledge base, use `search_documents` — answer **only** from the
  returned passages and cite the source filename(s). If it returns NO_RESULTS, say nothing
  matched; if SEARCH_NOT_CONFIGURED/SEARCH_FAILED, tell the user search is unavailable —
  never make up an answer. To *compare* an uploaded session file against the Library, read
  the session file (`read_workspace_file`) AND `search_documents`, then contrast them.

The user's current view may be provided as context (e.g. "[Current view: To-Do]"). Use it
to resolve "here" / "this". The current date is provided as "[Today: …]".

Style:
- Be concise and friendly. One or two sentences is usually enough.
- State concretely what you did ("Added the high-priority task" / "Moved the design review
  to Thursday" / "Drafted the project brief").
- Don't mention tools, routes, file paths, or IDs unless asked. Don't invent data the tools
  didn't return.
- Stay in your lane: you're this app's assistant. For clearly off-topic requests (general
  trivia, unrelated coding), don't answer at length — briefly redirect ("I'm focused on your
  Personal Assistant workspace — want me to look at your tasks, calendar, or a document?").
"""


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


def _result_text(result) -> str:
    """Extract the tool's returned text from the SDK result.

    The SDK delivers tool results as a `ToolExecutionCompleteResult` object (or a
    dict) carrying the tool's string under `content` — NOT a bare string. Pull the
    text out of any of these shapes so outcome classification reads the real marker
    (e.g. "AMBIGUOUS"), not a repr of the wrapper object.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("content", "text", "detailed_content"):
            val = result.get(key)
            if isinstance(val, str) and val:
                return val
        return ""
    for attr in ("content", "text", "detailed_content"):
        val = getattr(result, attr, None)
        if isinstance(val, str) and val:
            return val
    return str(result or "")


_NOOP_MARKERS = {"AMBIGUOUS", "NO_CHANGES", "NO_DOCUMENTS", "NO_RESULTS"}
_ERROR_MARKERS = {"INVALID_PATH", "FILE_NOT_FOUND", "BINARY_FILE_UNSUPPORTED", "PATH_REQUIRED", "ENCODING_UNSUPPORTED", "TITLE_REQUIRED", "TEXT_REQUIRED", "DATE_REQUIRED", "SEARCH_NOT_CONFIGURED", "SEARCH_FAILED", "QUERY_REQUIRED", "LIBRARY_FAILED", "FILENAME_REQUIRED", "UNSUPPORTED"}


def _tool_outcome(result, success) -> str:
    """Classify a tool result as ok | noop | error so the UI trace reflects reality.

    Classify ONLY on the leading status marker our tools emit (NAVIGATED / CREATED /
    AMBIGUOUS / *_NOT_FOUND / ...). We deliberately do NOT scan the whole result body
    — document/template content returned by read/get tools could otherwise contain a
    marker word and flip a real success to a false error. Keeps the trace honest.
    """
    text = _result_text(result).strip()
    head = text.split(None, 1)[0].rstrip(":") if text else ""
    if head in _NOOP_MARKERS:
        return "noop"
    if head in _ERROR_MARKERS or head.endswith("NOT_FOUND"):
        return "error"
    if success is False:
        return "error"
    # Fail loud: an empty result with no positive marker is not a real success —
    # don't show a green check for a tool that produced nothing.
    if not text:
        return "error"
    return "ok"


def _nav_candidates(result) -> list[str]:
    """Pull candidate destination titles out of a navigate AMBIGUOUS/NOT_FOUND result
    so the UI can offer them as one-click chips."""
    text = _result_text(result)
    marker = "destinations: " if "destinations: " in text else ("options: " if "options: " in text else None)
    if not marker:
        return []
    tail = text.split(marker, 1)[1]
    tail = tail.split(". ", 1)[0].rstrip(".")
    # Candidates are joined with "; " by the navigate tool — split on that only
    # (splitting on the word "and" would fragment titles like "Research and Development").
    parts = [p.strip() for p in tail.split(";") if p.strip()]
    return [p for p in parts if p and not p.lower().startswith("ask ")][:6]


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
    destination: str = Field(
        description="Where to go, as the user phrased it — a page ('Home', 'To-Do', 'Calendar', 'Documents') or a task or event title (e.g. 'Draft Q3 planning doc', 'Design review')."
    )


class ListTasksParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    pass


class CreateTaskParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    title: str = Field(description="Task title, e.g. 'Draft Q3 planning doc'")
    status: str = Field(default="", description="Status: 'To do', 'In progress', 'Blocked', or 'Done' (defaults to 'To do')")
    priority: str = Field(default="", description="Priority: 'Low', 'Medium', or 'High' (defaults to 'Medium')")
    group: str = Field(default="", description="Group/bucket, e.g. 'Work', 'Personal' (defaults to 'General')")
    due_date: str = Field(default="", description="Due date (YYYY-MM-DD), if known")


class UpdateTaskParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    task: str = Field(description="Task id or a distinctive part of its title")
    status: str = Field(default="", description="New status: 'To do', 'In progress', 'Blocked', or 'Done'")
    priority: str = Field(default="", description="New priority: 'Low', 'Medium', or 'High'")
    group: str = Field(default="", description="New group/bucket")
    due_date: str = Field(default="", description="New due date (YYYY-MM-DD)")


class DeleteTaskParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    task: str = Field(description="Task id or a distinctive part of its title")


class AddSubtaskParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    task: str = Field(description="Task id or a distinctive part of its title")
    text: str = Field(description="The subtask to add")


class ListEventsParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    pass


class CreateEventParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    title: str = Field(description="Event title, e.g. 'Team standup'")
    date: str = Field(description="Event date (YYYY-MM-DD) — required")
    start: str = Field(default="", description="Start time (24h HH:MM), if known")
    end: str = Field(default="", description="End time (24h HH:MM), if known")
    type: str = Field(default="", description="Event type: 'Meeting', 'Reminder', 'Focus', … (defaults to 'Meeting')")


class UpdateEventParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    event: str = Field(description="Event id or a distinctive part of its title")
    title: str = Field(default="", description="New title")
    date: str = Field(default="", description="New date (YYYY-MM-DD)")
    start: str = Field(default="", description="New start time (24h HH:MM)")
    end: str = Field(default="", description="New end time (24h HH:MM)")
    type: str = Field(default="", description="New type: 'Meeting', 'Reminder', 'Focus', …")


class DeleteEventParams(BaseModel):
    project: str = Field(default="", description="Optional project to act in (name or id). Leave empty for the personal space. Resolution: id, exact name, then unique substring among YOUR projects.")
    event: str = Field(description="Event id or a distinctive part of its title")


class SearchDocumentsParams(BaseModel):
    query: str = Field(description="What to look for in the Library, in natural language, e.g. 'what did we decide about the budget' or 'standard NDA term'")


class SaveToLibraryParams(BaseModel):
    filename: str = Field(description="The session file to save into the persistent Library (e.g. 'acme-standard-nda.md'). Use the filename shown in Documents.")


class ListLibraryParams(BaseModel):
    pass


class ListProjectsParams(BaseModel):
    pass


class CreateProjectParams(BaseModel):
    name: str = Field(description="Project name, e.g. 'Website Launch'")
    description: str = Field(default="", description="One-line description of the project")


class ShareProjectParams(BaseModel):
    project: str = Field(description="Project id or a distinctive part of its name")
    username: str = Field(description="Username of the person to add, e.g. 'ava'")
    role: str = Field(default="editor", description="owner, editor, or viewer")


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


# ── Tool builders (closures over the session workspace) ─────────────────────

def _build_flow_tools(working_dir: str, get_user) -> list:
    workspace_root = Path(working_dir).resolve()

    def _as_user(fn):
        """Bind the signed-in user around an appdb call. The SDK runs tools on ITS OWN
        thread, so the request-scoped contextvar set in server.py never reaches them —
        the user must be re-bound here, in the thread the tool actually executes on.
        `get_user()` reads the session's current user (set per turn from X-User-Id)."""
        token = appdb.set_current_user(get_user())
        try:
            return fn()
        finally:
            appdb.reset_current_user(token)

    def _load() -> dict:
        return _as_user(appdb.load)

    def _scope_load(project_ref: str):
        """(data, error) for a read in the chosen scope: a project (membership-resolved,
        same record shape) or the personal space when the ref is empty."""
        ref = (project_ref or "").strip()
        if not ref:
            return _load(), None
        proj = appdb.resolve_project(ref, get_user())
        if proj is None:
            names = ", ".join(p["name"] for p in appdb.list_projects_for(get_user())) or "none yet"
            return None, f"PROJECT_NOT_FOUND: no unique project of yours matches '{ref}'. Your projects: {names}."
        return proj, None

    def _scope_update(project_ref: str, mutator):
        """Apply a record mutation in the chosen scope. Project scope is resolved among
        the SIGNED-IN USER's projects, role-gated (viewers can't write), and the pane is
        pointed at the project page so the user sees where the record landed."""
        ref = (project_ref or "").strip()
        if not ref:
            return _update(mutator)
        uid = get_user()
        proj = appdb.resolve_project(ref, uid)
        if proj is None:
            names = ", ".join(p["name"] for p in appdb.list_projects_for(uid)) or "none yet"
            return f"PROJECT_NOT_FOUND: no unique project of yours matches '{ref}'. Your projects: {names}."
        if not appdb.can_write(appdb.project_role(proj, uid)):
            return f"FORBIDDEN: you are a viewer on '{proj['name']}' and can't modify it."
        result = appdb.update_project(proj["id"], mutator)
        # Follow-up navigation: land the pane on the project so the change is visible.
        _as_user(lambda: appdb.update(
            lambda d: d.__setitem__("currentRoute", f"/projects/{proj['id']}")
        ))
        return f"{result} (in project '{proj['name']}')"

    def _update(mutator):
        """Concurrency-safe user-doc mutation (ETag + retry, see appdb.update).
        `mutator(data)` mutates and returns the tool's result string; raise
        appdb.AbortWrite(msg) to return a message without writing (validation/no-op).

        Validation rule for tools: input-only checks (no doc needed — empty title, bad
        frequency) return early BEFORE _update; checks that inspect the current doc
        (resolve-by-ref, ambiguity, not-found) raise AbortWrite INSIDE the mutator so they
        re-evaluate against the fresh read on each retry."""
        return _as_user(lambda: appdb.update(mutator))

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

    @define_tool(name="navigate", description="Navigate the Personal Assistant app to a page, a project, a task, or a calendar event. Pass the user's destination words verbatim.")
    def navigate(params: NavigateParams) -> str:
        projects = appdb.list_projects_for(get_user())

        def _mut(data):
            result = appdb.resolve_destination_v2(
                data, params.destination, projects, current_route=data.get("currentRoute"),
            )
            if result["status"] == "resolved":
                data["currentRoute"] = result["path"]
                appdb.append_visit(data, result["path"], result["title"])
                alternates = result.get("alternates") or []
                if alternates:
                    opts = "; ".join(a["title"] for a in alternates)
                    return (f"NAVIGATED to {result['title']} ({result['path']}). "
                            f"Decided by your context — alternatives if wrong: {opts}")
                return f"NAVIGATED to {result['title']} ({result['path']})"
            opts = "; ".join(c["title"] for c in result["candidates"])
            if result["status"] == "ambiguous":
                raise appdb.AbortWrite(f"AMBIGUOUS: '{params.destination}' matches multiple destinations: {opts}. Ask the user which one.")
            raise appdb.AbortWrite(f"NOT_FOUND: no destination matched '{params.destination}'. Closest options: {opts}.")
        return _update(_mut)

    @define_tool(name="list_tasks", description="List the tasks with their status, priority, group, due date, a computed overdue flag, and subtask progress.")
    def list_tasks(params: ListTasksParams) -> str:
        data, scope_err = _scope_load(params.project)
        if scope_err:
            return scope_err
        tasks = data["tasks"]
        if not tasks:
            return "No tasks yet."
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        n_over = sum(1 for t in tasks if appdb.is_overdue(t, today))
        lines = [f"{len(tasks)} task(s) | today={today} | overdue={n_over}:"]
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
            )
        return _scope_update(params.project, _mut)

    @define_tool(name="update_task", description="Update a task's status, priority, group, or due date.")
    def update_task(params: UpdateTaskParams) -> str:
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
        return _scope_update(params.project, _mut)

    @define_tool(name="delete_task", description="Delete a task from the to-do list.")
    def delete_task(params: DeleteTaskParams) -> str:
        def _mut(data):
            t, err = _resolve_task_strict(data, params.task)
            if err:
                raise appdb.AbortWrite(err)
            data["tasks"] = [x for x in data["tasks"] if x["id"] != t["id"]]
            data["currentRoute"] = "/todo"
            return f"DELETED task [{t['id']}] '{t['title']}'."
        return _scope_update(params.project, _mut)

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
        return _scope_update(params.project, _mut)

    @define_tool(name="list_events", description="List the calendar events with their date, time, and type.")
    def list_events(params: ListEventsParams) -> str:
        data, scope_err = _scope_load(params.project)
        if scope_err:
            return scope_err
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
        return _scope_update(params.project, _mut)

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
        return _scope_update(params.project, _mut)

    @define_tool(name="delete_event", description="Delete a calendar event.")
    def delete_event(params: DeleteEventParams) -> str:
        def _mut(data):
            e, err = _resolve_event_strict(data, params.event)
            if err:
                raise appdb.AbortWrite(err)
            data["events"] = [x for x in data["events"] if x["id"] != e["id"]]
            data["currentRoute"] = "/calendar"
            return f"DELETED event [{e['id']}] '{e['title']}'."
        return _scope_update(params.project, _mut)

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
        def _mut(data):
            s = appdb.resolve_schedule(data, params.schedule)
            if s is None:
                raise appdb.AbortWrite(f"NOT_FOUND: no reminder matches '{params.schedule}'.")
            data["schedules"] = [x for x in data["schedules"] if x["id"] != s["id"]]
            data["currentRoute"] = "/reminders"
            return f"DELETED reminder [{s['id']}] '{s['title']}'."
        return _update(_mut)

    # ── Projects (spec F2) ────────────────────────────────────────────────
    @define_tool(name="list_projects", description="List the projects the user belongs to, with their role, member count, and record counts.")
    def list_projects(params: ListProjectsParams) -> str:
        projects = appdb.list_projects_for(get_user())
        if not projects:
            return "No projects yet. Create one with create_project."
        lines = [f"{len(projects)} project(s):"]
        for p in projects:
            role = appdb.project_role(p, get_user())
            lines.append(
                f"- [{p['id']}] {p['name']} | your role={role} | members={len(p['members'])} | "
                f"tasks={len(p['tasks'])} | events={len(p['events'])}"
                + (f" | conventions={len(p['conventions'])}" if p.get("conventions") else "")
            )
        return "\n".join(lines)

    @define_tool(name="create_project", description="Create a new shared project. The user becomes its owner.")
    def create_project(params: CreateProjectParams) -> str:
        name = params.name.strip()
        if not name:
            return "NAME_REQUIRED: a project needs a name."
        project = appdb.create_project(name, get_user(), params.description)
        _as_user(lambda: appdb.update(
            lambda d: d.__setitem__("currentRoute", f"/projects/{project['id']}")
        ))
        return f"CREATED project [{project['id']}] '{project['name']}'."

    @define_tool(name="share_project", description="Add a user to a project by username, with a role (owner, editor, or viewer). Only a project owner can do this.")
    def share_project(params: ShareProjectParams) -> str:
        uid = get_user()
        proj = appdb.resolve_project(params.project, uid)
        if proj is None:
            return f"PROJECT_NOT_FOUND: no unique project of yours matches '{params.project}'."
        if appdb.project_role(proj, uid) != "owner":
            return f"FORBIDDEN: only the owner of '{proj['name']}' can manage members."
        role = params.role.strip().lower() or "editor"
        if role not in appdb.PROJECT_ROLES:
            return f"BAD_ROLE: role must be one of {list(appdb.PROJECT_ROLES)}."
        target = appdb.get_user(params.username)
        if target is None:
            return f"USER_NOT_FOUND: no user named '{params.username}'."
        def _mut(data):
            if any(m["userId"] == target["id"] for m in data["members"]):
                raise appdb.AbortWrite(f"NO_CHANGE: {target['displayName']} is already a member of '{proj['name']}'.")
            data["members"].append({"userId": target["id"], "role": role})
            return f"SHARED '{proj['name']}' with {target['displayName']} as {role}."
        return appdb.update_project(proj["id"], _mut)

    return [
        navigate,
        list_tasks, create_task, update_task, delete_task, add_subtask,
        list_events, create_event, update_event, delete_event,
        list_projects, create_project, share_project,
        list_documents, read_workspace_file, write_file,
        search_documents, save_to_library, list_library,
        create_schedule, list_schedules, delete_schedule,
    ]


# Internal tool names never surfaced to the frontend (the "skill" tool is handled
# separately via SkillInvokedData). Empty today; kept for easy extension.
_HIDDEN_TOOLS: set[str] = set()


class AgentSession:
    """Async context manager holding a persistent Copilot session (SDK 1.0.x)."""

    def __init__(self, working_dir: str, token: str | None = None, session_id: str = "default",
                 user_id: str | None = None):
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
        custom_tools = _build_flow_tools(self._working_dir, lambda: self._user_id)
        available_tools = [t.name for t in custom_tools] + ["skill"]

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
            system_message={"mode": "replace", "content": SYSTEM_PROMPT},
            working_directory=self._working_dir,
            tools=custom_tools,
            available_tools=available_tools,
            streaming=True,
            skip_custom_instructions=True,
            enable_skills=True,
            skill_directories=[skills_dir],
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
            skill_directories=[skills_dir],
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
            outcome = _tool_outcome(result, getattr(data, "success", None))
            if call_id:
                # Carry the real outcome so the UI trace reflects what happened
                # (e.g. an ambiguous navigation is NOT shown as a success).
                payload = {"type": "TOOL_CALL_RESULT", "tool_call_id": call_id, "outcome": outcome}
                if tool == "navigate" and outcome != "ok":
                    cands = _nav_candidates(result)
                    if cands:
                        payload["candidates"] = cands
                self._enqueue_sse(payload)
                self._enqueue(ToolCallEndEvent(tool_call_id=call_id))
            _trace("agent.tool_end", session_id=self._session_id, run_id=self._run_id, tool=tool, call_id=call_id, success=getattr(data, "success", None), outcome=outcome)

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
            self._enqueue(RunFinishedEvent(thread_id=self._thread_id, run_id=self._run_id))
            self._finish()

    def set_user(self, user_id: str | None) -> None:
        """Bind the signed-in user for subsequent turns (tools read it via closure)."""
        self._user_id = user_id

    async def send(self, prompt: str) -> AsyncGenerator[str, None]:
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
