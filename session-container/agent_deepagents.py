"""Standalone LangGraph **Deep Agents** backend for the Personal Assistant session container.

This is a drop-in alternative to `agent.AgentSession` (which wraps the GitHub
Copilot SDK). It exposes the *identical* interface that `server.py` depends on —
constructor `(working_dir, token=, session_id=)`, `__aenter__`/`__aexit__`,
the `.token` and `.raw_sdk_log_path` properties, and an async `send(prompt)`
generator that yields already-formatted **AG-UI SSE strings** — but runs the turn
on a LangChain/LangGraph "deep agent" (`deepagents.create_deep_agent`) against
Azure OpenAI instead of the Copilot SDK.

Design notes (see review/ findings doc for the full comparison):
- **Standalone by choice.** This module shares only `appdb` (the system of record)
  and the `ag_ui` event protocol with the Copilot path. The Personal Assistant tools and system
  prompt are ported here as native LangChain tools so the two backends never
  couple. The cost is duplicated tool logic; the benefit is a clean, independent
  implementation that could run with the Copilot SDK uninstalled.
- **"Don't over-plan" parity.** The deep-agent harness ships planning (`write_todos`),
  a scratch filesystem (`ls`/`read_file`/`write_file`/…), subagents (`task`) and
  shell (`execute`). Personal Assistant is deliberately a one-direct-tool-call app, so every
  built-in tool is hidden from the model via `_ToolExclusionMiddleware`. The model
  sees ONLY the 14 Personal Assistant tools — identical surface to the Copilot agent.
- **Tool-name fidelity.** The frontend keys off exact tool *and* arg names
  (`write_file`/`p.path`, `navigate`/`p.destination`, …). A user tool named
  `write_file` shadows the built-in of the same name (verified: user `tools=` win
  the name dedupe), so naming is preserved.
- **Skills.** The four markdown skills are inlined into the system prompt for the
  POC (deepagents has a native `SkillsMiddleware`, noted as the production path).
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
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from deepagents import create_deep_agent
from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

import appdb

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
# its model-visible tools by name is enough — and `write_file` is intentionally
# left out of this set so our own `write_file` keeps that name.)
_EXCLUDED_BUILTINS = frozenset(
    {"write_todos", "task", "execute", "ls", "read_file", "edit_file", "glob", "grep"}
)


# ───────────────────────── System prompt (ported + skills inlined) ──────────

_BASE_PROMPT = """\
You are the assistant embedded in Personal Assistant — a personal-productivity and engagement
workspace for managing **tasks**, a **calendar**, **documents**, and shared customer
**engagements**. The app has these pages: Home (today's agenda — what's due, what's overdue,
the next events), To-Do (tasks grouped into buckets, each with a status, priority, group,
optional due date, and subtasks), Calendar (events — meetings, reminders, focus blocks — by
day), Documents (notes and drafts you read and write), and Engagements (the team's shared
customer engagements — stage, health, milestones, risks, actions). You help by acting
directly on the app through tools.

You operate inside the user's own session. The tools you call read and mutate the
*real* application state, and the user sees the result in the app next to this chat.
Only claim you did something after the tool that does it has returned successfully —
never say a record was created/updated/deleted or that you navigated unless the tool call succeeded.

How you work:
- Read the request, then take the single most direct action. Do not over-plan.
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
- Engagements are **shared with the whole team** (unlike personal tasks): `list_engagements`
  reviews health at a glance; `create_engagement` starts one; `update_engagement` changes
  title/customer/stage/dates/notes; `set_engagement_health` sets green/amber/red — amber and
  red REQUIRE a `note` saying why, so ask for the reason if the user didn't give one;
  `add_engagement_item` / `update_engagement_item` manage milestones, risks, and actions
  (`kind` = 'milestone' | 'risk' | 'action'). For engagement status questions, answer from
  `list_engagements` — never from memory.
- For "what's overdue", use the `overdue` flag from `list_tasks` and the "[Today: …]"
  context — never judge dates yourself.
- To write or revise a document (a brief, notes, a summary), use `write_file` — it appears
  in Documents and opens in the artifact canvas, where the user can edit it. To read an
  existing document first, use `list_documents` then `read_workspace_file`.
- For "what did I decide about X", "find … in my notes", "search the docs/library", or any
  question that needs grounding across the document library, use `search_documents` — it
  returns the most relevant passages with their source filenames. Answer **only** from the
  returned passages and cite the source filename(s). If it returns NO_RESULTS, say nothing
  matched; if it returns SEARCH_NOT_CONFIGURED or SEARCH_FAILED, tell the user document
  search is unavailable — never make up an answer.

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

## Playbooks (domain detail)

### Tasks
- Statuses are exactly: "To do", "In progress", "Blocked", "Done". A "Done" task is complete
  and never overdue. Priorities are exactly: "Low", "Medium", "High". Map the user's phrasing
  to these values.
- For updates/deletes/subtask adds: if the tool returns AMBIGUOUS, list the candidates and
  ask which task. If TASK_NOT_FOUND, say so — don't invent one.

### Calendar
- Dates are YYYY-MM-DD; times are 24-hour HH:MM. Resolve relative words ("today", "tomorrow",
  "Thursday") against the "[Today: …]" context — never guess the current date.
- If create_event returns DATE_REQUIRED, ask for the date. Tasks with due dates also appear on
  the Calendar surface.

### Documents
- Discover → read → answer: `list_documents` first, then `read_workspace_file`, then answer
  strictly from what you read. For "draft/write/summarize", `write_file` a markdown artifact
  with a clear title and headings; ground any summary in the document you actually read.

### Research (search)
- Call `search_documents(query)` with the user's question; it returns passages each prefixed
  `source: <filename>`. Answer ONLY from them and cite the source filename(s). Never fabricate
  on NO_RESULTS / SEARCH_NOT_CONFIGURED / SEARCH_FAILED — say plainly that search is
  unavailable or nothing matched.
"""

SYSTEM_PROMPT = _BASE_PROMPT


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


def _result_text(result) -> str:
    """Extract a tool's returned text from a str / dict / ToolMessage-like object."""
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
_ERROR_MARKERS = {"INVALID_PATH", "FILE_NOT_FOUND", "BINARY_FILE_UNSUPPORTED", "PATH_REQUIRED", "ENCODING_UNSUPPORTED", "TITLE_REQUIRED", "TEXT_REQUIRED", "DATE_REQUIRED", "SEARCH_NOT_CONFIGURED", "SEARCH_FAILED", "QUERY_REQUIRED"}


def _tool_outcome(result, success) -> str:
    """Classify a tool result as ok | noop | error from its leading status marker."""
    text = _result_text(result).strip()
    head = text.split(None, 1)[0].rstrip(":") if text else ""
    if head in _NOOP_MARKERS:
        return "noop"
    if head in _ERROR_MARKERS or head.endswith("NOT_FOUND"):
        return "error"
    if success is False:
        return "error"
    if not text:
        return "error"
    return "ok"


def _nav_candidates(result) -> list[str]:
    text = _result_text(result)
    marker = "destinations: " if "destinations: " in text else ("options: " if "options: " in text else None)
    if not marker:
        return []
    tail = text.split(marker, 1)[1]
    tail = tail.split(". ", 1)[0].rstrip(".")
    parts = [p.strip() for p in tail.split(";") if p.strip()]
    return [p for p in parts if p and not p.lower().startswith("ask ")][:6]


def _path_within_workspace(workspace: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(workspace)
        return True
    except ValueError:
        return False


_SEARCH_INDEX_NAME = "flow-documents-index"
_SEARCH_SEMANTIC_CONFIG = "flow-semantic"
_SEARCH_API_VERSION = "2024-07-01"


def _search_documents_query(query: str, top: int = 4) -> str:
    import httpx

    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_KEY")
    if not endpoint or not key:
        return (
            "SEARCH_NOT_CONFIGURED: document search is unavailable because Azure AI Search "
            "is not configured (missing AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY)."
        )
    url = endpoint.rstrip("/") + f"/indexes/{_SEARCH_INDEX_NAME}/docs/search"
    body = {
        "search": query,
        "top": top,
        "select": "filename,title,chunk",
        "queryType": "semantic",
        "semanticConfiguration": _SEARCH_SEMANTIC_CONFIG,
    }
    try:
        resp = httpx.post(
            url,
            params={"api-version": _SEARCH_API_VERSION},
            headers={"api-key": key, "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
    except httpx.HTTPError as exc:
        return f"SEARCH_FAILED: could not reach Azure AI Search ({exc})."
    if resp.status_code != 200:
        return f"SEARCH_FAILED: Azure AI Search returned {resp.status_code}: {resp.text[:200]}"
    results = resp.json().get("value", [])
    if not results:
        return f"NO_RESULTS: nothing in the document library matched '{query}'."
    lines = [f"PASSAGES for '{query}' ({len(results)} from the document library):"]
    for r in results:
        snippet = " ".join((r.get("chunk") or "").split())
        lines.append(f"- source: {r.get('filename')}\n  {snippet}")
    return "\n".join(lines)


def _normalize_workspace_text(text: str) -> str:
    text = _re.sub(r"<!--\s*Page(?:Header|Footer|Break|Number)[^>]*-->", "", text, flags=_re.IGNORECASE)
    text = _re.sub(r"!\[[^\]]*]\([^)]+\)", "", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


# ───────────────────────── Personal Assistant tools as LangChain tools ────────────────────

def _build_langchain_tools(working_dir: str) -> list:
    """Port of agent._build_flow_tools as native LangChain tools (same names, args,
    marker-string returns, and behavior). Closures over the session workspace."""
    workspace_root = Path(working_dir).resolve()

    def _load() -> dict:
        return appdb.load()

    def _save(data: dict) -> None:
        appdb.save(data)

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

    @tool("navigate", description="Navigate the Personal Assistant app to a page, a task, a calendar event, or an engagement.")
    def navigate(destination: str) -> str:
        data = _load()
        result = appdb.resolve_destination(data, destination, appdb.list_engagements())
        if result["status"] == "resolved":
            data["currentRoute"] = result["path"]
            _save(data)
            return f"NAVIGATED to {result['title']} ({result['path']})"
        if result["status"] == "ambiguous":
            opts = "; ".join(c["title"] for c in result["candidates"])
            return f"AMBIGUOUS: '{destination}' matches multiple destinations: {opts}. Ask the user which one."
        opts = "; ".join(c["title"] for c in result["candidates"])
        return f"NOT_FOUND: no destination matched '{destination}'. Closest options: {opts}."

    @tool("list_tasks", description="List the tasks with their status, priority, group, due date, a computed overdue flag, and subtask progress.")
    def list_tasks() -> str:
        data = _load()
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

    @tool("create_task", description="Create a task in the to-do list.")
    def create_task(title: str, status: str = "", priority: str = "", group: str = "", due_date: str = "") -> str:
        if not title.strip():
            return "TITLE_REQUIRED: a task needs a title."
        data = _load()
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
        _save(data)
        return (
            f"CREATED task [{task['id']}] '{task['title']}', status {task['status']}, "
            f"priority {task['priority']}, group {task['group']}, due {task['dueDate'] or 'n/a'}."
        )

    @tool("update_task", description="Update a task's status, priority, group, or due date.")
    def update_task(task: str, status: str = "", priority: str = "", group: str = "", due_date: str = "") -> str:
        data = _load()
        t, err = _resolve_task_strict(data, task)
        if err:
            return err
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
            return "NO_CHANGES: specify a status, priority, group, or due_date to update."
        data["currentRoute"] = appdb.task_route(t["id"])
        _save(data)
        return f"UPDATED task [{t['id']}] '{t['title']}': {', '.join(changed)}."

    @tool("delete_task", description="Delete a task from the to-do list.")
    def delete_task(task: str) -> str:
        data = _load()
        t, err = _resolve_task_strict(data, task)
        if err:
            return err
        data["tasks"] = [x for x in data["tasks"] if x["id"] != t["id"]]
        data["currentRoute"] = "/todo"
        _save(data)
        return f"DELETED task [{t['id']}] '{t['title']}'."

    @tool("add_subtask", description="Add a subtask to a task.")
    def add_subtask(task: str, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "TEXT_REQUIRED: provide the subtask text."
        data = _load()
        t, err = _resolve_task_strict(data, task)
        if err:
            return err
        t.setdefault("subtasks", []).append({"text": text, "done": False})
        data["currentRoute"] = appdb.task_route(t["id"])
        _save(data)
        return f"ADDED subtask to '{t['title']}': {text}."

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
        data = _load()
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
        _save(data)
        when = event["start"] or "all-day"
        if event["start"] and event["end"]:
            when = f"{event['start']}-{event['end']}"
        return f"CREATED event [{event['id']}] '{event['title']}' ({event['type']}) on {event['date']} at {when}."

    @tool("update_event", description="Update or move a calendar event's title, date, time, or type.")
    def update_event(event: str, title: str = "", date: str = "", start: str = "", end: str = "", type: str = "") -> str:
        data = _load()
        e, err = _resolve_event_strict(data, event)
        if err:
            return err
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
            return "NO_CHANGES: specify a title, date, start, end, or type to update."
        data["currentRoute"] = appdb.event_route(e["id"])
        _save(data)
        return f"UPDATED event [{e['id']}] '{e['title']}': {', '.join(changed)}."

    @tool("delete_event", description="Delete a calendar event.")
    def delete_event(event: str) -> str:
        data = _load()
        e, err = _resolve_event_strict(data, event)
        if err:
            return err
        data["events"] = [x for x in data["events"] if x["id"] != e["id"]]
        data["currentRoute"] = "/calendar"
        _save(data)
        return f"DELETED event [{e['id']}] '{e['title']}'."

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

    @tool("search_documents", description="Semantic search over the indexed document library (meeting notes, briefs, references). Returns the top matching passages, each with its source filename. Use to answer 'what did I decide about X', 'find … in my notes', or 'search the docs'.")
    def search_documents(query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "QUERY_REQUIRED: provide what to search for."
        return _search_documents_query(query)

    # ── Engagement tools (shared scope — separate Cosmos docs, see appdb) ────
    # Engagement writes go through appdb.create/update/delete_engagement, which are
    # ETag-safe by construction — the deep-agents last-write-wins `_save` shortcut
    # never touches them. Only the cosmetic currentRoute follow-up uses _load/_save.

    def _set_route(path: str) -> None:
        data = _load()
        data["currentRoute"] = path
        _save(data)

    def _resolve_engagement_strict(ref: str):
        r = (ref or "").strip().lower()
        if not r:
            return None, "ENGAGEMENT_REQUIRED: say which engagement."
        engs = appdb.list_engagements()
        exact = [g for g in engs if g["id"].lower() == r or g["title"].lower() == r]
        matches = exact if exact else [g for g in engs if r in g["title"].lower()]
        if not matches:
            return None, f"ENGAGEMENT_NOT_FOUND: '{ref}'."
        if len(matches) > 1:
            opts = "; ".join(f"[{g['id']}] {g['title']}" for g in matches)
            return None, f"AMBIGUOUS engagement '{ref}': {opts}. Ask which one."
        return matches[0], None

    def _normalize_kind(kind: str):
        k = (kind or "").strip().lower()
        if k.endswith("s") and k[:-1] in appdb.ENGAGEMENT_ITEM_KINDS:
            k = k[:-1]
        if k not in appdb.ENGAGEMENT_ITEM_KINDS:
            return None, "INVALID_KIND: kind must be 'milestone', 'risk', or 'action'."
        return k, None

    @tool("list_engagements", description="List the team's shared customer engagements: stage, health (with the why), milestone progress, open risks and actions.")
    def list_engagements() -> str:
        engs = appdb.list_engagements()
        if not engs:
            return "No engagements yet."
        lines = [f"{len(engs)} engagement(s):"]
        for g in engs:
            ms = g["milestones"]
            done = sum(1 for m in ms if m.get("status") == "Done")
            open_risks = sum(1 for r in g["risks"] if r.get("status") != "Closed")
            open_actions = sum(1 for a in g["actions"] if a.get("status") != "Done")
            why = f" ({g['healthNote']})" if g.get("healthNote") else ""
            lines.append(
                f"- [{g['id']}] {g['title']} | customer={g['customer'] or 'n/a'} | stage={g['stage']} | "
                f"health={g['health']}{why} | milestones={done}/{len(ms)} | open risks={open_risks} | "
                f"open actions={open_actions} | target={g['targetDate'] or 'n/a'}"
            )
        return "\n".join(lines)

    @tool("create_engagement", description="Create a shared customer engagement (visible to the whole team).")
    def create_engagement(title: str, customer: str = "", stage: str = "", target_date: str = "", notes: str = "") -> str:
        if not title.strip():
            return "TITLE_REQUIRED: an engagement needs a title."
        stage = stage.strip() or appdb.ENGAGEMENT_STAGES[0]
        if stage not in appdb.ENGAGEMENT_STAGES:
            return f"INVALID_STAGE: stage must be one of {', '.join(appdb.ENGAGEMENT_STAGES)}."
        eng = appdb.create_engagement(title=title, customer=customer, stage=stage,
                                      target_date=target_date, notes=notes)
        _set_route(appdb.engagement_route(eng["id"]))
        return (
            f"CREATED engagement [{eng['id']}] '{eng['title']}' | customer={eng['customer'] or 'n/a'} | "
            f"stage={eng['stage']} | health={eng['health']} | target={eng['targetDate'] or 'n/a'}."
        )

    @tool("update_engagement", description="Update an engagement's title, customer, stage, dates, or notes.")
    def update_engagement(engagement: str, title: str = "", customer: str = "", stage: str = "",
                          start_date: str = "", target_date: str = "", notes: str = "") -> str:
        if stage.strip() and stage.strip() not in appdb.ENGAGEMENT_STAGES:
            return f"INVALID_STAGE: stage must be one of {', '.join(appdb.ENGAGEMENT_STAGES)}."
        eng, err = _resolve_engagement_strict(engagement)
        if err:
            return err
        def _mut(g):
            changed = []
            for field, value in (("title", title), ("customer", customer), ("stage", stage),
                                 ("startDate", start_date), ("targetDate", target_date), ("notes", notes)):
                if value.strip():
                    g[field] = value.strip()
                    changed.append(f"{field}={g[field]}")
            if not changed:
                raise appdb.AbortWrite("NO_CHANGES: specify a title, customer, stage, start_date, target_date, or notes to update.")
            return f"UPDATED engagement [{g['id']}] '{g['title']}': {', '.join(changed)}."
        try:
            result = appdb.update_engagement(eng["id"], _mut)
        except KeyError:
            return f"ENGAGEMENT_NOT_FOUND: '{engagement}'."
        _set_route(appdb.engagement_route(eng["id"]))
        return result

    @tool("delete_engagement", description="Delete an engagement and everything in it (milestones, risks, actions).")
    def delete_engagement(engagement: str) -> str:
        eng, err = _resolve_engagement_strict(engagement)
        if err:
            return err
        if not appdb.delete_engagement(eng["id"]):
            return f"ENGAGEMENT_NOT_FOUND: '{engagement}'."
        _set_route("/engagements")
        return f"DELETED engagement [{eng['id']}] '{eng['title']}'."

    @tool("set_engagement_health", description="Set an engagement's health (green/amber/red). Amber and red REQUIRE a note saying why.")
    def set_engagement_health(engagement: str, health: str, note: str = "") -> str:
        h = health.strip().lower()
        if h not in appdb.HEALTH_LEVELS:
            return f"INVALID_HEALTH: health must be one of {', '.join(appdb.HEALTH_LEVELS)}."
        note = note.strip()
        if h in ("amber", "red") and not note:
            return "NOTE_REQUIRED: amber/red health needs a why — pass `note` (a red with no reason is noise)."
        eng, err = _resolve_engagement_strict(engagement)
        if err:
            return err
        def _mut(g):
            if g["health"] == h and (not note or g["healthNote"] == note):
                raise appdb.AbortWrite(f"NO_CHANGES: engagement [{g['id']}] health is already {h}.")
            g["health"] = h
            g["healthNote"] = note  # green with no note clears the stale why
            why = f" — {note}" if note else ""
            return f"UPDATED engagement [{g['id']}] '{g['title']}' health={h}{why}."
        try:
            result = appdb.update_engagement(eng["id"], _mut)
        except KeyError:
            return f"ENGAGEMENT_NOT_FOUND: '{engagement}'."
        _set_route(appdb.engagement_route(eng["id"]))
        return result

    @tool("add_engagement_item", description="Add a milestone, risk, or action to an engagement (kind = 'milestone' | 'risk' | 'action').")
    def add_engagement_item(engagement: str, kind: str, title: str, due_date: str = "",
                            severity: str = "", owner: str = "", notes: str = "") -> str:
        k, err = _normalize_kind(kind)
        if err:
            return err
        if not title.strip():
            return f"TITLE_REQUIRED: a {k} needs a title."
        sev = severity.strip() or "Medium"
        if k == "risk" and sev not in appdb.RISK_SEVERITIES:
            return f"INVALID_SEVERITY: severity must be one of {', '.join(appdb.RISK_SEVERITIES)}."
        eng, err = _resolve_engagement_strict(engagement)
        if err:
            return err
        field, prefix = appdb.ENGAGEMENT_ITEM_KINDS[k]
        def _mut(g):
            items = g[field]
            item = {"id": appdb.new_id(prefix, items), "title": title.strip()}
            if k == "milestone":
                item.update({"dueDate": due_date.strip(), "status": "Planned", "notes": notes.strip()})
            elif k == "risk":
                item.update({"severity": sev, "status": "Open", "mitigation": notes.strip(),
                             "owner": owner.strip()})
            else:  # action
                item.update({"owner": owner.strip(), "dueDate": due_date.strip(), "status": "Open",
                             "notes": notes.strip()})
            items.append(item)
            return f"CREATED {k} [{item['id']}] '{item['title']}' on engagement [{g['id']}] '{g['title']}'."
        try:
            result = appdb.update_engagement(eng["id"], _mut)
        except KeyError:
            return f"ENGAGEMENT_NOT_FOUND: '{engagement}'."
        _set_route(appdb.engagement_route(eng["id"]))
        return result

    @tool("update_engagement_item", description="Update a milestone, risk, or action on an engagement — status, title, severity, owner, due date, or notes.")
    def update_engagement_item(engagement: str, kind: str, item: str, title: str = "",
                               status: str = "", severity: str = "", due_date: str = "",
                               owner: str = "", notes: str = "") -> str:
        k, err = _normalize_kind(kind)
        if err:
            return err
        status = status.strip()
        valid_statuses = {"milestone": appdb.MILESTONE_STATUSES, "risk": appdb.RISK_STATUSES,
                          "action": appdb.ACTION_STATUSES}[k]
        if status and status not in valid_statuses:
            return f"INVALID_STATUS: a {k} status must be one of {', '.join(valid_statuses)}."
        severity = severity.strip()
        if severity and (k != "risk" or severity not in appdb.RISK_SEVERITIES):
            return f"INVALID_SEVERITY: severity applies to risks and must be one of {', '.join(appdb.RISK_SEVERITIES)}."
        eng, err = _resolve_engagement_strict(engagement)
        if err:
            return err
        notes_field = "mitigation" if k == "risk" else "notes"
        def _mut(g):
            it = appdb.find_engagement_item(g, k, item)
            if it is None:
                raise appdb.AbortWrite(f"ITEM_NOT_FOUND: no {k} matches '{item}' on engagement [{g['id']}].")
            changed = []
            for field, value in (("title", title), ("status", status), ("severity", severity),
                                 ("owner", owner), ("dueDate", due_date), (notes_field, notes)):
                if value.strip():
                    it[field] = value.strip()
                    changed.append(f"{field}={it[field]}")
            if not changed:
                raise appdb.AbortWrite("NO_CHANGES: specify a title, status, severity, owner, due_date, or notes to update.")
            return f"UPDATED {k} [{it['id']}] '{it['title']}' on [{g['id']}]: {', '.join(changed)}."
        try:
            result = appdb.update_engagement(eng["id"], _mut)
        except KeyError:
            return f"ENGAGEMENT_NOT_FOUND: '{engagement}'."
        _set_route(appdb.engagement_route(eng["id"]))
        return result

    return [
        navigate,
        list_tasks, create_task, update_task, delete_task, add_subtask,
        list_events, create_event, update_event, delete_event,
        list_documents, read_workspace_file, write_file,
        search_documents,
        list_engagements, create_engagement, update_engagement, delete_engagement,
        set_engagement_health, add_engagement_item, update_engagement_item,
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

    def __init__(self, working_dir: str, token: str | None = None, session_id: str = "default"):
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

        tools = _build_langchain_tools(self._working_dir)
        self._tool_names = {t.name for t in tools}
        self._checkpointer = InMemorySaver()
        self._agent = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
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

    async def send(self, prompt: str) -> AsyncGenerator[str, None]:
        """Run a deep-agent turn; yield SSE-formatted AG-UI events until completion."""
        self._run_id = str(uuid.uuid4())
        self._status = "thinking"
        self._turn_active = True

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
                        continue
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
                        continue
                    self._status = "thinking"
                    tools_called += 1
                    result = (ev.get("data") or {}).get("output")
                    outcome = _tool_outcome(result, None)
                    payload = {"type": "TOOL_CALL_RESULT", "tool_call_id": call_id, "outcome": outcome}
                    if name == "navigate" and outcome != "ok":
                        cands = _nav_candidates(result)
                        if cands:
                            payload["candidates"] = cands
                    yield f"data: {_json.dumps(payload)}\n\n"
                    yield _sse_event(ToolCallEndEvent(tool_call_id=call_id))
                    _trace("agent.tool_end", session_id=self._session_id, run_id=self._run_id, tool=name, call_id=call_id, outcome=outcome)

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
            yield _sse_event(RunFinishedEvent(thread_id=self._thread_id, run_id=self._run_id))
        finally:
            self._turn_active = False
            self._write_raw_sdk_record({"kind": "turn_finalized", "run_id": self._run_id, "status": self._status})
