# Session and state

> **Authority:** Capability detail subordinate to the [authoritative design](../design.md)
>
> **Deployed application revision:** `807a0d6766036aa88dce8dcd9f16a2aabeb187b3`
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## What a CSA can count on

An agent session is a temporary working conversation, not the product record. It remains usable only
while the owning API process and runtime state remain alive. If either is replaced, CSA Workbench
creates a new session and reloads the actor's durable product state.

The durable boundary is the Engagement:

- Cosmos DB keeps actors, personal state, Engagement aggregates, membership, artifact metadata, and
  activity.
- Blob Storage keeps Engagement artifact bytes.
- The API process keeps session ownership.
- The runtime process and its filesystem keep chat continuity, uploads, generated drafts, harness
  memory, and locks. API/runtime filesystems may also keep optional local traces.
- The browser keeps the current session ID and completed visible messages in actor-namespaced
  `sessionStorage`.

Consequently, an API or runtime replacement does not remove an Engagement, its members, or its
committed artifacts. It can remove the conversation, chat uploads, generated working files, and
trace files. The MVP does not promise durable conversations, server-side transcripts, checkpoints,
turn receipts, resumable streams, or upload promotion.

## State boundary

| State | Current owner | Lifetime |
|---|---|---|
| Actor profile and personal workspace | Cosmos DB | Durable across sessions and compute replacement |
| Engagement record, membership, tasks, conventions, artifact metadata, activity | Cosmos DB | Durable across sessions and compute replacement |
| Engagement artifact bytes | Blob Storage in the Entra deployment | Durable across sessions and compute replacement |
| Session ID and actor binding | API and runtime process maps | Lost when the relevant process is replaced |
| Harness conversation | Live `AgentSession`; Deep Agents uses `InMemorySaver` | Lost with the runtime session or process |
| Chat upload, generated file, upload manifest | Per-session runtime workspace directory | Ephemeral filesystem state |
| Completed chat shown after a same-tab reload | Browser `sessionStorage` | Browser-tab state, not server truth |
| Structured and raw trace JSONL | Local process filesystem when tracing is enabled | Optional and ephemeral; no user-retrievable receipt |
| Per-session turn and manifest locks | Runtime process memory | Process-local only |

Cosmos updates to personal and Engagement documents use optimistic ETag replacement with bounded
retry. That protects durable aggregate writes from lost updates; it does not make a chat, stream, or
session durable and is not a command-idempotency receipt.

## Session lifecycle

### Create and bind

`POST /sessions` requires the configured user authentication. The API generates a 16-character
opaque ID and asks the runtime to create that session with the authenticated actor in the internal
`X-User-Id` header. The runtime creates the workspace and records a write-once
`session ID -> actor ID` binding. Only after runtime creation succeeds does the API record the same
owner in its process-local maps and return `201`.

The workspace is created immediately; the harness is initialized lazily on the first turn. Neither
session map is written to Cosmos.

### Own and validate

Every session-scoped API route first probes the runtime and compares the authenticated actor with
the API's owner map. An unknown session, an owner mismatch, and a session whose API owner binding was
lost all return `404`, so another actor cannot use a guessed ID to learn that a session exists.

The runtime separately checks its write-once actor binding for chat and file calls. A different
forwarded actor receives the same `404`, without changing or deleting the original session. If a
runtime restart leaves an old workspace but loses its actor map, the runtime fails closed rather
than allowing the workspace to be claimed.

There is no session-list or server-side conversation-history API. On page initialization, the
frontend checks the actor's stored session ID. A live session restores the browser's completed
messages and reloads files plus authoritative Cosmos state. A genuine `404` clears the stored chat
and creates a new session. A timeout, network failure, or `5xx` keeps the stored ID and shows Retry;
it is not treated as proof that the session disappeared.

### Delete, reset, and New session

`DELETE /sessions/{id}` first checks ownership, removes the API's in-memory binding, and makes a
best-effort runtime delete. The runtime serializes cleanup with the turn lock, destroys the harness,
and removes the session workspace. Runtime cleanup failure is logged but does not change the API's
`204` response; this is cleanup, not a durable deletion receipt.

The runtime also has an internal reset operation that destroys the harness and workspace, then
recreates an empty directory under the same actor binding. It does not reset Cosmos or Blob.

The UI's **New session** action aborts its active stream, best-effort deletes the old session, clears
conversation-local UI and browser state, creates a new session, then reloads the actor's durable
personal and Engagement state. It intentionally does not delete personal records, Engagements,
membership, activity, or committed Engagement artifacts. The old conversation and its workspace
are not retained as a resumable history.

## Runtime trust boundary

The deployed runtime has internal ingress and `WORKLOAD_AUTH_MODE=entra`. Before it accepts the
forwarded actor header, middleware validates an API managed-identity bearer token for the configured
tenant, runtime audience, API caller object ID, and `invoke` application role. The API obtains that
token for HTTPS runtime calls. Only `/health` is exempt.

Local plain-HTTP development explicitly runs without workload-token authentication. That local
profile does not weaken the deployed boundary. In both profiles, the actor is bound by server code
and supplied to product tools outside model-selected arguments; a model cannot select a different
actor by changing the prompt or a tool parameter.

## Turns, streaming, and concurrency

The frontend prevents overlapping sends from one UI with synchronous in-flight and streaming
guards. The runtime is authoritative: it keeps one `asyncio.Lock` per session, acquires it before the
SSE generator starts, and immediately returns `409 Session is busy` if another turn already owns the
lock. Locks remain in that runtime process for its lifetime so reset cannot replace a lock while an
older turn still holds it. Different sessions can proceed independently.

The API proxies typed AG-UI events and validates their order. A stream must begin with
`RUN_STARTED`, keep message and tool lifecycles correlated, and end with one valid `RUN_FINISHED` or
`RUN_ERROR`. The proxy holds the terminal event until clean upstream EOF. A malformed, truncated, or
unterminated stream receives synthetic closure events where possible and a `RUN_ERROR`; raw stream
text is never searched for success markers.

The runtime applies a per-turn timeout, 300 seconds by default. Timeout or runtime failure destroys
the live harness, emits `RUN_ERROR`, and releases the session lock. The workspace remains unless the
session is reset or deleted.

**Stop is a client-side stream abort.** The UI ignores later buffered events and makes input usable
again. There is no public cancel endpoint, cancellation acknowledgement, or durable cancelled state.
The Copilot adapter attempts to abort its SDK turn when its generator closes. The deployed Deep
Agents adapter has no explicit cancellation acknowledgement; closing the active async stream is its
only propagation path. A tool mutation that committed before disconnect remains committed, and Stop
itself does not prove whether the server stopped before or after that commit. The next authoritative
state read is the only product truth. Streams cannot be resumed.

This coordination is valid only with one live API process and one live runtime process. The current
deployment enforces minimum `0` and maximum `1` replica for frontend, API, and runtime. There is no
distributed lease, shared session registry, cross-replica routing, durable turn queue, or recovery
coordinator. Increasing API or runtime replicas would break the ownership and locking assumptions
and is outside the MVP.

## Workspace and upload limits

Each runtime session uses a server-chosen directory below `WORKSPACE`. Chat uploads and converted
working files are written there, and generated drafts use the same ephemeral space. The upload
manifest records whether a visible file was uploaded or generated; a separate process-local lock
serializes manifest changes.

These files are not Engagement artifacts. Only the Engagement artifact API creates durable
Engagement bytes in Blob and commits their metadata in Cosmos. Starting a new session, runtime
scale-in, or revision replacement may remove session files without affecting already committed
Engagement artifacts.

The session runtime does not reconstruct chat, uploads, or generated files after replacement. It has
no transcript or workspace rehydration source. Browser messages can repaint a same-tab history, but
they do not restore harness memory and are not replayed into a new agent session.

## Failure and recovery

| Condition | Current behavior and limit |
|---|---|
| Stored session still exists | Same-tab reload restores browser messages and refreshes files plus Cosmos state |
| API process replaced or scaled to zero | API owner map is gone; the old ID fails ownership and the UI creates a new session |
| Runtime process/workspace replaced or scaled to zero | Runtime session, actor map, harness memory, uploads, drafts, and local traces are gone; the UI creates a new session |
| Old workspace exists without runtime actor binding | Runtime returns `404` and fails closed; it does not rebind the workspace |
| Runtime cold start | Session creation waits for the runtime; the cost-minimized deployment accepts the delay |
| Runtime unavailable or creation times out | UI shows a retryable session error; durable Cosmos/Blob data remains, but session-gated UI/API work waits for a valid new session |
| Cosmos unavailable | Durable reads and writes fail; the session does not become an alternative state store |
| Stream timeout or malformed upstream lifecycle | UI receives `RUN_ERROR`; there is no durable receipt or resumable cursor |
| Browser disconnect or Stop | Client observation ends; server cancellation and commit status are not durably acknowledged |
| Runtime delete cleanup fails | API binding is removed and cleanup is logged; residual runtime files are not a promised retrievable session |

The `0-1` replica profile therefore gives zero idle compute and accepts cold starts, but it also
makes replacement visible as a new conversation. Durable product state can be reloaded only after a
new actor-bound session is established; the current manual APIs are also session-gated.

## Evidence and precise gaps

The [authoritative design](../design.md) records that the deployed application revision passed
real-Entra session creation, authoritative Engagement readback, and a typed Deep Agents turn. It also
records an observed scale-to-zero cold start of roughly 24 seconds. The checked-in infrastructure
contract fixes all three Container Apps at `0-1` replicas, and focused tests cover workload-token
validation, write-once runtime actor binding, fail-closed orphan workspaces, cross-actor file denial,
structured stream lifecycle validation, and the replica limits.

The repository does not contain a release-candidate behavioral record that deliberately replaces
the API/runtime and captures both session loss and durable Cosmos/Blob survival. A historical
[ACA Dynamic Sessions test](../../review/aca-state-test.md) confirmed that workspace state persisted
only within a live sandbox and was destroyed on cooldown, but it used the former Dynamic Sessions
topology and is not proof of the current plain Container Apps deployment.

Current MVP gaps are intentionally narrow:

- no durable conversation list, transcript, chat upload, checkpoint, turn receipt, or trace store;
- no explicit server cancellation result or interrupted-turn reconciliation;
- no resumable SSE cursor and no automatic replay of a lost turn;
- no rehydration of harness memory or workspace files after process replacement; and
- no safe multi-replica session ownership or turn exclusion.

Those gaps define the MVP boundary; they are not hidden future requirements.
