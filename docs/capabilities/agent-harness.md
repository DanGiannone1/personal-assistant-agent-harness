# Agent Harness Capability

> **Authority:** Canonical harness detail subordinate to the [authoritative design](../design.md)
>
> **Deployed application revision:** `c544f6ca7d70a80d9aa5708d22c590f8f13c88d6`
>
> **Applies to:** Harness selection, the `AgentSession` seam, product-tool adaptation, AG-UI/SSE events, turn coordination, cancellation, and traces
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## In plain language

CSA Workbench is an Engagement application with an assistant, not an agent platform. A person can
operate the product directly, and the assistant uses a small set of typed tools over the same durable
Engagement records. The model does not choose the actor, role, session, route, or meaning of success.

Deep Agents is the deployed primary harness. A Copilot adapter remains available for a local,
non-release-blocking portability check. Both fit the same operational `AgentSession` seam and expose
the same seven model-visible tool names and schemas.

The important result of a tool call is a structured `ProductToolResult`, not the tool label or the
assistant's sentence. The browser renders that result, accepts navigation only from a correlated
structured event, and refreshes authoritative application state after tool activity and terminal
events. This is how the harness supports the product rule that a claim cannot outrun reality.

## One turn, end to end

For a normal assistant request, the implemented path is:

1. The API authenticates the browser actor and verifies that actor owns the ephemeral session.
2. For an HTTPS runtime endpoint, the API obtains a managed-identity token for the configured runtime
   audience. It sends the actor in an internal header covered by that workload-authenticated call.
3. In deployed Entra mode, the runtime validates the workload token. It then checks its write-once
   session-to-actor binding and takes the process-local lock for that session.
4. The selected `AgentSession` sends the prompt to the model with exactly seven typed product tools.
   Each tool is closed over the trusted actor and session workspace; neither is a model argument.
5. Engagement tools call the runtime's instance of the shared `workbench_core.EngagementService`,
   which re-reads current Cosmos state and applies current membership, role, and validation rules.
6. The harness preserves the native structured result and emits correlated AG-UI events as SSE.
7. The API proxy and browser independently validate framing and lifecycle order. The browser applies
   only valid structured navigation and refreshes current application state.

The current implementation does not yet have a separate coordinator abstraction that owns typed
events, trusted context, and acknowledged cancellation across both adapters. It also has no durable
turn receipt or complete trusted-context composition layer. Those gaps do not weaken actor binding or
tool authorization, which are enforced outside the prompt and model-visible schemas.

## Harness seam and selection

`session-container/server.py` imports one of two concrete classes behind the same small runtime-facing
shape:

```python
AgentSession(working_dir, token=None, session_id="default", user_id="dan")

async with session:
    async for sse_frame in session.send(prompt, navigation_version):
        ...
```

The server also reads the common `token`, `user_id`, and `raw_sdk_log_path` properties. This is a
stable and useful seam: session creation, actor binding, locking, timeout, and HTTP transport stay in
the server while model and SDK mechanics stay in the adapter.

It is not the more transport-neutral `run/cancel/aclose` protocol described in earlier target designs.
The adapters currently yield already-formatted SSE strings, expose token and raw-log details, and use
async context-manager teardown. Cancellation is implicit in generator closure rather than a common
acknowledged method.

`AGENT_BACKEND` accepts exactly `deepagents` or `copilot`, defaults to `deepagents`, and fails startup
for any other value. Selection is fixed when the runtime process imports the adapter. There is no
automatic or mid-turn fallback, so a failed turn is not replayed through the other harness.

### Deep Agents primary

Deep Agents uses `AzureChatOpenAI`, an in-memory LangGraph checkpointer, native LangChain tools, and
`create_deep_agent`. The adapter excludes the framework's planning, shell, generic filesystem, and
subagent tool names and raises if a runtime event reports a tool outside the approved inventory.

The deployed runtime uses its own managed identity for Azure OpenAI. The API deployment sets legacy
Azure OpenAI token forwarding off, while the runtime obtains a Cognitive Services token through its
configured identity when it initializes the harness.

### Copilot portability check

Copilot uses the same model-visible tool inventory and product result contract through native Copilot
tools. It is selectable for local comparison but is not a deployed release dependency. Focused tests
prove exact schema equality and representative structured-result equality across the two adapters;
they do not prove identical model wording, SDK events, cancellation behavior, or complete live parity
for every turn.

## Model-visible tools and the shared Engagement core

The single active Pydantic schema catalog in
[`session-container/mvp_tool_schemas.py`](../../session-container/mvp_tool_schemas.py) defines:

| Tool | Purpose |
|---|---|
| `navigate` | Resolve one destination from the application catalog |
| `list_engagements` | List Engagements visible to the bound actor |
| `create_engagement` | Create an Engagement with the actor as owner |
| `get_engagement` | Read one visible Engagement by stable ID |
| `update_engagement` | Change supported Engagement fields |
| `set_engagement_status` | Set Green, Yellow, or Red with the required reason |
| `share_engagement` | Add a member or change a member role as an owner |

Both adapters return exactly those tools, in that order, and derive their JSON schemas from the same
Pydantic models. Actor, role, session ID, and workload credentials are absent from every schema.
Legacy task, calendar, document, and schedule helper functions remain in the large adapter modules,
but they are not returned to the model in this release.

The six Engagement tools instantiate `EngagementService` over the same repository adapter used by
the manual Engagement REST path. That shared core owns the implemented basic Engagement membership,
role, validation, no-op, mutation, and activity behavior. `navigate` uses the separate catalog-backed
navigation service and returns the same `ProductToolResult` type.

This is shared-core parity for basic Engagement operations, not for the whole application. Manual
tasks, conventions, artifacts, and member removal have broader REST/UI coverage and are not all in
the model inventory or the shared service. There is no active external MCP tool server in this turn
path; the adapters call the core in process.

## Typed outcomes

`workbench_core` translates a service `Outcome` into a safe, transport-neutral
`ProductToolResult`. The current public shape is:

```json
{
  "status": "committed",
  "code": "engagement.committed",
  "operation": "update",
  "message": "",
  "resource": {"kind": "engagement", "id": "eng-42"}
}
```

The accepted status vocabulary is `committed`, `resolved`, `succeeded`, `noop`,
`needs_confirmation`, `ambiguous`, `invalid`, `not_found`, `forbidden`, `conflict`, and `failed`.
Only `committed` and `resolved` may carry a destination. The destination validator accepts only the
catalog IDs and exact canonical paths described by [Navigation](navigation.md).

Not every accepted status is produced by the current Engagement service. It does not implement
durable confirmation records, caller-visible expected versions, idempotency keys, or typed storage
failure receipts. A current result contains no Cosmos ETag, activity ID, durable command receipt, or
full Engagement record. See [CRUD](crud.md) for the exact implemented operation and concurrency
boundary.

Each harness stores the typed result in native tool metadata rather than parsing model-visible text:
Copilot uses `tool_telemetry.product_result`; Deep Agents uses a LangChain tool artifact. Missing or
invalid native metadata becomes a structured `tool.missing_native_result` failure. Marker-like prose
does not become a product result.

## AG-UI over SSE

The adapters normalize their different SDK events to this implemented lifecycle:

```text
RUN_STARTED
  TEXT_MESSAGE_START -> TEXT_MESSAGE_CONTENT* -> TEXT_MESSAGE_END
  TOOL_CALL_START -> TOOL_CALL_ARGS? -> TOOL_CALL_RESULT -> TOOL_CALL_END
  NAVIGATION_RESOLVED?            # while its matching tool result is still open
  ... groups may repeat ...
RUN_FINISHED | RUN_ERROR
```

Optional `REASONING_START`, `REASONING_DELTA`, and `REASONING_END` events may also appear. They are
presentation diagnostics, not evidence that product work succeeded. There is no implemented
`CONTEXT_APPLIED` event or persisted context projection.

`TOOL_CALL_RESULT` carries the validated `ProductToolResult`. For a destination-bearing `resolved` or
`committed` result, the runtime may also emit `NAVIGATION_RESOLVED` with the run ID, the exact
destination, and the navigation version captured when the turn began. Navigation remains a separate
structured effect; neither assistant text nor a tool-name allowlist moves the browser.

The API proxy frames complete LF or CRLF SSE records, uses strict incremental UTF-8 decoding, parses
JSON, and validates run, message, tool, result, navigation, and terminal order. It holds an upstream
terminal event until clean EOF establishes that no duplicate follows. On malformed or interrupted
streams it closes any known open message/tool lifecycle where possible and emits a safe `RUN_ERROR`.

The frontend repeats the lifecycle validation before reducing an event. It rejects malformed JSON,
unknown event types, wrong correlation, events after a terminal, truncated frames, and a clean close
without a terminal. It accepts navigation only when the native result, run, navigation version,
catalog destination, cancellation state, and current actor-filtered Engagement state agree.

The adapters normally emit one terminal event, and the validating proxy prevents a second terminal
from reaching the browser. This is stream validation rather than a durable exactly-once turn record.

## Locking, timeout, cancellation, and failure

### Locking and timeout

The runtime owns one `asyncio.Lock` per session. It verifies the actor before acquiring the lock,
acquires it before the stream generator starts, and returns `409 Session is busy` when another turn
already holds it. The lock object remains for the process lifetime so reset cannot create a second
lock while an earlier request still uses the first.

Each runtime turn has a configured timeout, 300 seconds by default. A timeout or unhandled runtime
turn failure destroys that live harness, emits `RUN_ERROR`, and releases the session lock in `finally`.
The browser also has a separate 600-second inactivity timer. That timer aborts its observation and
shows an error; it is not a server-side cancellation acknowledgement.

### Stop and disconnect

Stop marks the browser turn cancelled, aborts the fetch, ignores later buffered events, and makes the
input usable. Copilot attempts to abort its SDK turn when its `send()` generator closes. Deep Agents
has no explicit cancel method or acknowledgement; closing the async event stream is the propagation
path. New session also aborts the browser stream and then asks the runtime to delete the old session;
runtime deletion is serialized by the same lock.

Cancellation is not rollback. A tool may have committed before the disconnect, and the current Stop
handler does not itself await an authoritative refresh or receive a known commit state. The next state
read remains authoritative. There is no strict guarantee that a Deep Agents provider/tool operation
has stopped when the UI becomes idle, no durable `cancelled` state, and no resumable stream.

### Visible failures

- Invalid, forbidden, missing, ambiguous, no-op, and failed tool outcomes remain structured and do
  not produce navigation.
- Unknown harness names fail startup rather than selecting Copilot silently.
- Workload-token failures reject the runtime call before the forwarded actor header is trusted.
- Provider and adapter failures end in a safe terminal error; rate-limit and content-filter cases get
  bounded user-facing messages.
- Malformed, truncated, wrongly ordered, or duplicate-terminal upstream streams fail closed in the
  proxy and browser.
- A tool result or mutation already delivered before a later terminal failure is not rolled back; the
  browser refreshes authoritative state on tool end and terminal success or error.

The system does not currently durably distinguish “failed before commit” from “response lost after
commit.” It therefore makes no safe automatic replay or strict cancellation claim.

## Prompt, context, memory, and traces

The two adapters currently contain separate copies of the same small static product prompt and append
an actor-grounding line when the harness is created. Both expose skills as disabled; there is no
shared active skill catalog in this release.

Per-turn display context is still assembled in the browser. The frontend fetches a context bundle,
builds a bracketed preamble containing date, current view, display user, persona, and applicable
conventions, and concatenates it with the user's message before sending one `prompt` string. If the
bundle fetch fails, it sends date and current view without personalization. The inspector renders the
fetched bundle, not a server-emitted record of exactly what the harness accepted.

This browser composition is useful current behavior, but it is not a trusted immutable context
architecture: user text and context are not separate server-side fields, there is no context ID or
`CONTEXT_APPLIED` event, and the projection is not persisted. The product's hard actor and permission
boundaries do not depend on that preamble.

Conversation continuity is ephemeral. Deep Agents uses `InMemorySaver`; Copilot keeps its live SDK
session; the browser stores completed visible messages in actor-namespaced `sessionStorage`. Runtime
workspace files, conversation state, and browser chat do not become durable product records.

When enabled, local tracing writes process-local JSONL and optional per-session raw SDK JSONL. Raw SDK
capture can include the full prompt and is diagnostic-only. The runtime can also initialize Azure
Monitor HTTP tracing when configured, but the repository does not implement a complete correlated
turn-observability contract. There is no actor-authorized trace API, durable turn receipt, retention
contract, or guarantee that traces survive scale-in or revision replacement.

## Evidence status

### Verified behavior

Focused tests at the deployed application revision cover:

- exact Copilot/Deep Agents tool inventory and JSON-schema equality;
- representative native result parity and rejection of marker-text substitutes;
- `ProductToolResult` and destination validation;
- framed SSE parsing, lifecycle correlation, interruption closure, and one-terminal forwarding;
- workload-token tenant, audience, caller, role, and failure checks; and
- Engagement authorization, validation, no-op, and resulting-state behavior.

The primary sources are
[`tests/test_structured_control.py`](../../tests/test_structured_control.py),
[`tests/test_release_boundaries.py`](../../tests/test_release_boundaries.py), and
[`tests/test_engagement_core.py`](../../tests/test_engagement_core.py).

The ignored local Deep Agents observation with run ID
`2026-07-15T01-27-46-902Z-2ecc70df` passed seven structured cases at source revision `7bca264`,
including typed reads, mutation, navigation, denial/non-execution, exact terminal validation, and a
marker-like prompt that produced no false effect.

The ignored local browser observation with run ID
`2026-07-15T02-57-58-244Z-1e852bb3` passed 34 checks at source revision `9142b2a`, including a
structured Engagement update followed by authoritative state/UI refresh. These ignored results are
local observations, not portable evidence in a fresh clone.

The [authoritative design](../design.md) records the final deployed release-candidate smoke: the Deep
Agents turn `List my engagements.` emitted a typed `list_engagements` call and successful
`engagement.listed` result before describing the exact Cosmos-backed Engagement. That smoke also
covered workload-authenticated runtime invocation and authoritative Engagement readback.

### Remaining evidence and implementation gaps

- The local eval and browser bundles predate the deployed application revision. A fresh clean-worktree
  local Deep Agents bundle at `c544f6c` is absent.
- The deployed typed `list_engagements` turn is recorded in the authoritative design, but there is no
  durable turn receipt or checked-in per-event deployed transcript to inspect independently.
- Copilot has focused schema/result contract evidence, not a current full live local parity bundle.
- Prompt and per-turn context sources are duplicated or browser-composed; skills are disabled and no
  server-recorded applied-context projection exists.
- Stop/disconnect, timeout during a tool, and unknown commit state are not covered by an acknowledged
  end-to-end cancellation contract. Deep Agents cancellation is not proven strict.
- The shared core covers basic Engagement operations only; universal manual/agent capability parity is
  not implemented.
- Traces and turn state are ephemeral, optional, and incomplete. There are no durable receipts or
  implemented user-facing observability promises.

These are precise release limits, not authorization to add a coordinator, external MCP service,
durable conversation system, broad observability program, or other hardening outside the MVP.

## Related authority

- [Authoritative design](../design.md)
- [MVP success criteria](../requirements.md)
- [CRUD](crud.md)
- [Navigation](navigation.md)
- [Context](context.md)
- [Session and state](session-state.md)
- [Identity and access](identity-access.md)
- [Testing and evals](testing-evals.md)
