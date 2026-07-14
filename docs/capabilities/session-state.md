# Session and State Capability

> **Authority:** Canonical capability detail subordinate to [CSA Workbench — Authoritative Product and System Design](../design.md)  
> **State:** Reference direction; the MVP requires correct actor/session isolation but does not require the full durable-conversation design
>
> **Applies to:** Conversation ownership, durable state, rehydration, runtime coordination, and compute lifecycle  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## The short version

The MVP release bar requires that one CSA cannot use another CSA's session and that scale-to-zero
does not lose Engagement data. Full transcript rehydration, durable private chat uploads, turn
receipts, and draft promotion are documented below as reference patterns, not as implied MVP scope.

CSA Workbench separates the place where work is kept from the compute that temporarily helps with it:

- **Cosmos is the filing cabinet.** It owns structured records: actors, personal state,
  Engagements, conversations, messages, upload metadata, and turn receipts.
- **Blob is the file room.** It owns durable bytes: private conversation files and shared
  Engagement artifacts.
- **The session runtime is a rented desk.** It may hold a warm agent, materialized files, caches,
  and scratch while a turn runs. The desk may disappear at any time.

The product rule is that losing the rented desk must not lose anything the user reasonably expects
to resume. A conversation is therefore an actor-owned product record, not a container identity. It
can be reopened after a browser refresh, process restart, scale-in, or cold start. Compute rebuilds
from Cosmos and Blob; it never becomes the system of record.

Conversations remain private even when they are associated with an Engagement. Uploading or drafting
inside an Engagement-scoped conversation does not share the file. Sharing is a separate, explicit
**Save to Engagement** action that creates an Engagement artifact under current membership and role
rules.

## Product promises

This capability makes six promises to the user:

1. **Resume means resume.** The conversation list, visible messages, durable private uploads, and
   behavior receipts survive loss of browser or agent compute; an unsaved generated draft is clearly
   excluded from that promise.
2. **Private stays private.** A conversation and its files belong to one authenticated actor. An
   Engagement association supplies context, not access for other members.
3. **Sharing is deliberate.** Only an explicit successful promotion creates a shared Engagement
   artifact.
4. **New is not reset.** Starting a new conversation does not delete the previous conversation and
   never resets personal records, Engagement records, or shared artifacts.
5. **One turn at a time.** A conversation cannot run two overlapping turns. Competing sends fail
   visibly rather than racing or queuing invisibly.
6. **Failure leaves evidence.** An accepted turn has a durable receipt and exactly one honest
   terminal state, including failure, cancellation, interruption, or unknown commit state.

## State taxonomy and ownership

State is classified by who owns it and what loss would mean. Storage technology follows that
classification rather than the lifecycle of an agent framework.

| State | Owner and visibility | System of record | Runtime responsibility |
|---|---|---|---|
| Actor identity and minimal persona | One authenticated actor | Cosmos actor record | Receive a trusted projection; never infer identity |
| Personal tasks, preferences, and working context | One actor | Cosmos personal records | Read live through permissioned application services |
| Engagement, membership, status, tasks, conventions, and activity | The Engagement; current members are role-gated | One Cosmos Engagement aggregate/partition | Read and mutate only through live authorization and ETag checks |
| Conversation metadata and product-visible transcript | One actor; optionally tagged to an Engagement | Cosmos conversation aggregate | Keep a warm copy and rehydrate it on demand |
| Turn context and behavior receipt | The conversation owner | Cosmos, attached to the conversation in v1 | Emit normalized events and terminal state; do not rely on raw runtime logs |
| User uploads | One conversation owner | Blob bytes plus Cosmos conversation metadata | Materialize only the uploads needed by the active conversation |
| Generated working drafts | One conversation owner while the runtime exists | None until **Keep in Personal Library** or **Save to Engagement** commits | Scratch; label as unsaved and safe to lose |
| Engagement artifacts | The Engagement | Blob bytes plus Engagement metadata in Cosmos | Use only after an explicit, authorized promotion |
| Search documents or indexes | Derived from an authorized durable source | Optional, rebuildable projection | Never broaden the source scope; absent from the baseline |
| Harness memory, framework checkpoint, caches, conversions, and intermediate files | No durable product owner | None | Ephemeral cache or scratch; safe to discard |
| Runtime locks and active stream handles | One running process | None in v1 | Coordinate the active turn under the single-replica deployment constraint |

The private conversation Blob namespace holds user uploads, not ordinary generated drafts. A draft
may be visible in the artifact canvas while it remains explicitly labelled **Private working draft ·
not saved**. It becomes durable only through **Keep in Personal Library** or **Save to Engagement**,
which create a new durable document in the selected scope. Losing runtime scratch makes an unsaved
draft unavailable; the transcript and receipt may record that it existed but never imply the bytes
can be resumed.

## Durable conversation record

For v1, one Cosmos conversation aggregate is the simple source of truth. It is not an event-sourcing
system and does not mirror every raw SDK event. Its logical shape is:

```text
Conversation
  id
  ownerActorId
  engagementId?          # context association only
  title
  status                 # active | archived
  createdAt, updatedAt
  messages[]             # product-visible user and assistant messages
  files[]                # durable private user-upload metadata and provenance
  turns[]                # bounded behavior receipts
  version / ETag
```

Each message has a stable ID, role, timestamp, and product-visible content. Each durable conversation
file has a stable file ID, safe display name, content type, size, Blob key, `uploaded` origin, and
creation attribution. Filenames are labels, not identity; two same-named files do not overwrite one
another. Unsaved generated drafts are not entries in `files[]`.

Each turn receipt contains:

- stable conversation, turn, and input-message IDs;
- accepted, started, and terminal timestamps;
- the stored safe `CONTEXT_APPLIED` inspector projection or its durable reference;
- normalized tool names, structured outcomes, and affected stable record IDs;
- output-message ID when one exists; and
- exactly one terminal state: `completed`, `failed`, `cancelled`, `interrupted`, or
  `unknown_commit`.

The receipt deliberately excludes credentials, hidden chain-of-thought, complete prompts containing
trusted runtime projections, and unbounded raw SDK telemetry. Azure Monitor remains useful for
operations, but it does not replace the user-retrievable receipt.

The aggregate is bounded as a product record. V1 may apply an explicit conversation-length or file
count limit and must fail before a Cosmos document limit is reached. It does not add transcript
sharding, an archive service, or an event store before measured need.

## Conversation privacy and actor binding

Conversation ownership is established only from authenticated backend state:

1. Creation writes `ownerActorId` from the validated Entra or synthetic demo identity.
2. Listing filters by that actor.
3. Read, resume, append, upload, archive, and promotion first load the conversation and compare its
   owner with the authenticated actor.
4. An absent conversation and another actor's conversation return the same not-found behavior.
5. The browser, model, and model-visible tool arguments never supply an authoritative actor ID.

`engagementId` is a context tag, not an access-control list. Other Engagement members cannot list or
open the conversation. On every turn, CSA Workbench rechecks whether the actor can still see the associated
Engagement before using its conventions or facts. Losing membership removes that Engagement context
and blocks later promotion; it does not transfer or expose the private conversation.

The orchestrator binds the authenticated actor, conversation ID, context ID, and workspace outside
model-visible arguments. The internal runtime accepts that trusted binding from the orchestrator and
does not rebind a live conversation because a caller supplied a different header.

## Conversation lifecycle

### Create and list

Creating a conversation first creates its Cosmos record and returns its durable ID. It does not wake
the session runtime. Listing or opening conversation history is an application-data operation and
must also work while agent compute is at zero.

The dock and full workbench are two views of the same selected conversation. Moving between them,
collapsing the dock, navigating the host application, or resizing the viewport does not create a new
conversation or cancel a turn.

### Upload and private draft

An upload follows bytes-first, metadata-second ordering:

1. Authorize the actor-owned conversation and mint a file ID.
2. Store the original bytes in the conversation's private Blob prefix. Store a reusable converted
   representation there too when document conversion is required for later rehydration.
3. Append file metadata to the conversation with an ETag-protected update.
4. Surface the file only after metadata commits.

A metadata failure may leave an inaccessible orphan for later cleanup; it never creates a listed
file with missing bytes.

A generated draft stays in runtime scratch and the UI labels it unsaved. **Keep in Personal
Library** copies it to the actor's durable private document scope; **Save to Engagement** copies it
to the authorized shared artifact scope. There is no implicit “durable conversation draft” state in
v1.

### Start a turn

A turn uses this order:

1. Authenticate the actor and authorize the conversation.
2. Reject the request with `409 conversation_busy` if that conversation already has an active turn.
3. Validate the UI destination and compose one immutable trusted turn context on the server.
4. Persist the user message and a `started` receipt before invoking model compute.
5. Cold-start or reuse the runtime, rehydrate transcript and needed files, and invoke the selected
   `AgentSession` adapter.
6. Persist the safe context projection and normalized tool outcomes as the turn progresses.
7. Persist the assistant message when present, choose exactly one terminal state, and release the
   in-process conversation lock.
8. Re-read authoritative application state before displaying any claimed mutation as complete.

The user's message remains distinct from trusted context. Resume never replays an old context
snapshot as current authority; the context composer reads current identity, membership, and live
records for every new turn.

### Stop, disconnect, and retry

Stop requests cancellation from the runtime and marks the receipt `cancelled` only when cancellation
is known. A browser disconnect does not prove cancellation. The coordinator attempts to finish or
cancel the runtime operation, reconciles authoritative state, and records `interrupted` or
`unknown_commit` when the result cannot be established.

Already committed tool mutations are never rolled back merely because streaming stopped. Retrying a
turn does not automatically replay a destructive or mutating tool call. The UI first refetches state
and shows the stored receipt so the user can choose a safe next action.

### Resume and rehydration

Resume is deterministic reconstruction, not recovery of a particular container:

1. Load the actor-owned conversation, transcript, file metadata, and prior receipts from Cosmos.
2. Reconcile any non-terminal prior receipt with the runtime/process evidence available; if completion
   cannot be proven, mark it `interrupted` or `unknown_commit` rather than successful.
3. Recreate the conversation workspace under a server-chosen path.
4. Download the conversation files needed for the next turn from Blob.
5. Create a fresh harness session and replay the bounded, normalized product transcript through the
   harness adapter.
6. Compose fresh trusted context and begin the new turn.

Deep Agents may use an in-memory checkpointer while warm, and Copilot may retain its SDK session while
warm. Neither is authoritative. Harness replacement or scale-in must leave the same conversation
record usable.

### New conversation

**New conversation** creates a new actor-owned Cosmos record and selects it. It clears only the new
view's conversation-local UI state and starts with no private files. It does not delete or reset:

- the prior conversation, transcript, files, or receipts;
- personal tasks, profile, preferences, or working context;
- any Engagement record, task, convention, membership, activity, or status; or
- any promoted Engagement artifact.

The previous conversation remains in the actor's conversation list unless the actor separately
archives it. Permanent deletion, retention schedules, legal hold, and export are outside v1.

### Explicit promotion

**Save to Engagement** is a separate application command. It reauthorizes the conversation owner and
current Engagement membership, requires the product role allowed by the artifact contract, copies
the selected private bytes into an Engagement artifact Blob identity, commits Engagement metadata and
attribution, and returns a structured result. Only that committed result makes the file shared.

An active Engagement, filename match, assistant suggestion, or successful private upload never
promotes automatically. Removing or archiving the conversation does not remove an already committed
Engagement artifact.

## Concurrency and consistency

V1 deliberately uses a small deployment and a small coordination model:

- at most one orchestrator replica and one internal session-runtime replica;
- one in-process lock per conversation in the turn coordinator and a matching runtime guard;
- immediate `409 conversation_busy` for a competing send;
- Cosmos ETag checks for conversation, personal, and Engagement aggregate updates; and
- stable client/request IDs for bounded idempotent retries of message acceptance, upload metadata,
  promotion, and application mutations.

Different conversations may proceed independently within the runtime's supported request
concurrency. Two tabs opening the same conversation share durable history but cannot run overlapping
turns. The UI guard improves responsiveness; the server remains authoritative.

This design does **not** add a distributed lease service, workflow engine, queue, or event-sourcing
layer in v1. The one-replica limit is a real architectural constraint, not a claim that process-local
coordination scales horizontally. Increasing either replica count requires a fresh design record and
behavioral evidence for durable actor/session binding, single-turn exclusion, cancellation, and
recovery across replicas.

## Degraded and failure behavior

Failure is scoped and remains visible:

| Failure | Required behavior |
|---|---|
| Cosmos unavailable | Do not create, resume, accept a turn, or claim a mutation. The UI may retain clearly stale last-known content but disables state-changing actions until an authoritative read succeeds |
| Blob unavailable while opening a conversation | Transcript and receipts may still load; mark affected files unavailable. A turn that requires those bytes fails or proceeds only with an explicit omitted-file notice |
| Blob write succeeds but metadata commit fails | File remains invisible; retry by stable request/file ID cannot create duplicate visible metadata |
| Session runtime unavailable or cold-start timeout | Manual CSA Workbench remains usable; persist a failed/interrupted receipt, show a recoverable error, and never infer tool success |
| Browser/SSE disconnect | Do not equate disconnect with cancellation. Reconcile the receipt and authoritative application state before enabling retry |
| Tool result or commit acknowledgement is lost | Record `unknown_commit`, refetch the target record, and do not navigate or narrate success until the commit is proven |
| Context source is omitted or unavailable | Record the degraded source in the stored context projection; use only safe defaults and never invent identity, permission, scope, or facts |
| Runtime or workspace is destroyed | Rehydrate from Cosmos and Blob. Loss of unpresented scratch is expected and requires no recovery |
| Conversation is busy | Return a stable conflict immediately; do not silently queue, duplicate, or switch conversations |

The application remains useful for direct Engagement work when model compute is unavailable. A
failure in the assistant path cannot become a reason to hide or corrupt authoritative manual paths.

## Compute lifecycle and fixed target

The v1 target is a **plain internal Azure Container Apps session-runtime app on the consumption
profile**, with minimum replicas `0` and maximum replicas `1`. The frontend and orchestrator also
scale to zero and are limited to one orchestrator replica under the coordination constraint above.
Cold starts are accepted. A safe cold start means CSA Workbench can reconstruct a selected conversation from
Cosmos and Blob before the next model turn; it does not mean reviving a particular process.

| Runtime option | Status in this design | Reason |
|---|---|---|
| Plain ACA scale-to-zero app | **Fixed v1 target** | Simple GA compute lifecycle, zero idle compute, and no durable-state dependency on runtime |
| ACA Dynamic Sessions pool | Historical bridge only | Strong per-session isolation was useful, but the reported one-warm-instance floor conflicts with the fixed zero-idle baseline |
| ACA Sandboxes | Optional future investigation | May later improve resume latency or isolation, especially if code execution is introduced, but preview behavior is not a v1 dependency or state store |

The runtime app uses server-selected per-conversation workspace directories inside one process. That
is acceptable only for the v1 no-shell/no-code-execution tool surface and the single-replica profile.
It is not final risk acceptance for a broader execution surface. Adding shell, arbitrary code,
autonomous subagents, or untrusted execution requires a new isolation decision before implementation.

Schedulers and reminders are absent. There is no always-on loop, background workflow engine, or
scheduled-agent exception to scale-to-zero.

## V1 simplifications

The capability intentionally excludes machinery that does not prove the core product:

- no distributed lease, durable work queue, event sourcing, or cross-replica session routing;
- no session affinity as a substitute for durable ownership;
- no framework checkpointer as a product database;
- no Dynamic Sessions warm pool in the target deployment;
- no ACA Sandbox, snapshot, mounted-volume, or preview API dependency;
- no scheduler, reminder, background turn, or autonomous workflow;
- no Search dependency for conversation resume;
- no automatic promotion or shared conversation;
- no multi-region, disaster-recovery automation, retention engine, legal hold, or archive service;
- no raw chain-of-thought or unbounded SDK-event persistence; and
- no IDA-specific state, runtime, taxonomy, or integration. IDA remains reference-only.

These exclusions do not weaken the durability promise. They keep the system complete at the product
boundary while postponing horizontal scale and production-hardening work until evidence requires it.

## Current integrated state versus target

Static inspection of `master@1fcaac6` shows useful foundations but not this target:

| Concern | Current integrated evidence | Target difference |
|---|---|---|
| Personal and Engagement data | Cosmos has per-user personal records and Engagement aggregates with ETag retry paths ([`appdb.py`](../../session-container/appdb.py)) | Retain them; new-conversation and compute lifecycle never reset them |
| Engagement artifact bytes | Blob/local adapter plus Engagement metadata and membership-gated routes exist ([`artifact_store.py`](../../artifact_store.py); [`app.py`](../../app.py)) | Keep the same durable/shared boundary and make promotion from private conversation explicit |
| Conversation ownership | Orchestrator keeps session owner in process memory (`session_manager.py:109-112`), and an orchestrator restart loses that binding | Store owner on the Cosmos conversation and authorize every request from authenticated actor state |
| Browser resume | Session ID and completed messages use per-user `sessionStorage` (`frontend/src/lib/session.ts:4-48`) | Server conversation list and Cosmos transcript are authoritative across tabs, browsers, and devices |
| Harness continuity | Deep Agents uses `InMemorySaver`; Copilot creates a live SDK session (`session-container/agent_deepagents.py:1152-1161`; `agent.py:1326-1341`) | Warm optimization only; both rehydrate from one normalized transcript |
| Workspace files | Uploads, generated files, and origin manifest live under an ephemeral session workspace (`session-container/server.py:296-383`) | User uploads live in Blob and materialize on demand; generated drafts remain labelled scratch until explicitly kept or shared |
| Turn exclusion | Session server uses a per-process `asyncio.Lock` and returns 409 while locked (`server.py:237-288`) | Preserve the behavior under the explicit one-orchestrator/one-runtime constraint and durable receipts |
| Turn evidence | Optional local rotating JSONL is process-local (`trace_logging.py:16-48`) | Cosmos stores the safe, user-retrievable turn receipt; Azure Monitor remains operational evidence |
| Compute deployment | Deploy script defaults toward a plain ACA scale-to-zero runtime, while older architecture prose still describes Dynamic Sessions | Plain ACA is now the fixed target; historical prose and runbooks do not override this capability |

The current deploy script also has a concrete static defect: the plain ACA branch expands
`SESSION_ENV_VARS` at `infra/deploy.sh:455` and `:464`, before the array is defined at `:482`.
Therefore the checked-in default path is evidence of intended direction, not proof of a runnable
deployment. Correcting that script belongs to implementation and infrastructure ownership, not this
design document.

Runtime behavior, deployed identity binding, scale-to-zero, and rehydration remain **UNVERIFIED** at
this baseline until behavioral evidence proves them.

## Behavioral oracles

Implementation and review must prove behavior at the product boundary. The following are observable
oracles, not suggestions about test framework:

1. **Cross-browser resume.** Create a conversation, exchange messages, upload a file, close the
   browser, and sign in elsewhere. The same actor sees the conversation, transcript, file, and turn
   receipts without relying on prior browser storage.
2. **Actor isolation.** A second actor cannot list or open the conversation or its Blob-backed files,
   even when both actors are members of the associated Engagement. A guessed ID is indistinguishable
   from an unknown ID.
3. **Explicit promotion.** A private file is invisible to another Engagement member before **Save to
   Engagement**. After an authorized committed promotion, it appears once as a durable Engagement
   artifact with attribution and survives conversation/runtime loss.
4. **New conversation safety.** Starting a new conversation leaves the old one resumable and leaves
   personal records, Engagement records, membership, activity, and artifacts byte-for-byte or
   semantically unchanged.
5. **Orchestrator restart.** Restart the orchestrator. The actor can still list and authorize the
   conversation because ownership does not depend on the old process map.
6. **Runtime scale-in.** Remove the runtime workspace and scale the runtime to zero. The next turn
   cold-starts, rematerializes the uploaded file, replays transcript continuity, and answers a
   reference to prior conversation content without treating old context as current authorization.
7. **Harness replacement.** Resume the same stored conversation through each supported harness
   adapter. Both receive the same normalized product transcript; neither requires its former
   in-memory checkpointer or SDK process.
8. **Competing sends.** Two tabs send to the same conversation concurrently. Exactly one turn is
   accepted; the other receives `conversation_busy`; no duplicate message, tool call, mutation, or
   terminal receipt appears.
9. **Interrupted stream.** Disconnect during a mutating turn. CSA Workbench does not call it successful from
   prose or absence of an error. It stores an honest terminal/unknown state and refetches the target
   record before offering a retry.
10. **Blob partial failure.** Force metadata commit failure after bytes are written. The file is not
    listed, retry does not duplicate it, and the conversation remains usable.
11. **Missing Blob bytes.** Remove or make one referenced Blob unavailable. Transcript still opens,
    the file is visibly unavailable, and a file-dependent turn fails or records explicit omission
    rather than proceeding as if it read the file.
12. **Membership change.** Remove the conversation owner from its associated Engagement. The private
    conversation remains theirs, but fresh Engagement context is omitted and promotion or
    Engagement reads are denied under current membership.
13. **Cold-start honesty.** With all compute at zero, manual durable data remains intact. A cold-start
    timeout creates a failed/interrupted receipt and no success claim; a later retry resumes safely.
14. **Receipt reconciliation.** For every accepted turn, the UI-visible context inspector, normalized
    tool outcomes, terminal state, and authoritative record agree. No assistant sentence is accepted
    as evidence on its own.
15. **Zero-idle profile.** With frontend, orchestrator, and runtime idle, deployed compute reaches
    zero. A later authenticated cold start can resume a pre-existing conversation and complete a
    smoke turn.

Exact model wording, token timing, restoration of unpresented scratch, and recovery of a particular
container are not behavioral oracles.
