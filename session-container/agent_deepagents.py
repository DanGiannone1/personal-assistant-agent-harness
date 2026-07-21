"""Standalone LangGraph **Deep Agents** backend for the CSA Workbench session container.

This is a drop-in alternative to `agent.AgentSession` (which wraps the GitHub
Copilot SDK). It exposes the *identical* interface that `server.py` depends on —
constructor `(working_dir, token=, session_id=)`, `__aenter__`/`__aexit__`,
the `.token` and `.raw_sdk_log_path` properties, and an async `send(prompt)`
generator that yields already-formatted **AG-UI SSE strings** — but runs the turn
on a LangChain/LangGraph "deep agent" (`deepagents.create_deep_agent`) against
Azure OpenAI instead of the Copilot SDK.

Design notes:
- **Standalone by choice.** This module shares only `appdb`/`navsvc`, the shared
  `workbench_core` Engagement service, and the `ag_ui` event protocol with the
  Copilot path. The product tools and system prompt are implemented here as
  native LangChain tools so the two backends never couple; either can run with
  the other's SDK uninstalled.
- **MVP product tools.** The model sees the seven contract tools shared with the
  Copilot backend: list/get/create/update/status/share engagements and navigate.
  Their public names, arguments, authorization, and result envelopes remain the
  customer-facing contract.
- **One internal skill loader.** Deep Agents' native `read_file` is retained only
  for progressive disclosure of the approved product skill. Its virtual backend
  and deny-by-default permissions expose exactly one `SKILL.md`; loader events
  stay out of the public AG-UI stream and are recorded only in raw eval evidence.
  Planning, writes, shell, subagents, and every other built-in are excluded.
"""

import json as _json
import logging as _logging
import os
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
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from deepagents import create_deep_agent
from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware

import appdb
import navsvc
from workbench_core import EngagementService, ProductToolResult, engagement_product_result
from workbench_core.appdb_repository import AppdbEngagementRepository
from workbench_core.trace_logging import trace_event
from mvp_tool_schemas import (
    CreateEngagementCommand, GetEngagementCommand, ListEngagementsCommand, NavigateCommand,
    SetEngagementStatusCommand, ShareEngagementCommand, UpdateEngagementCommand,
)
from skill_runtime import (
    INTERNAL_SKILL_TOOLS,
    deepagents_skill_config,
    skill_identity,
    skill_name_for_read,
)

load_dotenv()

_logger = _logging.getLogger("agent.deepagents")


def _trace(event: str, **data) -> None:
    trace_event("session", event, **data)


# Built-in deep-agent tools hidden from the model so the agent behaves like the
# Copilot one: direct single-tool actions, no planning / scratch-FS / subagents.
# (FilesystemMiddleware itself is protected and cannot be removed, but stripping
# every supplied model-visible tool by name leaves the approved product inventory.)
_EXCLUDED_BUILTINS = frozenset(
    {"write_todos", "task", "execute", "ls", "write_file", "edit_file", "glob", "grep"}
)


# ───────────────────────── System prompt (mirrors agent.py) ─────────────────

SYSTEM_PROMPT = """\
You are the CSA Workbench assistant for shared Engagements. For product operations, use only:
`navigate`, `list_engagements`, `create_engagement`, `get_engagement`,
`update_engagement`, `set_engagement_status`, and `share_engagement`.
You may use the internal `read_file` loader only to load an available product skill when its
description matches the user's request. It is not a product action and must not replace a typed
product tool.

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


def _model_visible_text(result) -> str:
    """Capture exactly the content returned to the model for eval-only raw evidence."""
    content = getattr(result, "content", None)
    if content is None and isinstance(result, tuple) and result:
        content = result[0]
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    try:
        return _json.dumps(_jsonable(content), sort_keys=True)
    except Exception:
        return str(content)


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


def _safe_error_message(error: object) -> str:
    """Map provider failures to fixed browser-safe messages."""
    message = str(error).lower()
    if "too many requests" in message or "429" in message or "rate limit" in message:
        return "The AI service is temporarily rate-limited. Please wait 30–60 seconds and try again."
    if any(marker in message for marker in ("content_filter", "content management policy", "responsible ai", "filtered")):
        return "I can't act on that request — it was flagged by the safety filter. I won't take actions that try to override my guardrails or operate outside your workspace."
    return "The assistant could not complete that request. Please retry."


# ───────────────────────── CSA Workbench tools as LangChain tools ─────────────────────────

def _build_langchain_tools(working_dir: str, user_id: str) -> list:
    engagement_service = EngagementService(AppdbEngagementRepository(appdb), appdb.find_user)
    """Port of agent._build_flow_tools as native LangChain tools (same names, args,
    marker-string returns, role gating, and ETag-safe writes). Closures over the
    session workspace + user."""

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

    def _tool_result(result: ProductToolResult, text: str) -> tuple[str, dict]:
        return text, {"product_result": result.to_dict()}

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
        return _tool_result(result, _engagement_detail_text(outcome.record) if outcome.record else result.message)

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
        self._internal_tool_names: set[str] = set(INTERNAL_SKILL_TOOLS)
        self._credential: DefaultAzureCredential | None = None
        self._sync_credential: SyncDefaultAzureCredential | None = None

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
        model_auth: dict = {}
        if token:
            # An explicitly forwarded or configured bearer token remains a static
            # compatibility mode. The runtime may replace this session when a new
            # inbound token arrives (see server._get_or_create_session).
            self._token = token
            model_auth["azure_ad_token"] = token
        else:
            # Do not pin a managed-identity token at session creation. LangChain
            # constructs both synchronous and asynchronous Azure OpenAI clients,
            # so each needs its matching refreshable provider.
            self._credential = DefaultAzureCredential()
            self._sync_credential = SyncDefaultAzureCredential()

            def azure_ad_sync_token_provider() -> str:
                credential = self._sync_credential
                if credential is None:
                    raise RuntimeError("Azure credential is unavailable")
                access_token = credential.get_token(
                    "https://cognitiveservices.azure.com/.default"
                )
                return access_token.token

            async def azure_ad_async_token_provider() -> str:
                credential = self._credential
                if credential is None:
                    raise RuntimeError("Azure credential is unavailable")
                access_token = await credential.get_token(
                    "https://cognitiveservices.azure.com/.default"
                )
                return access_token.token

            model_auth["azure_ad_token_provider"] = azure_ad_sync_token_provider
            model_auth["azure_ad_async_token_provider"] = azure_ad_async_token_provider

        # AZURE_ENDPOINT points at the Foundry/Cognitive-Services resource and may be
        # given as `…/openai` or `…/openai/v1/`. AzureChatOpenAI wants the bare resource
        # endpoint plus the deployment + api-version (the classic deployments path,
        # verified working against this resource); derive it defensively by stripping
        # anything from `/openai` onward. Explicit Cognitive-Services bearer tokens
        # use azure_ad_token; managed identity uses LangChain's refreshable AAD providers.
        base_endpoint = os.environ["AZURE_ENDPOINT"].split("/openai")[0].rstrip("/")
        deployment = os.environ["AZURE_DEPLOYMENT"]
        # gpt-5 reasoning models (non-chat) only honor reasoning_effort via the Responses
        # API — chat/completions rejects it alongside tools — so route those there at a
        # version that supports it, and leave plain chat models on completions untouched.
        is_reasoning = deployment.startswith("gpt-5") and "chat" not in deployment
        api_version = os.getenv("AZURE_API_VERSION", "2024-10-21")
        reasoning_kwargs: dict = {}
        if is_reasoning:
            api_version = os.getenv("REASONING_API_VERSION", "2025-04-01-preview")
            reasoning_kwargs = {"use_responses_api": True, "reasoning_effort": os.getenv("REASONING_EFFORT", "low")}
        model = AzureChatOpenAI(
            azure_endpoint=base_endpoint,
            azure_deployment=deployment,
            api_version=api_version,
            streaming=True,
            **model_auth,
            **reasoning_kwargs,
        )

        tools = _build_langchain_tools(self._working_dir, self._user_id)
        self._tool_names = {t.name for t in tools}
        self._checkpointer = InMemorySaver()
        native_skill = deepagents_skill_config()
        self._agent = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=SYSTEM_PROMPT + _user_prompt_line(self._user_id),
            middleware=[_ToolExclusionMiddleware(excluded=_EXCLUDED_BUILTINS)],
            checkpointer=self._checkpointer,
            **native_skill,
        )

        _trace(
            "agent.session_initialized",
            session_id=self._session_id,
            working_dir=self._working_dir,
            model=deployment,
            backend="deepagents",
            available_tools=sorted(self._tool_names),
            internal_skill_tools=sorted(self._internal_tool_names),
            skills=[skill_identity()],
        )
        self._write_raw_sdk_record({
            "kind": "session_initialized",
            "backend": "deepagents",
            "available_product_tools": sorted(self._tool_names),
            "internal_skill_tools": sorted(self._internal_tool_names),
            "skills": [skill_identity()],
        })
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._agent = None
        if self._sync_credential:
            self._sync_credential.close()
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
        open_tool_calls: dict[str, dict] = {}  # SDK run id -> tool evidence
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
                    if name not in self._tool_names and name not in self._internal_tool_names:
                        raise RuntimeError(f"Deep Agents exposed an unapproved tool: {name}")
                    call_id = ev.get("run_id") or str(uuid.uuid4())
                    arguments = (ev.get("data") or {}).get("input")
                    args_str = _args_to_str(arguments)
                    selected_skill = skill_name_for_read(arguments) if name == "read_file" else None
                    open_tool_calls[call_id] = {
                        "name": name,
                        "arguments": _jsonable(arguments),
                        "args_str": args_str,
                        "skill": selected_skill,
                    }
                    self._status = f"tool:{name}"
                    if name in self._internal_tool_names:
                        self._write_raw_sdk_record({
                            "kind": "internal_skill_tool_start",
                            "run_id": self._run_id,
                            "tool_call_id": call_id,
                            "tool": name,
                            "arguments": _jsonable(arguments),
                            "recognized_skill": selected_skill,
                        })
                        continue
                    yield _sse_event(ToolCallStartEvent(
                        tool_call_id=call_id,
                        tool_call_name=name,
                        parent_message_id=current_msg_id or None,
                    ))
                    if args_str:
                        yield _sse_event(ToolCallArgsEvent(tool_call_id=call_id, delta=args_str))
                    _trace("agent.tool_start", session_id=self._session_id, run_id=self._run_id, tool=name, call_id=call_id, args=args_str)

                elif kind == "on_tool_end":
                    call_id = ev.get("run_id")
                    entry = open_tool_calls.pop(call_id, None)
                    if entry is None:
                        raise RuntimeError("Deep Agents emitted an uncorrelated tool result")
                    name = entry["name"]
                    self._status = "thinking"
                    result = (ev.get("data") or {}).get("output")
                    model_visible_output = _model_visible_text(result)
                    if name in self._internal_tool_names:
                        result_status = getattr(result, "status", None)
                        recognized_skill = entry.get("skill")
                        record_kind = "skill_invoked" if recognized_skill and result_status != "error" and model_visible_output else "skill_load_failed"
                        record = {
                            "kind": record_kind,
                            "run_id": self._run_id,
                            "tool_call_id": call_id,
                            "tool": name,
                            "arguments": entry.get("arguments"),
                            "model_visible_output": model_visible_output,
                        }
                        if recognized_skill:
                            record["skill"] = skill_identity()
                        self._write_raw_sdk_record(record)
                        _trace(
                            "agent.skill_invoked" if record_kind == "skill_invoked" else "agent.skill_load_failed",
                            session_id=self._session_id,
                            run_id=self._run_id,
                            skill=recognized_skill,
                            call_id=call_id,
                        )
                        continue
                    tools_called += 1
                    product_result = _artifact_result(result)
                    if product_result is None:
                        product_result = ProductToolResult("failed", "tool.missing_native_result", name, "The tool did not return a structured result.")
                    self._write_raw_sdk_record({
                        "kind": "product_tool_execution",
                        "run_id": self._run_id,
                        "tool_call_id": call_id,
                        "tool": name,
                        "arguments": entry.get("arguments"),
                        "model_visible_output": model_visible_output,
                        "product_result": product_result.to_dict(),
                    })
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
            msg = _safe_error_message(exc)
            self._write_raw_sdk_record({"kind": "turn_exception", "run_id": self._run_id, "error": repr(exc)})
            _trace("agent.error", session_id=self._session_id, run_id=self._run_id, message=msg)
            yield _sse_event(RunErrorEvent(message=msg))
        finally:
            self._turn_active = False
            self._write_raw_sdk_record({"kind": "turn_finalized", "run_id": self._run_id, "status": self._status})
