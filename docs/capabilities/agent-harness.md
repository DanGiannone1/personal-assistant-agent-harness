# Agent harness boundary

> **Authority:** Focused current-boundary note; [design](../design.md) and [requirements](../requirements.md) remain higher authority.

## In plain language

CSA Workbench is an Engagement application with an assistant, not an agent platform. A person can
operate the product directly, and the assistant uses a small set of typed tools over the same
durable Engagement and personal records. The model does not choose the actor, role, session, route,
or meaning of success.

Deep Agents is the deployed product runtime. A Copilot adapter remains available for a local,
non-release-blocking portability check. Both fit the same `AgentSession` seam and expose the same
model-visible product tools and schemas. Deep Agents additionally retains one internal native
`read_file` loader for progressive disclosure of the four approved product skills; it is not a
public product operation or AG-UI tool event.

The important result of a tool call is a structured `ProductToolResult`, not the tool label or the
assistant's sentence. The browser renders that result, accepts navigation only from a correlated
structured event, and re-reads authoritative application state after tool activity and terminal
events — the harness mechanism behind the product rule that a claim can never outrun reality.

## One turn, end to end

1. The API authenticates the browser actor and verifies that actor owns the ephemeral session.
2. It calls the internal session runtime and forwards the bound actor outside the request body.
3. The runtime checks its write-once session-to-actor binding and takes the process-local lock for
   that session.
4. The selected `AgentSession` sends the prompt to the model along with the full typed product-tool
   catalog. Each tool is already tied to the actor and session workspace — neither is something the
   model can pass in as an argument. Deep Agents additionally exposes the compact native skill
   catalog and the one deny-by-default internal `read_file` loader.
5. A selected tool calls the runtime's instance of the matching shared service —
   `workbench_core.EngagementService` for Engagement tools, `workbench_core.PersonalWorkspaceService`
   for personal tools, or the navigation catalog for `navigate` — which re-reads current state and
   applies its authorization and validation rules.
6. The harness preserves the native structured result and emits correlated AG-UI events over SSE.
7. The API proxy and browser independently validate framing and lifecycle order. The browser applies
   only valid structured navigation and refreshes the current application state.

## Harness seam and selection

`session-container/server.py` imports one of two concrete classes behind the same small
runtime-facing shape (`AgentSession(working_dir, token=None, session_id=..., user_id=...)`, an async
context manager whose `send(prompt, navigation_version)` yields already-formatted SSE frames). Session
creation, actor binding, locking, timeout, and HTTP transport stay in the server; model and SDK
mechanics stay in the adapter. There is no explicit cancel method — closing the generator is what
stops it.

`AGENT_BACKEND` accepts exactly `deepagents` or `copilot`, defaults to `deepagents`, and fails startup
for any other value. Selection is fixed once the runtime process imports the adapter — there is no
automatic or mid-turn fallback, so a failed turn is never replayed through the other harness.

### Deep Agents (product runtime)

Deep Agents uses `AzureChatOpenAI`, an in-memory LangGraph checkpointer (`InMemorySaver`), native
LangChain tools, and `create_deep_agent`. The adapter excludes the framework's planning, shell,
filesystem-write, search, and subagent tool names. It retains native `read_file` only behind a
virtual root and ordered permissions that allow exactly the four approved `SKILL.md` reads
(`skill_runtime.SKILL_NAMES`: `engagement-meeting-prep`, `tasks`, `calendar`, `weekly-review`) and
deny every other path. The adapter raises if a runtime event reports a tool outside the product
inventory plus that internal loader. The runtime uses its own managed identity for Azure OpenAI in
the Entra release.

### Copilot (portability check)

Copilot uses the same model-visible tool inventory and product result contract through native
Copilot tools. It is selectable for local comparison (`AGENT_BACKEND=copilot uv run dev.py`) but is
not a deployed release dependency. Product skills are disabled on this lane; the separate Waza
laboratory evaluates the `engagement-meeting-prep` skill through Copilot only, in a hermetic mock
environment — never Deep Agents product state.

## Model-visible tools

The active Pydantic schema catalog in
[`session-container/mvp_tool_schemas.py`](../../session-container/mvp_tool_schemas.py) defines twenty
tools, all closed over the bound actor with no actor/role/session argument:

| Group | Tools |
|---|---|
| Navigation | `navigate` |
| Engagement | `list_engagements`, `create_engagement`, `get_engagement`, `update_engagement`, `set_engagement_status`, `share_engagement` |
| Personal tasks | `list_tasks`, `create_task`, `update_task`, `delete_task`, `add_subtask` |
| Personal calendar | `list_events`, `create_event`, `update_event`, `delete_event` |
| Personal reminders | `list_reminders`, `create_reminder`, `update_reminder`, `delete_reminder` |

Both adapters return exactly this catalog and derive their JSON schemas from the same Pydantic
models. The six Engagement tools instantiate `EngagementService`; the thirteen personal tools
instantiate `PersonalWorkspaceService` — the same services the manual REST paths use — so this is
shared-core parity for those operations, not for the whole application. Engagement member removal,
tasks, conventions, and artifacts remain manual-only; see [CRUD](crud.md).

## Typed outcomes

`workbench_core` translates a service outcome into a transport-neutral `ProductToolResult`:
`status`, `code`, `operation`, `message`, an optional `resource`, and an optional `destination`
(only on a `committed` or `resolved` result, validated against the navigation catalog). Each harness
stores this in native tool metadata rather than parsing model-visible text — Copilot uses
`tool_telemetry.product_result`, Deep Agents uses a LangChain tool artifact. Missing or invalid
native metadata becomes a structured `tool.missing_native_result` failure; marker-like prose never
becomes a product result.

## AG-UI over SSE

The adapters normalize their SDK events to one lifecycle: `RUN_STARTED`, message/tool event groups
(`TOOL_CALL_START -> TOOL_CALL_ARGS? -> TOOL_CALL_RESULT -> TOOL_CALL_END`, with an optional
`NAVIGATION_RESOLVED` while its matching tool result is still open), repeating, then one
`RUN_FINISHED` or `RUN_ERROR`. The API proxy frames complete SSE records, decodes UTF-8 strictly, and
validates that lifecycle order before forwarding; the frontend repeats that validation before
reducing an event. A malformed, truncated, or wrongly ordered stream fails closed with a safe
`RUN_ERROR` rather than being partially applied.

## Locking, timeout, and cancellation

The runtime holds one `asyncio.Lock` per session, verifies the actor before acquiring it, and returns
`409 Session is busy` if another turn already holds it; different sessions proceed independently.
Each turn has a configured timeout (300 seconds by default); a timeout or unhandled failure destroys
the live harness, emits `RUN_ERROR`, and releases the lock. Stop is a client-side stream abort: the UI
ignores later buffered events, but a tool call that already committed before disconnect remains
committed — the next authoritative state read is the only trusted signal, not the cancellation
itself. See [Session and state](session-state.md) for the full session lifecycle.

## Evidence status

Focused tests cover exact tool inventory and JSON-schema shape, `ProductToolResult`/destination
validation, framed SSE parsing and lifecycle correlation, and Engagement/personal-workspace
authorization and validation behavior (`tests/test_structured_control.py`,
`tests/test_engagement_core.py`, `tests/test_personal_workspace.py`, `tests/test_skill_runtime.py`).
A local browser journey passed 41/41 checks at the current revision including a live agent turn, and
live-model spot checks cover the personal tools. **UNVERIFIED:** a deployed Azure/Entra turn and a
live-model eval run of the `MVP-E8`/`MVP-E9` personal-work cases specifically.

## Related authority

- [Design](../design.md)
- [CRUD](crud.md)
- [Navigation](navigation.md)
- [Context](context.md)
- [Session and state](session-state.md)
- [Identity and access](identity-access.md)
- [Testing and evals](testing-evals.md)
