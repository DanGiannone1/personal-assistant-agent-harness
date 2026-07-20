# Agent Harness Capability

> **Authority:** This document covers harness details; see [design.md](../design.md) for the full picture.
>
> **Deployed application revision:** `ce251fbbe03c6b99bc38e676a8be88e9f199f777`
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
the same seven **product** tool names and schemas. Deep Agents additionally retains one internal
native `read_file` loader for progressive disclosure of the approved meeting-prep skill; it is not a
public product operation or AG-UI tool event.

The important result of a tool call is a structured `ProductToolResult`, not the tool label or the
assistant's sentence. The browser renders that result, accepts navigation only from a correlated
structured event, and re-reads authoritative application state (the stored truth, not a cached
copy) after tool activity and terminal
events. This is how the harness supports the product rule that a claim can never outrun reality.

## One turn, end to end

For a normal assistant request, the implemented path is:

1. The API authenticates the browser actor and verifies that actor owns the ephemeral session.
2. For an HTTPS runtime endpoint, the API obtains a managed-identity token for the configured runtime
   audience — a call authenticated with the API's own managed identity. It sends the actor in an
   internal header covered by that same call.
3. In deployed Entra mode, the runtime validates the workload token. It then checks its write-once
   session-to-actor binding and takes the process-local lock for that session.
4. The selected `AgentSession` sends the prompt to the model along with seven typed product tools.
   Each tool is already tied to the actor and session workspace — neither one is something the model
   can pass in as an argument. In Deep Agents, the model also receives the compact native skill
   catalog and the one deny-by-default internal loader described below.
5. Engagement tools call the runtime's instance of the shared `workbench_core.EngagementService`,
   which re-reads the current Cosmos state and applies the current membership, role, and validation
   rules.
6. The harness preserves the native structured result and emits correlated AG-UI events as SSE
   (server-sent events).
7. The API proxy and browser independently validate framing and lifecycle order. The browser applies
   only valid structured navigation and refreshes the current application state.

The system doesn't yet have one central piece of code that manages event types, security context, and
turn cancellation the same way across both adapters. It also has no permanent record proving a turn
completed, or one place that assembles all the context the model sees. Neither gap weakens who a
request is bound to or what it's allowed to do — those checks are enforced outside the prompt and the tools
the model can see.

## Harness seam and selection

`session-container/server.py` imports one of two concrete classes behind the same small runtime-facing
shape:

```python
AgentSession(working_dir, token=None, session_id="default", user_id="dan")

async with session:
    async for sse_frame in session.send(prompt, navigation_version):
        ...
```

The server also reads the common `token`, `user_id`, and `raw_sdk_log_path` properties. This seam is
stable and useful: session creation, actor binding, locking, timeout, and HTTP transport stay in the
server, while model and SDK mechanics stay in the adapter.

It is not the more general `run/cancel/aclose` interface described in earlier target designs. Instead,
the adapters yield already-formatted SSE text, expose the token and raw-log details directly, and clean
up using Python's async context-manager teardown. There's no explicit cancel method — closing the
generator is what stops it.

`AGENT_BACKEND` accepts exactly `deepagents` or `copilot`, defaults to `deepagents`, and fails startup
for any other value. Selection is fixed once the runtime process imports the adapter. There is no
automatic or mid-turn fallback, so a failed turn is not replayed through the other harness.

### Deep Agents primary

Deep Agents uses `AzureChatOpenAI`, an in-memory LangGraph checkpointer, native LangChain tools, and
`create_deep_agent`. The adapter excludes the framework's planning, shell, filesystem writes and
search, and subagent tool names. It retains native `read_file` only behind a virtual root and ordered
permissions that allow the exact meeting-prep `SKILL.md` read and deny every other path. The adapter
raises an error if a runtime event reports a tool outside the product inventory plus that internal
loader.

The deployed runtime uses its own managed identity for Azure OpenAI. The API deployment sets legacy
Azure OpenAI token forwarding off, while the runtime obtains a Cognitive Services token through its
configured identity when it initializes the harness.

### Copilot portability check

Copilot uses the same model-visible tool inventory and product result contract through native Copilot
tools. It is selectable for local comparison but is not a deployed release dependency. Focused tests
prove exact schema equality and representative structured-result equality across the two adapters.
They do not prove identical model wording, SDK events, cancellation behavior, or complete live parity
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

Both adapters return exactly those **product** tools, in that order, and derive their JSON schemas
from the same Pydantic models. Actor, role, session ID, and workload credentials are absent from
every schema. The Deep Agents skill loader is harness-local and outside this product catalog.
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
Only `committed` and `resolved` may carry a destination. The destination validator only accepts the
catalog IDs and exact paths described in [Navigation](navigation.md).

Not every status in that list is actually produced today. The Engagement service doesn't keep
permanent confirmation records, doesn't expose a version number callers can check for conflicts,
doesn't have unique request IDs to detect a retried request, and doesn't have a distinct error type
for storage failures. A current result contains no Cosmos ETag (a version marker used to detect
conflicting writes), activity ID, permanent record proving the command happened, or full Engagement
record. See [CRUD](crud.md) for the exact implemented operation and concurrency boundary.

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

Optional `REASONING_START`, `REASONING_DELTA`, and `REASONING_END` events may also appear. They're for
the UI to display, not evidence that any product work succeeded. There is no implemented
`CONTEXT_APPLIED` event or persisted context projection.

`TOOL_CALL_RESULT` carries the validated `ProductToolResult`. For a destination-bearing `resolved` or
`committed` result, the runtime may also emit `NAVIGATION_RESOLVED` with the run ID, the exact
destination, and the navigation version captured when the turn began. Navigation remains a separate
structured effect; neither assistant text nor a tool-name allowlist moves the browser.

The API proxy frames complete SSE records (each ending in an LF or CRLF line break), decodes UTF-8
strictly and incrementally, parses the JSON, and checks that run, message, tool, result, navigation,
and terminal events arrive in a valid order. It holds an upstream terminal event until a clean
end-of-stream confirms no duplicate follows. If a stream is malformed or interrupted, the proxy
closes any message/tool lifecycle it can still cleanly close and emits a safe `RUN_ERROR`.

The frontend repeats the lifecycle validation before reducing an event. It rejects malformed JSON,
unknown event types, wrong correlation, events after a terminal, truncated frames, and a clean close
without a terminal. It accepts navigation only when the native tool result, run, navigation version,
catalog destination, cancellation state, and the current actor-filtered Engagement state all agree.

The adapters normally emit one terminal event, and the validating proxy prevents a second terminal
from reaching the browser. This validates the stream; it doesn't create a permanent record proving
the turn ran exactly once.

## Locking, timeout, cancellation, and failure

### Locking and timeout

The runtime owns one `asyncio.Lock` per session. It verifies the actor before acquiring the lock,
acquires it before the stream generator starts, and returns `409 Session is busy` when another turn
already holds it. The lock object remains for the process lifetime so reset cannot create a second
lock while an earlier request still uses the first.

Each runtime turn has a configured timeout, 300 seconds by default. A timeout or unhandled runtime
turn failure destroys that live harness, emits `RUN_ERROR`, and releases the session lock in `finally`.
The browser also has a separate 600-second inactivity timer. That timer aborts the browser's
observation of the stream and shows an error — it does not mean the server has acknowledged or
completed a cancellation.

### Stop and disconnect

Stop marks the browser turn cancelled, aborts the fetch, ignores later buffered events, and makes the
input usable. Copilot attempts to abort its SDK turn when its `send()` generator closes. Deep Agents
has no explicit cancel method or acknowledgement; closing the async event stream is how cancellation
propagates. New session also aborts the browser stream and then asks the runtime to delete the old
session; runtime deletion is serialized by the same lock.

Cancelling doesn't undo anything. A tool call may already have saved its change before the disconnect,
and clicking Stop doesn't itself wait to check whether that happened, nor does it receive a known
commit state. The next time the app reads data, that's what's trusted. There's no strict guarantee
the underlying Deep Agents provider or tool operation has actually stopped when
the screen goes idle, no stored `cancelled` status, and no way to resume a stopped stream.

### Visible failures

- Invalid, forbidden, missing, ambiguous, no-op, and failed tool outcomes remain structured and do
  not produce navigation.
- Unknown harness names fail startup rather than selecting Copilot silently.
- Workload-token failures reject the runtime call before the forwarded actor header is trusted.
- Provider and adapter failures end in a safe terminal error; rate-limit and content-filter cases get
  bounded user-facing messages.
- Malformed, truncated, wrongly ordered, or duplicate-terminal upstream streams fail closed (they're
  rejected rather than let through) in the proxy and browser.
- A tool result or mutation that was already delivered before a later terminal failure is not rolled
  back — the browser refreshes the current state after each tool ends and after the terminal success
  or error.

The system has no permanent way to tell "the action failed before it saved" apart from "the action
saved but the response was lost." So it makes no promise of safe automatic replay, and no strict claim
about what a cancellation actually stopped.

## Prompt, context, memory, and traces

The two adapters currently contain separate copies of the same small static product prompt and append
a short line naming the actor to the system prompt (actor grounding) when the harness is created.
Deep Agents exposes one active product skill,
[`engagement-meeting-prep`](../../session-container/product-skills/engagement-meeting-prep/SKILL.md),
through the framework's native progressive-disclosure mechanism. Copilot product runtime skills
remain disabled; Waza evaluates the same skill file through Copilot only in a hermetic laboratory
lane.

The virtual skill backend exposes no application files, session workspace, or second skill. A
successful full skill read is recorded in the optional raw diagnostic stream with its name, SHA-256,
and model-visible body. Failed loader reads and product tool executions are also distinguishable in
that stream. Internal loader events are intentionally suppressed from public AG-UI, so the browser
still observes only the seven typed product tools. This raw capture can contain prompts and skill
content; it remains local, ephemeral, and diagnostic rather than a user-facing audit log.

Per-turn display context is still assembled in the browser. The frontend fetches a context bundle,
builds a bracketed preamble containing date, current view, display user, persona, and applicable
conventions, and concatenates it with the user's message before sending one `prompt` string. If the
bundle fetch fails, it sends date and current view without personalization. The inspector renders the
fetched bundle, not a server-emitted record of exactly what the harness accepted.

This browser composition is useful current behavior, but it is not a locked-down, tamper-proof
context system: the user's words and the context hints aren't kept as separate fields on the server,
there's no context ID or `CONTEXT_APPLIED` event, and nothing about it is saved permanently. The
product's real actor and permission checks do not depend on this preamble.

Conversation continuity is ephemeral. Deep Agents uses `InMemorySaver`; Copilot keeps its live SDK
session; the browser stores completed visible messages in actor-namespaced `sessionStorage`. Runtime
workspace files, conversation state, and browser chat do not become permanent product records.

When enabled, local tracing writes process-local JSONL and optional per-session raw SDK JSONL. Raw SDK
capture can include the full prompt and is diagnostic-only. The runtime can also initialize Azure
Monitor HTTP tracing when configured, but the repository does not implement a complete, correlated way
to observe an entire turn end-to-end. There is no actor-authorized trace API, no permanent record
proving a turn happened, no retention guarantee, and no promise that traces survive a scale-in event
or a new revision replacing the running one.

## Evidence status

### Verified behavior

Focused tests at the deployed application revision cover:

- exact Copilot/Deep Agents tool inventory and JSON-schema equality;
- representative native result parity and rejection of marker-text substitutes;
- `ProductToolResult` and destination validation;
- framed SSE parsing, lifecycle correlation, interruption closure, and one-terminal forwarding;
- workload-token tenant, audience, caller, role, and failure checks; and
- Engagement authorization, validation, no-op, and resulting-state behavior.

The current checkout additionally has deterministic contracts for the exact virtual skill root,
allow-one/deny-all permissions, full-read invocation recognition, skill hashing, hidden internal
loader inventory, three-turn workflow continuity, complete model-visible product-tool evidence, and
runtime-image packaging. Those source checks do not prove a live model turn or update the older
deployed-revision evidence above.

The primary sources are
[`tests/test_structured_control.py`](../../tests/test_structured_control.py),
[`tests/test_release_boundaries.py`](../../tests/test_release_boundaries.py), and
[`tests/test_engagement_core.py`](../../tests/test_engagement_core.py).

The ignored local Deep Agents observation with run ID
`2026-07-19T14-36-18-536Z-0a399fbe` passed seven structured cases at source revision `e641082`,
including typed reads, mutation, navigation, denial/non-execution, exact terminal validation, and a
marker-like prompt that produced no false effect.

The ignored local browser observation with run ID
`2026-07-19T14-35-51-193Z-779df115` passed 34 checks at source revision `e641082`, including a
structured Engagement update followed by a state and UI refresh from authoritative state. These ignored
results are local observations, not portable evidence in a fresh clone.

The [authoritative design](../design.md) records the smoke test run against the final deployed
release candidate: the Deep Agents turn `List my engagements.` emitted a typed
`list_engagements` call and successful `engagement.listed` result before describing the exact
Cosmos-backed Engagement. That smoke also covered a workload-authenticated runtime call and reading
back the current Engagement state afterward.

### Remaining evidence and implementation gaps

- The local eval and browser bundles predate the deployed application revision. A fresh clean-worktree
  local Deep Agents bundle at `807a0d6` is absent.
- The deployed typed `list_engagements` turn is recorded in the authoritative design, but there is no
  permanent record proving it happened beyond that write-up, and no checked-in per-event deployed
  transcript to inspect independently.
- Copilot has focused schema/result contract evidence, but not a full, current live local-parity
  bundle.
- Prompt and per-turn context sources are duplicated across adapters or assembled in the browser.
  Only Deep Agents has the one active product skill; there is still no shared cross-harness skill
  catalog or server-recorded copy of the complete context that was actually applied.
- The new three-turn workflow and Deep Agents skill invocation have deterministic source contracts
  but no accepted clean-worktree live bundle for this revision yet.
- Stop/disconnect, a timeout during a tool call, and an unknown commit state are not covered by an
  end-to-end cancellation contract in which the server acknowledges what was actually stopped. Deep
  Agents cancellation in particular is not proven to be strict.
- The shared core covers basic Engagement operations only — full parity between manual and agent
  capability is not implemented.
- Traces and turn state are ephemeral, optional, and incomplete. There are no permanent records of
  what happened, and no user-facing observability promises are implemented.

These are precise limits of this release, not permission to add a coordinator, an external MCP
service, a permanent conversation system, a broad observability program, or other hardening beyond
the MVP.

## Related authority

- [Authoritative design](../design.md)
- [MVP success criteria](../requirements.md)
- [CRUD](crud.md)
- [Navigation](navigation.md)
- [Context](context.md)
- [Session and state](session-state.md)
- [Identity and access](identity-access.md)
- [Testing and evals](testing-evals.md)
