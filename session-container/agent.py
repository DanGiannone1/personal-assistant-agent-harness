"""AgentSession wrapping the GitHub Copilot SDK (1.0.x) with an event queue.

Provides a streaming async generator interface for running agent turns against
Azure OpenAI. Translates SDK session events into AG-UI protocol events.

Local portability check for the primary Deep Agents adapter: it exposes the
same seven model-visible product tools over the shared workbench_core
Engagement service (durable state lives in Cosmos via appdb.py) and the same
`AgentSession` seam that server.py depends on.
"""

import asyncio
import json as _json
import logging as _logging
import os
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
import navsvc
from workbench_core import EngagementService, ProductToolResult, engagement_product_result
from workbench_core.appdb_repository import AppdbEngagementRepository
from workbench_core.trace_logging import trace_event
from mvp_tool_schemas import (
    CreateEngagementCommand, GetEngagementCommand, ListEngagementsCommand, NavigateCommand,
    SetEngagementStatusCommand, ShareEngagementCommand, UpdateEngagementCommand,
)

load_dotenv()

_LOG = os.getenv("LOG_AGENT_EVENTS", "").lower() == "true"
_logger = _logging.getLogger("agent.events")


def _log_event(msg: str) -> None:
    if _LOG:
        _logger.info(msg)


def _trace(event: str, **data) -> None:
    trace_event("session", event, **data)


SYSTEM_PROMPT = """\
You are the CSA Workbench assistant for shared Engagements. Use only these tools:
`navigate`, `list_engagements`, `create_engagement`, `get_engagement`,
`update_engagement`, `set_engagement_status`, and `share_engagement`.

Navigation accepts only these destination IDs: `engagements`, `engagement_overview`,
`engagement_tasks`, and `engagement_artifacts`. For an Engagement destination,
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


def _safe_error_message(error: object) -> str:
    """Map provider failures to fixed browser-safe messages."""
    message = str(error).lower()
    if "too many requests" in message or "429" in message or "rate limit" in message:
        return "The AI service is temporarily rate-limited. Please wait 30–60 seconds and try again."
    if any(marker in message for marker in ("content management policy", "content_filter", "responsible ai", "filtered")):
        return "I can't act on that request — it was flagged by the safety filter. I won't take actions that try to override my guardrails or operate outside your workspace."
    return "The assistant could not complete that request. Please retry."


# ── Tool builders (closures over the session workspace) ─────────────────────


def _build_flow_tools(working_dir: str, user_id: str) -> list:
    """Build the seven model-visible product tools as native Copilot tools.

    Same names, schemas, authorization, and typed-result envelopes as the Deep
    Agents adapter (proven by tests/test_structured_control.py). Closures bind
    the actor and session; the model can never pass either as an argument.
    """
    engagement_service = EngagementService(AppdbEngagementRepository(appdb), appdb.find_user)

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

    def _tool_result(result: ProductToolResult, text: str) -> ToolResult:
        return ToolResult(text_result_for_llm=text, tool_telemetry={"product_result": result.to_dict()})

    @define_tool(name="navigate", description="Navigate to an explicit CSA Workbench catalog destination.")
    def navigate(params: NavigateCommand) -> ToolResult:
        result = navsvc.destination_for(user_id, params.destination_id, params.engagement_id)
        return _tool_result(result, result.message or "Navigation request processed.")

    @define_tool(name="list_engagements", description="List the shared engagements the user belongs to, including their stable IDs.")
    def list_engagements(params: ListEngagementsCommand) -> ToolResult:
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
    def create_engagement(params: CreateEngagementCommand) -> ToolResult:
        outcome = engagement_service.create(user_id, {"name": params.name, "description": params.description,
                                                       "customer": params.customer, "targetDate": params.target_date})
        result = engagement_product_result(outcome)
        text = f"Engagement [{outcome.record['id']}] is available." if outcome.record else result.message
        return _tool_result(result, text)

    @define_tool(name="get_engagement", description="Read one visible engagement by stable ID.")
    def get_engagement(params: GetEngagementCommand) -> ToolResult:
        outcome = engagement_service.get(user_id, params.engagement_id)
        result = engagement_product_result(outcome)
        text = _engagement_detail_text(outcome.record) if outcome.record else result.message
        return _tool_result(result, text)

    @define_tool(name="update_engagement", description="Update description, customer, or dates as an editor/owner; changing name requires owner access. Omit fields to leave them unchanged; empty optional fields clear them.")
    def update_engagement(params: UpdateEngagementCommand) -> ToolResult:
        values = {key: value for key, value in (("name", params.name), ("description", params.description),
                  ("customer", params.customer), ("startDate", params.start_date), ("targetDate", params.target_date)) if value is not None}
        outcome = engagement_service.update(user_id, params.engagement_id, values)
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement update processed." if outcome.status == "committed" else result.message)

    @define_tool(name="set_engagement_status", description="Set an engagement's status (green/yellow/red). Yellow and red REQUIRE a note saying why — ask the user for the reason if they didn't give one. Requires editor access.")
    def set_engagement_status(params: SetEngagementStatusCommand) -> ToolResult:
        outcome = engagement_service.update(user_id, params.engagement_id, {"status": params.status, "statusNote": params.note})
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement status processed." if outcome.status == "committed" else result.message)

    @define_tool(name="share_engagement", description="Share a engagement with another user (grant viewer, editor, or owner access). Only a engagement owner can share.")
    def share_engagement(params: ShareEngagementCommand) -> ToolResult:
        outcome = engagement_service.share(user_id, params.engagement_id, params.user, params.role)
        result = engagement_product_result(outcome)
        return _tool_result(result, "Engagement sharing processed." if outcome.status == "committed" else result.message)

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
            msg = _safe_error_message(getattr(data, "message", None) or "")
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
