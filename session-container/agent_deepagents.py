"""Standalone LangGraph **Deep Agents** backend for the Personal Assistant session container.

This is a drop-in alternative to `agent.AgentSession` (which wraps the GitHub
Copilot SDK). It exposes the *identical* interface that `server.py` depends on —
constructor `(working_dir, token=, session_id=)`, `__aenter__`/`__aexit__`,
the `.token` and `.raw_sdk_log_path` properties, and an async `send(prompt)`
generator that yields already-formatted **AG-UI SSE strings** — but runs the turn
on a LangChain/LangGraph "deep agent" (`deepagents.create_deep_agent`) against
Azure OpenAI instead of the Copilot SDK.

Design notes (see review/ findings doc for the full comparison):
- **Standalone by choice.** This module shares `appdb` (the system of record),
  `library` (the RAG Library store), and the `ag_ui` event protocol with the Copilot
  path. The Personal Assistant tools and system
  prompt are ported here as native LangChain tools so the two backends never
  couple. The cost is duplicated tool logic; the benefit is a clean, independent
  implementation that could run with the Copilot SDK uninstalled.
- **"Don't over-plan" parity.** The deep-agent harness ships planning (`write_todos`),
  a scratch filesystem (`ls`/`read_file`/`write_file`/…), subagents (`task`) and
  shell (`execute`). Personal Assistant is deliberately a one-direct-tool-call app, so every
  built-in tool is hidden from the model via `_ToolExclusionMiddleware`. The model
  sees ONLY the 22 Personal Assistant tools — identical surface to the Copilot agent.
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
import library

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
_ERROR_MARKERS = {"INVALID_PATH", "FILE_NOT_FOUND", "BINARY_FILE_UNSUPPORTED", "PATH_REQUIRED", "ENCODING_UNSUPPORTED", "TITLE_REQUIRED", "TEXT_REQUIRED", "DATE_REQUIRED", "SEARCH_NOT_CONFIGURED", "SEARCH_FAILED", "QUERY_REQUIRED", "LIBRARY_FAILED", "FILENAME_REQUIRED", "UNSUPPORTED"}


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


def _nav_candidates(result) -> list[dict]:
    """Pull FULLY-BOUND candidates ({title, path}) from a navigate result's CHIPS line —
    picker chips (ambiguous/not-found) and escape-hatch chips (decided-with-alternates)
    both ride this channel; a chip click is a plain manual nav, no second resolution."""
    text = _result_text(result)
    if "\nCHIPS: " not in text:
        return []
    tail = text.rsplit("\nCHIPS: ", 1)[1].strip()
    chips = []
    for part in tail.split(";"):
        title, _, path = part.strip().partition("|")
        if title and path.startswith("/"):
            chips.append({"title": title, "path": path})
    return chips[:6]


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

    @tool("navigate", description="Navigate the Personal Assistant app to a page, a task, or a calendar event.")
    def navigate(destination: str) -> str:
        data = _load()
        result = appdb.resolve_destination(data, destination)
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

    return [
        navigate,
        list_tasks, create_task, update_task, delete_task, add_subtask,
        list_events, create_event, update_event, delete_event,
        list_documents, read_workspace_file, write_file,
        search_documents,
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
