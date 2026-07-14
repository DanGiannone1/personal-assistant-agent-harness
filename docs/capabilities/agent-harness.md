# Agent Harness Capability

> **Authority:** Canonical capability detail subordinate to [CSA Workbench — Authoritative Product and System Design](../design.md)  
> **State:** Target design, reconciled with integrated `master@1fcaac6`  
> **Applies to:** Harness selection, the `AgentSession` seam, prompt and skill composition, product-tool adaptation, AG-UI events, cancellation, and turn traces  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## The short version

CSA Workbench is an Engagement workspace, not an agent framework with a demo attached. The assistant is one
way to operate the same permissioned application core used by the manual UI. If the agent runtime
is unavailable, users can still read and maintain their work.

The harness has one job: turn a user's request and a small trusted context projection into assistant
text and calls to approved CSA Workbench tools. It does not own identity, authorization, validation, durable
state, or the meaning of success. Deep Agents is the deployed primary harness. Copilot is a local,
non-release-blocking portability check. They share one narrow `AgentSession` contract, one static
prompt, one skill catalog, one product-tool contract, and one normalized event stream.

The promise is the product's central invariant: **a claim never outruns reality**. A tool reports a
structured outcome from the runtime's application-core instance. The browser then re-reads
authoritative state.
Neither persuasive model prose nor a harness-native “tool completed” signal proves that a mutation
committed.

This capability deliberately excludes shell access, arbitrary code execution, autonomous subagents,
multi-agent workflows, and weekly-review-style autonomous routines. IDA and other future consumers
may study the contracts, but they create no v1 integration or compatibility requirement.

## A turn in plain language

When an editor asks, “Make Northstar Yellow because the security review slipped,” CSA Workbench processes the
request as follows:

1. The orchestrator verifies the signed-in actor and owned conversation, then validates the current
   UI location as an untrusted hint.
2. The turn coordinator creates one immutable context snapshot containing only the safe information
   relevant to this turn and emits `CONTEXT_APPLIED`.
3. The configured `AgentSession` gives the model the user's words, kept distinct from trusted context,
   plus the safe prompt projection and approved skills/tools.
4. The model calls `set_engagement_status`. Actor, session, workspace, context, and permission scope
   are already bound by the runtime; the model cannot choose them.
5. The tool adapter calls the same versioned application-core package as the manual REST path. Its
   runtime instance reauthorizes the actor, checks the Yellow-requires-a-reason rule, performs an
   idempotent ETag-safe commit, writes activity, and returns a structured `committed` outcome.
6. The coordinator streams the structured tool result and assistant response through AG-UI, persists
   the turn receipt, and emits exactly one terminal event.
7. The browser reloads the Engagement and may follow the committed canonical destination. The visible
   status comes from the saved record, not the model's sentence.

If the operation is denied, ambiguous, invalid, a no-op, cancelled, or fails, the route stays put and
the actual outcome remains visible. If cancellation races with a commit, CSA Workbench reconciles state and
explains that stopping the response did not roll back already committed work.

## Responsibilities and trust boundaries

| Component | Owns | Must not own or trust |
|---|---|---|
| Web application | User text and UI intent, AG-UI reduction, direct catalog-backed navigation, authoritative-state refresh | Identity, permissions, trusted context, confirmation policy, success inferred from prose or tool name |
| Authenticated orchestrator | Actor authentication, conversation/session ownership, request bounds, validated forwarding, SSE proxy, durable conversation and turn records | Harness SDK behavior, model prompt assembly, domain mutation rules |
| Turn coordinator | Run ID and lifecycle, context composition, harness selection, deadline, cancellation, event normalization, terminal state, receipt correlation | Domain authorization, validation, target resolution, or storage policy |
| `AgentSession` adapter | Model session, safe prompt injection, shared skill/tool registration, harness-event translation | Product rules, durable product state, model-supplied identity, marker-string outcome classification |
| Static prompt and skills | Interpretation guidance and bounded procedures | Authorization, hidden state, durable memory, tool implementation, new capability or permission |
| Bound product-tool adapter | Exact model-visible tool allowlist and runtime binding to actor/session/context/workspace | Independent business rules, global owner state, public/shared-key access, identity in model arguments |
| Shared `workbench_core` package | One versioned implementation of live authorization, validation, strict resolution, confirmation, idempotency, ETag commit, activity, structured outcomes and canonical destinations | Harness-specific policy, UI presentation, or process-local correctness |
| Repositories and stores | Persistence, versions, atomic aggregate replacement, durable bytes and derived indexes | User-visible outcome policy or authorization decisions |
| Trace and receipt sinks | Correlated context, tool, outcome, duration, failure, and terminal evidence | Credentials, unrestricted content, hidden chain-of-thought, or reconstructed success |

The browser and model are intent sources, not authorities. Hard safety boundaries live in runtime tool
allowlists, service authentication, actor/session binding, live application authorization, and data
partitioning. Prompt instructions reinforce those boundaries but never replace them.

## The stable `AgentSession` seam

Only the harness adapter varies between Deep Agents and Copilot. The stable product-facing seam is a
small typed protocol:

```python
class AgentSession(Protocol):
    async def run(self, turn: TurnInput) -> AsyncIterator[AgentEvent]: ...
    async def cancel(self, run_id: str, reason: str) -> None: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class TurnInput:
    run_id: str
    user_text: str
    context_id: str
    prompt_context: PromptContext
```

`PromptContext` is the already-redacted model projection described by
[Context](context.md). It does not contain credentials, effective permissions, raw memberships,
approval material, full record collections, or the trusted tool projection.

The session factory binds model configuration, model authentication, conversation/thread identity,
the shared prompt and skill catalog, the product-tool connection, and the trace writer. Actor ID,
owned conversation/session, workspace, retrieval filters, and `contextId` are bound outside
model-visible arguments. They are not fields the model can alter in `TurnInput` or a tool schema.

The seam intentionally omits:

- SSE strings or HTTP response types;
- raw SDK log paths;
- bearer-token refresh mechanics;
- framework-specific status, session, checkpoint, or callback objects;
- the product application core and repositories; and
- generic plugin or third-harness registration machinery.

An adapter yields typed normalized `AgentEvent` values. The coordinator serializes those events to
AG-UI/SSE and persists their safe receipt projection. This keeps transport framing, terminal
semantics, and timeout behavior out of duplicated harness code.

### Coordinator ownership

For every accepted turn, the coordinator owns:

- generation and correlation of `run_id`, `thread_id`, and `context_id`;
- one immutable context composition before model execution;
- `RUN_STARTED` and `CONTEXT_APPLIED` emission;
- the 300-second initial turn budget and outer-layer grace;
- cancellation propagation and dirty-session disposal;
- normalization of adapter events into the product event contract;
- exactly one terminal `RUN_FINISHED` or `RUN_ERROR` event;
- persistence of a terminal turn receipt even when the client disconnects; and
- authoritative-state reconciliation instructions after tools, failure, cancellation, or unknown
  commit state.

The coordinator may be a logical module inside the existing session runtime. This design does not
require another deployable service.

## Harness selection and parity

`AGENT_BACKEND` accepts exactly `deepagents` or `copilot`. Missing configuration selects
`deepagents`. Any other value fails startup with a clear configuration error. Harness selection is
fixed for a session and recorded on every turn receipt.

There is no automatic fallback. Switching to another harness after a model, tool, transport, or
timeout failure could repeat a mutation, change interpretation, hide an operational defect, or
produce a reply from different conversation state.

### Deep Agents primary

Deep Agents is the deployed release gate. It must pass the complete supported product journey and
failure profile on the Azure reference deployment. Framework-provided planning, shell, arbitrary
filesystem, code execution, and subagent tools are absent from the model-visible allowlist. If the
framework cannot remove them through a supported configuration, the adapter must pin and verify the
small exclusion boundary; their presence is a startup or contract-test failure, not an invitation to
use them.

### Copilot secondary

Copilot implements the same seam and supported CSA Workbench behavior locally. Its failure is recorded and
triaged but does not block a deployed release. It has no product capability that Deep Agents lacks
and cannot introduce a separate prompt, skill, tool, outcome, or UI contract.

### What parity means

Parity requires both harnesses to have:

- the same approved model-visible tool names and JSON schemas;
- the same static prompt and eligible skill catalog versions;
- the same runtime-bound identity and context rules;
- the same application-core authorization, validation, mutation, and outcome behavior;
- the same required AG-UI ordering and terminal invariants;
- the same cancellation and timeout contract; and
- the same observable product effects for the supported local evaluation set.

Parity does not require identical assistant wording, token timing, internal planning, raw SDK event
shape, model request format, or diagnostic reasoning/skill-load events. Optional harness-native
metadata cannot affect routing, state, authorization, success presentation, or release acceptance.

## Prompt, skills, context, and tool composition

The model-facing turn has four distinct inputs. They are composed by the adapter without blending
their authority:

1. **One shared static product prompt.** It defines CSA Workbench's role, commit-before-claim rule, supported
   product boundary, tool-use posture, and concise professional response style. It is small,
   cacheable, versioned, and not copied into each harness source file.
2. **One shared skill catalog.** Approved `SKILL.md` files contain capability-specific procedure and
   use the same source files for both harnesses. Harness adapters may load them differently, but the
   eligible catalog and resulting product behavior remain the same.
3. **One per-turn prompt projection.** The context service supplies safe display identity, validated
   current location and active Engagement, minimal persona, applicable Engagement conventions, and
   small live summaries. It is injected as trusted context, not prefixed to browser-authored user
   text and not checkpointed as user speech.
4. **One product tool allowlist.** Narrow typed tools are loaded from the shared tool adapter. No
   framework built-ins are exposed merely because a harness provides them.

The user's message remains distinguishable from every trusted layer. Conversation checkpoints
preserve conversation continuity only; they are not the source of persona, authorization, durable
memory, current records, context inspector data, or application state. Context is recomposed every
turn, and tools read changing facts live.

Style precedence is `turn instruction > applicable Engagement convention > persona > application
default`. Authorization and live facts are not part of that precedence: authorization is an absolute
ceiling, and current permissioned records override remembered or prompt-projected facts.

Skills are procedures, not agents. A skill may explain how to use already approved tools but cannot
add tools, widen scope, store hidden memory, bypass confirmation, or turn one request into an
unapproved autonomous workflow. The existing multi-step weekly-review routine is excluded from the
supported catalog. Skill-load and model reasoning-summary events are diagnostic-only and are not
rendered as evidence of product work. Hidden chain-of-thought is never requested, streamed, stored,
or exposed.

If an optional context source such as persona or conventions is unavailable, composition records an
explicit omission and the turn may proceed with safe defaults. Failure to establish authenticated
actor/session ownership or a valid trusted tool binding stops the turn.

## Shared application core and product tools

`workbench_core` is the one implementation of CSA Workbench behavior, imported into two process boundaries:

```text
Orchestrator: manual UI -> REST adapter ---------> local workbench_core instance -> repositories
Runtime:      agent -> bound csa-workbench-tools tool -> local workbench_core instance -> repositories
                                      same package, schemas, outcomes, and contract version
```

The package owns live membership and role checks, target and scope resolution, schemas and cross-field
validation, confirmation policy, idempotency, ETag retry behavior, activity, durable receipts, and
structured outcomes. A concurrency retry re-reads the aggregate and rechecks authorization, target,
validation, and confirmation before commit.

REST handlers call the orchestrator instance directly. The model-facing adapter exposes narrow
capability tools such as `list_engagements`, `set_engagement_status`, `create_task`, and
`save_artifact_to_engagement`; it delegates immediately to the runtime instance and contains no
independent mutation policy. There is no application-service HTTP callback and REST never calls MCP.

Both workload images carry the same Git revision and `workbench_core` contract version. The orchestrator
checks that version when establishing a runtime session, refuses a mismatch, and records it in the
turn receipt. ETags and same-aggregate idempotency receipts preserve correctness across the two
instances. Actor/session context is bound independently at each adapter and every operation
reauthorizes live state; the package contains no manual-versus-agent policy branch.

### Internal `csa-workbench-tools` adapter and MCP direction

The logical tool adapter is named `csa-workbench-tools`. Tool names remain product capability names; they
are not prefixed with `deepagents_`, `copilot_`, or `mcp_`. Traces record the adapter and harness in
separate fields.

The adapter is session-bound. Actor, owned conversation/session, workspace, retrieval scopes, and
`contextId` are supplied through trusted runtime binding rather than model arguments. The v1
baseline is an in-process typed adapter calling the runtime's local `workbench_core` instance. A later
session-bound stdio MCP wrapper may expose the same schemas when harness portability evidence
justifies the extra process, but it cannot add policy, credentials, or a public endpoint. MCP remains
a replaceable protocol adapter, not the domain layer or an architectural requirement for REST.

The legacy remote `flow-appstate` MCP server is outside this architecture. Its shared-key,
global-owner, remotely reachable posture is incompatible with CSA Workbench's actor-bound application
contract. It should be retired rather than adapted into the harness substrate. This capability does
not authorize an external MCP endpoint or an IDA bypass path.

## AG-UI event contract

AG-UI is the normalized semantic event protocol. SSE is only its current browser transport. One turn
has this required shape:

```text
RUN_STARTED
CONTEXT_APPLIED
  TEXT_MESSAGE_START -> TEXT_MESSAGE_CONTENT* -> TEXT_MESSAGE_END
  TOOL_CALL_START -> TOOL_CALL_ARGS* -> TOOL_CALL_RESULT -> TOOL_CALL_END
  ...text and tool groups may repeat...
RUN_FINISHED | RUN_ERROR
```

The first two events precede model or tool output. Text is associated with stable message IDs. Every
started product tool call has one structured result and one end event. If failure or cancellation
interrupts a call before its outcome is known, the coordinator closes it with a structured `failed`
result whose commit state is unknown and requires reconciliation. Exactly one of `RUN_FINISHED` or
`RUN_ERROR` terminates the run. A clean stream close without a valid terminal event is an error.

Malformed required frames, invalid ordering, duplicate terminal events, unknown required schema
versions, and truncated UTF-8/SSE frames fail loud. The orchestrator parses framed event types; it
does not search raw bytes for strings such as `RUN_ERROR`. The browser ignores only explicitly
forward-compatible optional events and must surface corruption of a required event.

`REASONING_*`, `SKILL_LOADED`, or equivalent harness-native events are optional diagnostics outside
the product parity contract. They are not success evidence and are not required by the frontend.

### `CONTEXT_APPLIED`

`CONTEXT_APPLIED` carries the safe inspector projection produced by the context composer, including
`context_id`, snapshot time, effective scope and reason, applied items, omitted/degraded sources, and
freshness. It never carries the trusted tool projection, credentials, hidden policy, raw visit
history, inaccessible names, or chain-of-thought. The UI's **What I used** view renders this stored
projection rather than reconstructing context from current browser or database state.

### Structured `TOOL_CALL_RESULT`

The tool result mirrors a safe projection of the application-core outcome. It is not inferred by
parsing a leading marker from prose:

```json
{
  "type": "TOOL_CALL_RESULT",
  "tool_call_id": "call-7",
  "result": {
    "status": "committed",
    "code": "engagement.status_changed",
    "operation": "update",
    "scope": {"kind": "engagement", "id": "eng-42"},
    "resource": {"kind": "engagement", "id": "eng-42", "version": "etag-9"},
    "destination": {
      "id": "destination:engagement:eng-42:overview",
      "title": "Northstar",
      "route": "/engagements/eng-42"
    },
    "audit_id": "activity-81"
  }
}
```

The core statuses are `committed`, `noop`, `needs_confirmation`, `ambiguous`, `invalid`,
`not_found`, `forbidden`, `conflict`, and `failed`. Read and navigation contracts may use
`succeeded` and `resolved` where no domain mutation occurs. Optional typed fields carry authorized
candidates, field errors, confirmation previews and IDs, retry guidance, citations, or an unknown
commit-state warning.

Only `committed` or `resolved` may carry a canonical destination that can move the UI. The browser
does not maintain a list of tool names assumed to set routes. `failed` with unknown commit state
forces a refetch before the assistant or UI can state what happened.

## Cancellation and timeout

The coordinator's initial per-turn budget is 300 seconds. Orchestrator transport and browser
inactivity watchdogs use that same configured budget plus a small outer grace so the coordinator,
not a client timer, normally emits the terminal error. Model connection/startup and file upload have
their own bounded operations; they do not silently extend the turn deadline.

Stop follows one path:

1. The browser aborts its stream and marks later buffered presentation effects invalid.
2. The orchestrator closes the upstream stream and preserves the owned conversation/run identity.
3. The coordinator cancels the run task and calls `AgentSession.cancel(run_id, "user")`.
4. The adapter interrupts the harness and waits for it to become idle within a short grace period.
5. If a clean stop cannot be proven, the coordinator closes and recreates that harness session before
   accepting another turn.
6. The receipt records `cancelled`, any known tool outcome, and whether authoritative reconciliation
   is required.
7. The browser refetches authoritative state and keeps the route in place.

Timeout uses the same cancellation path with reason `timeout` and ends in one `RUN_ERROR`. New
conversation waits for cancellation and session teardown rather than racing a new run against the old
one. Session-level serialization prevents two active turns for one conversation; ETag and idempotency
remain necessary because different sessions or retries may act on the same Engagement.

Cancellation is not rollback. A tool that already returned a committed receipt remains committed,
even if the user stops before assistant prose arrives. A tool still running when cancellation occurs
must either return a known outcome or leave the turn in unknown commit state until authoritative
refetch and receipt reconciliation. Buffered navigation effects from a cancelled turn are never
applied.

## Trace and turn receipts

CSA Workbench keeps two related evidence channels:

- a user-retrievable durable turn receipt in Cosmos for product evidence; and
- operational traces in Azure Monitor or local structured logs for diagnostics.

The normalized coordinator event and application-core outcome are the canonical evidence. Raw SDK
event logs are optional adapter diagnostics and never a release oracle.

A turn receipt contains, subject to safe redaction:

- actor, conversation, thread, run, context, and harness identifiers;
- `workbench_core` contract, static prompt, skill catalog, context, event, and tool schema versions;
- context snapshot time plus the applied/omitted inspector projection or its durable reference;
- model deployment and adapter, without credentials;
- each product tool name and call ID, safe arguments, start/end times, structured status/code,
  resource version, idempotency receipt, activity/audit ID, and duration;
- citations or grounded source identifiers when a read depends on documents;
- cancellation, timeout, transport, context, and application failure reason codes;
- terminal state and whether authoritative reconciliation succeeded; and
- total latency and token/usage data when safely available.

Arguments and results have distinct model, UI, receipt, and operational projections when their
sensitivity differs. Do not store bearer tokens, passwords, confirmation secrets, unrestricted
documents, hidden tool context, inaccessible resource names, raw membership collections, or hidden
chain-of-thought. Full user text and raw SDK payload capture is off by default and requires an
explicit short-lived diagnostic mode with access and retention controls.

Trace writes must not be split among independent processes appending incompatible JSON shapes to the
same file. Local JSONL and Azure Monitor may use different sinks, but they derive from the same typed
coordinator/tool events and correlation IDs. Receipt persistence failure is visible: the product does
not advertise a retrievable trace when it did not save one.

## Failure contract

| Failure | Required behavior |
|---|---|
| Unknown harness name or tool inventory drift | Fail startup or the harness contract check; never silently select another backend |
| Model authentication, rate limit, filter, or provider failure | Emit one safe `RUN_ERROR`, persist reason, reconcile any started tools, offer retry where safe |
| Optional persona/convention source unavailable | Emit an explicit omitted/degraded context item and continue with safe defaults |
| Actor/session binding or authorization context unavailable | Stop before model/tool execution; do not degrade identity |
| Tool returns `noop`, `ambiguous`, `invalid`, `not_found`, or `forbidden` | Preserve exact structured status; no success language or route effect |
| Confirmation required | Return a backend-issued actor-bound preview and confirmation ID; do not ask a model to convert “yes” into authority |
| ETag conflict | Re-read and recheck all dependent rules; return `conflict` after bounded retries rather than last-write-wins |
| Tool transport fails before commit is known | Mark commit state unknown, suppress route effects and success claims, then refetch/reconcile |
| Client disconnects or presses Stop | Continue coordinator cleanup and receipt persistence; cancel harness; refetch state; never imply rollback |
| Turn exceeds 300 seconds | Cancel, dispose an unclean harness session, emit one timeout `RUN_ERROR`, persist terminal receipt |
| Upstream stream truncates or required event is malformed | Fail loud with a normalized stream error; do not leave the UI indefinitely Working |
| State or receipt refresh fails after a claimed commit | Show stale/unknown freshness and retry; do not let assistant prose stand in for state |
| Raw diagnostic logging fails | Preserve product execution but report observability degradation; durable receipt requirements remain enforced |

## Behavioral oracles

Harness verification reconciles three observations: the real UI, authoritative product state, and
the durable turn receipt. Exact assistant prose is not an oracle.

### Contract evidence

- Both adapters consume the same prompt, skill catalog, product-tool schema, and typed turn fixture.
- Required event ordering, message/tool correlation, UTF-8 framing, one-terminal behavior, malformed
  frame failure, and context-before-model ordering are asserted independently of an SDK.
- Unknown backend values fail closed, and both model-visible tool inventories exactly match the
  approved shared allowlist with no shell, code, arbitrary filesystem, planning, or subagent tools.
- Structured tool outcomes survive adapter and AG-UI translation without marker parsing or loss of
  status, destination, confirmation, error, citation, or receipt fields.

### Behavioral evidence

- Deep Agents passes the complete deployed Azure journey: identity isolation, membership trimming,
  viewer read-only behavior, Yellow/Red reason validation, task and artifact operations, grounded
  reads, deterministic navigation, context inspection, receipt retrieval, and deliberate tool
  failure.
- Copilot passes the same supported journey locally against the same repeatable seed, application
  service, and frontend. A failure is reported but does not block deployment.
- Every mutation assertion checks the resulting record/version in authoritative state and the
  matching committed receipt. Every non-commit assertion proves state and route did not change.
- Repeated create delivery with the same idempotency receipt produces one resource and one activity
  record.
- Concurrent updates reauthorize and revalidate after ETag conflict; unsafe ambiguity ends as
  `conflict` rather than silently overwriting newer state.
- **What I used** equals the stored `CONTEXT_APPLIED` projection, and trusted actor/session/tool
  bindings are absent from model-visible tool arguments.

### Failure and recovery evidence

- Deliberately failing, no-op, ambiguous, invalid, not-found, forbidden, and confirmation-required
  tools are never shown or narrated as committed.
- Cancellation is exercised before a tool, during a tool, after commit but before assistant prose,
  during streaming text, and during rapid New Conversation. Buffered routes do not apply, state is
  reconciled, and already committed work remains visible.
- Timeout, provider failure, token expiry, context-source degradation, tool transport loss, malformed
  SSE, truncated stream, receipt-write failure, and post-tool state-refresh failure all end visibly
  with one terminal event and an appropriate receipt/degradation signal.
- Raw Deep Agents and Copilot event sequences may differ, but their normalized product events,
  structured outcomes, state effects, and receipts satisfy the same assertions.

## Simplifications and non-goals

- Two explicit adapters and one factory are enough; there is no generic harness plugin platform.
- Deep Agents is primary and Copilot is secondary; there is no automatic or mid-turn fallback.
- No shell, arbitrary code execution, autonomous subagents, planning tool, generic filesystem, or
  multi-agent workflow is exposed.
- No weekly-review-style autonomous multi-mutation routine is part of the approved skill catalog.
- MCP is an optional internal tool transport, not the application core, public API, durable state,
  authorization boundary, or prerequisite for manual REST.
- The legacy shared-key `flow-appstate` MCP path is retired rather than preserved through a
  compatibility shim.
- Context is not a durable memory system, and a conversation checkpoint is not product state.
- Reasoning summaries and skill-load notifications are diagnostics only; hidden chain-of-thought is
  never collected or exposed.
- Harness parity does not require identical prose, token cadence, raw SDK events, or framework
  internals.
- This capability does not add an IDA integration, public MCP endpoint, connector platform,
  scheduler, workflow engine, third harness, or speculative autonomy.

## Current integrated state versus target

The integrated baseline contains a useful seam and substantial proof, but static inspection shows
that the target contract is not implemented yet. Runtime behavior at this baseline remains
**UNVERIFIED** unless supported by separately current behavioral evidence.

| Current evidence at `master@1fcaac6` | Target gap |
|---|---|
| `session-container/server.py:33-41` selects Deep Agents by default but treats every other string as Copilot; `master@1fcaac6:docs/development.md:53-80` and `master@1fcaac6:README.md:37-45` still describe Copilot as default | One exact fail-closed selector and Deep-primary documentation/configuration |
| `master@1fcaac6:docs/harnesses.md:15-38` and both current classes expose a seam whose `send()` yields already formatted SSE and whose token/raw-log properties are consumed by the server | Typed `run/cancel/aclose`; coordinator-owned lifecycle, transport, token refresh, and logs |
| `session-container/agent.py:82-177` and `agent_deepagents.py:95-189` duplicate a large system prompt | One shared small versioned static prompt |
| Copilot loads `session-container/skills/` at `agent.py:1304-1339`; Deep setup at `agent_deepagents.py:1152-1161` does not load the shared catalog | One approved catalog and parity evidence; weekly-review routine excluded |
| Product tools are duplicated across `agent.py:473-1214` and `agent_deepagents.py:313-1043` | Thin shared `csa-workbench-tools` adapter over the runtime instance of one `workbench_core` package |
| Tool status, cards, and navigation chips are parsed from marker text in `agent.py:245-302` and `agent_deepagents.py:248-293` | Native structured service outcome preserved through AG-UI |
| `frontend/src/hooks/useAgentSession.ts:484-506` fetches a context bundle, creates bracketed prompt text in the browser, and sends it as part of the prompt | Server-side immutable composition; user text separate; stored `CONTEXT_APPLIED` |
| `frontend/src/components/AssistantPanel.tsx:129-142` renders the fetched bundle rather than the event actually supplied to the harness | Inspector renders persisted event projection |
| `frontend/src/hooks/useAgentSession.ts:9-24,441-456` infers route following from `outcome === "ok"` and a hard-coded tool-name set | Follow only an explicit structured committed/resolved destination |
| Both adapters can emit `RUN_ERROR` followed by `RUN_FINISHED` (`agent.py:1512-1525`; `agent_deepagents.py:1265-1276`) | Coordinator emits exactly one terminal event |
| `session_manager.py:252-280` detects terminal events by searching raw text chunks for `RUN_FINISHED` or `RUN_ERROR` | Parse framed typed events and validate ordering/schema |
| `frontend/src/lib/sse.ts:63-95` silently drops malformed data frames | Corruption of required events fails loud |
| Copilot aborts an active SDK turn in `agent.py:1527-1567`; the Deep POC records unproven cancellation at `review/2026-06-24-deepagents-poc/FINDINGS.md:127-142`; frontend Stop at `useAgentSession.ts:559-565` does not itself reconcile state | One tested coordinator cancellation path and post-stop authoritative refetch |
| Session agent trace helpers emit only when logger `trace` has a handler (`agent.py:59-79`; `agent_deepagents.py:68-82`), while `session-container/trace_logging.py:19-56` prepares a path without installing that handler | One typed trace/receipt pipeline with reliable correlation and retrieval |
| `session-container/server.py:266-273` logs a prompt preview and raw SDK records may store the full prompt | Safe receipt projections; full prompt/raw capture off by default |
| `mcp_server.py:1-15,178-200` defines a shared-key global-owner remote server and its tools call removed global `appdb.load/update` APIs | Exclude and retire; do not use as the actor-bound harness substrate |

The smallest dependency-ordered migration is:

1. establish the shared application-core package and structured outcomes;
2. establish immutable actor/session binding, server-side context, and durable turn receipts;
3. introduce coordinator-owned typed events and the `AgentSession.run/cancel/aclose` seam;
4. connect Deep Agents to the shared prompt, approved skills, and bound `csa-workbench-tools` adapter;
5. connect Copilot to the same contracts and remove duplicated tools/prompts/marker parsing; then
6. prove deployed Deep behavior and local Copilot parity with the oracles above.

This sequence keeps framework replacement subordinate to product truth and avoids building protocol
layers before the application core has one authoritative behavior to expose.
