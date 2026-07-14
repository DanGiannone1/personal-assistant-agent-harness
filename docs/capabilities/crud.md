# CRUD, Confirmation, and Honest Outcomes

> **Authority:** Canonical detailed design for commands, validation, confirmation, mutation outcomes, idempotency, and optimistic concurrency  
> **Parent:** [CSA Workbench — Authoritative Product and System Design](../design.md)  
> **State:** Target design, reconciled with integrated `master@1fcaac6`  
> **Applies to:** Manual UI and agent actions over visible v1 personal and Engagement records  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#15](https://github.com/DanGiannone1/personal-assistant-agent-harness/issues/15)

## The short version

CSA Workbench has one **change desk** behind both the application and the assistant. A person may submit a
form or describe the same change in chat, but both paths use one versioned `workbench_core`
implementation. In either process, its local instance works out the permitted scope and target,
checks the signed-in actor's current role, validates the
resulting record, asks for confirmation where required, commits with optimistic concurrency, records
activity, and returns a structured outcome.

Only a `committed` outcome means the requested change landed. The UI then reloads authoritative
state and may follow the committed record's canonical destination. Assistant prose, tool arguments,
an optimistic form value, or the word “yes” is never proof of a change.

This is a product contract, not an enterprise workflow system. The first release has one small
confirmation policy, one aggregate boundary per personal space or Engagement, three bounded ETag
retries, and bounded idempotency receipts. It does not add standing approvals, bulk workflows,
cross-Engagement mutation, an outbox, or a generic policy engine.

## The jobs this contract makes dependable

### Change status without creating a second set of rules

An editor can select **Yellow** in the UI or ask the assistant to set an Engagement to Yellow. Both
paths call the same service. Yellow without a reason is `invalid` and changes nothing. Yellow with a
reason commits the status and reason together, records who changed it, reloads the Engagement, and
keeps or opens its canonical detail destination.

### Create work from the current Engagement

From an Engagement screen, an editor can add a task manually or say “add a task to prepare the
kickoff deck.” The validated current destination supplies an Engagement scope hint. The service
rechecks membership, creates the task once, records activity, and returns the new task's stable ID
and destination.

A sticky or recently visited Engagement may help navigation, but it never silently turns a neutral
screen into authority for a shared write. From a neutral screen, an Engagement task command needs an
explicit Engagement or must return a non-committing ambiguity result.

### Edit private workbench settings

The signed-in actor can change their own minimal profile and workbench preferences. The personal
scope comes from the authenticated actor, not a user ID in a form or tool argument. No Engagement
membership check applies, and another actor's personal scope can never become a candidate.

### Delete only after a bound confirmation

Deleting a task, convention, or artifact first returns `needs_confirmation` with a preview of the
exact record and effect. Nothing in product state is deleted. The rendered Confirm button calls the
backend directly with an actor-bound confirmation ID. The service rechecks the actor, role, target,
and version before committing. Typing “yes” into chat is insufficient approval.

### Recover honestly from a lost response

If a response is lost after a possible commit, the UI does not claim success. It refetches state and
retries with the same idempotency key. A stored receipt replays the original outcome if the first
attempt landed; otherwise the command safely runs once.

## Visible v1 mutation boundary

The service initially covers every visible v1 JSON mutation surface:

- personal profile and minimal workbench preferences owned by the authenticated actor;
- Engagement creation and the Engagement's name, customer, description, optional target date, and
  Green/Yellow/Red status;
- Engagement membership, tasks, working conventions, and artifact metadata; and
- the JSON metadata involved in explicitly promoting a private upload or draft to an Engagement.

Artifact bytes keep their Blob transport and compensation behavior; this service owns their
authorization, metadata commit, activity, and outcome. File lifecycle and retrieval details belong
to [Documents and retrieval](documents-retrieval.md).

The contract does not expose personal schedulers, stage pipelines, milestones, risks, action
registers, Engagement calendars, standing approvals, free-form memory, Engagement deletion or
archive, bulk mutation, or cross-Engagement mutation. Dormant fields in old data are not permission
to add tools or UI for them.

## One application core, thin adapters

```text
Orchestrator: manual form -> authenticated REST adapter -> local workbench_core instance -> repositories
Runtime: Deep Agents/Copilot -> bound product-tool adapter -> local workbench_core instance -> repositories
                                                   same package and contract version
```

`workbench_core` is a package, not a new microservice. The orchestrator and runtime each instantiate the
same immutable package inside their own process and repository identity. Cross-process correctness
comes from live authorization, Cosmos ETags, and same-aggregate idempotency receipts; session setup
refuses a runtime whose core contract version differs from the orchestrator's.

REST is the manual transport, not a second domain implementation. A later session-bound MCP wrapper
may adapt agent tools, but it is not the domain layer. Narrow model-visible tools
such as `create_task`, `set_engagement_status`, and `delete_task` normalize their arguments into the
same internal command used by REST.

Do not expose a generic, free-form CRUD tool to the model. Do not let a REST handler, harness, or UI
component own an alternative role table, status rule, confirmation rule, or success classifier.

Grounded `get` and `list` operations also pass through this application layer and apply the same
actor binding, permission trimming, stable-ID resolution, and live membership checks. They return
typed authorized records, never prompt memory or cached membership. They do not need confirmation,
idempotency receipts, ETag mutation retries, activity entries, or CRUD route effects. The command
contract below governs the state-changing half of CRUD, where honest outcomes and replay safety are
required.

## Application-core contract

The logical interface is:

```text
execute(command, trustedRuntime) -> outcome
```

### Command: untrusted intent

```json
{
  "operation": "create | update | delete | confirm",
  "resourceType": "profile | engagement | task | member | convention | artifact",
  "scopeHint": {
    "kind": "personal | engagement",
    "ref": "optional user/model reference"
  },
  "targetRef": {
    "id": "optional stable ID",
    "text": "optional strict human reference"
  },
  "changes": {},
  "expectedVersion": "optional version from an authoritative read",
  "confirmationId": "present only for confirm"
}
```

The command contains intent to validate. A stable target ID is stronger than text, but neither a
browser nor model-provided ID proves existence or access. Field changes are a typed, allow-listed
object for the selected resource. The service does not accept generic JSON Patch.

For `confirm`, the service reconstructs the exact pending operation from the confirmation record;
the caller cannot replace its target, scope, or changes.

### Trusted runtime: adapter-bound authority

```json
{
  "actorId": "actor-7",
  "sessionId": "session-...",
  "contextId": "ctx-...",
  "validatedCurrentDestinationId": "destination:...",
  "channel": "manual | agent",
  "idempotencyKey": "UI UUID or turnId:toolCallId"
}
```

The adapter binds these values after authentication and session validation. They are not
model-visible arguments and are not accepted from browser JSON:

- actor identity and personal-space owner;
- session/conversation ownership;
- current membership or effective role;
- trusted current destination and context ID; and
- idempotency key and confirmation authority.

The trusted current destination is still only a scope hint. The service performs a live read and
authorization check at execution time and again on every concurrency retry. Identity and session
details are governed by [Identity and access](identity-access.md); the snapshot and its projections
are governed by [Context](context.md).

### Structured outcome

```json
{
  "requestId": "req-...",
  "status": "committed",
  "operation": "update",
  "scope": {
    "kind": "engagement",
    "id": "eng-42",
    "title": "Website Launch",
    "reason": "current_destination"
  },
  "resource": {
    "kind": "engagement",
    "id": "eng-42",
    "version": "etag-or-domain-version"
  },
  "changedFields": ["status", "statusWhy"],
  "destination": {
    "id": "destination:engagement:eng-42",
    "title": "Website Launch",
    "route": "/engagements/eng-42"
  },
  "activityId": "activity-...",
  "confirmation": null,
  "errors": [],
  "candidates": [],
  "warnings": [],
  "retry": null
}
```

| Status | Product state changed? | Destination? | Meaning |
|---|---:|---:|---|
| `committed` | Yes | Yes | The authorized record and required activity/receipt landed |
| `noop` | No | No | The resulting state was already satisfied |
| `needs_confirmation` | No | No | A backend-bound preview awaits a direct actor action |
| `ambiguous` | No | No | More than one permitted scope or target remains |
| `invalid` | No | No | A field, transition, or command shape violates the canonical schema |
| `not_found` | No | No | No visible target matched, including hidden non-membership |
| `forbidden` | No | No | A current member lacks the required role |
| `conflict` | No | No | Concurrent change or a stale confirmation prevented a safe commit |
| `failed` | No or unknown | No | Infrastructure failed; refetch before making any claim |

Only `committed` carries a CRUD destination. `failed` includes `commitState: "unknown"` when the
service cannot know whether a storage acknowledgement was lost. Adapters preserve the envelope;
they never infer outcome from tool names, exceptions alone, marker prose, or a `CARD_JSON` trailer.

HTTP status codes may distinguish accepted, invalid, forbidden, missing, and conflicting requests,
but the response body remains this contract. AG-UI carries the same structured outcome. Harness
event mapping belongs to [Agent harness](agent-harness.md).

## Scope and target resolution

Scope resolution applies only after building a candidate set from resources the actor may currently
access:

```text
explicit stable scope or resource in the command
  > currently selected record or Engagement
  > Engagement encoded by the validated current destination
  > permitted working-Engagement hint
  > personal scope, only for a personal resource type
```

Rules by operation:

- **Personal commands** always bind to the authenticated actor's personal aggregate. A supplied
  actor ID is ignored/rejected rather than used as a scope.
- **Create Engagement** needs no existing shared scope. Any authenticated actor may create one and
  becomes its first owner.
- **Create Engagement child** may default from a selected/current Engagement destination. From a
  neutral screen it requires an explicit uniquely resolved Engagement. A sticky Engagement may rank
  suggestions but never silently scopes the write.
- **Update** and **delete** require exactly one live target. A close textual match returns
  `ambiguous`; context does not mutate the top-ranked guess.
- **Duplicate Engagement names are valid.** Stable IDs are authoritative. A name reference that
  matches more than one permitted Engagement returns `ambiguous` with safe, permitted candidates.
- **No cross-Engagement spread.** One command resolves to one aggregate. Bulk and cross-Engagement
  operations are outside v1.
- **Context never authorizes.** A stale route, visit, or selected record cannot add a resource to the
  permitted set.

Candidate details are permission-trimmed. Non-membership and non-existence both produce
`not_found`; the service must not return the hidden Engagement's title in an error or candidate
list. Natural-language destination resolution and the canonical catalog belong to
[Navigation](navigation.md).

## Authorization dependency

[Identity and access](identity-access.md#final-engagement-role-matrix) is the sole detailed authority
for the owner/editor/viewer action matrix and personal ownership rules. CRUD commands name an
operation and resource; the application core resolves that pair through the identity policy before
validation or mutation. Confirmation proves user intent but never raises the actor's permission.

Every attempt and ETag retry reloads the live actor, realm, scope, membership, and role. A personal
command derives its owner from authenticated actor context and cannot address another actor's
record. A known member below the required role receives `forbidden`; non-membership remains
indistinguishable from absence. The UI may hide unavailable controls, but the application core is
authoritative through both REST and agent paths.

Membership uses stable actor IDs, not display names. Adding an existing member with a different role
is a role change, not a duplicate. Removing or demoting the last owner remains `invalid` and is
rechecked during every concurrency attempt.

## Canonical validation

Validation runs after resolution and authorization and evaluates the **resulting state**, not only
the submitted fields.

### Engagement

- `name` is trimmed and non-empty. Names need not be unique.
- `customer` is a free-text alias, not a customer system-of-record identifier.
- `description` and `targetDate` are optional and clearable through explicit field presence.
- `targetDate`, when present, is an ISO calendar date.
- Public status values are exactly `Green`, `Yellow`, and `Red` in schemas, outcomes, UI labels, and
  assistant language. A repository may normalize storage internally, but adapters do not expose
  lowercase or legacy Amber vocabulary.
- Yellow or Red requires a trimmed, non-empty `statusWhy`.
- A patch that blanks `statusWhy` while the resulting status is Yellow or Red is `invalid`.
- Setting Green atomically clears `statusWhy`, preventing a stale blocker reason from surviving
  recovery.
- Status and reason land in one aggregate commit.

### Tasks

- `title` is trimmed and non-empty.
- Status is one of `To do`, `In progress`, `Blocked`, or `Done`.
- Priority is one of `Low`, `Medium`, or `High`.
- Optional due date is an ISO calendar date.
- Free-text group and notes use the canonical size limits and trimming rules.
- A repeated update that produces no field change is `noop`.

### Members, conventions, and artifacts

- Member role is exactly `owner`, `editor`, or `viewer`; actor reference resolves to one known
  identity in the allowed identity realm.
- Every Engagement retains at least one owner.
- Convention text is trimmed and non-empty.
- Artifact filename, byte size, content type, hash, uploader, and upload time come from trusted
  upload/storage results, not model assertions.
- Artifact metadata cannot become visible until durable bytes have been accepted by the configured
  store.

### Personal profile and workbench

- Only the minimal fields defined by the product are writable: job role, tone, language, time zone,
  and other explicitly documented preferences.
- Time zone uses a recognized IANA identifier; language and tone values obey the visible schema.
- Credentials, role membership, context history, and system receipts are not editable profile
  fields.

Typed updates distinguish omitted from intentionally cleared values. Current empty-string sentinel
patterns must not make it impossible to clear an optional field. Unknown fields are `invalid`; they
are never silently stored for forward compatibility.

## Confirmation

The backend, not the model, decides whether a command needs confirmation.

The v1 policy is intentionally fixed:

- create and ordinary update commit directly after authorization and validation;
- deletes require confirmation;
- all membership additions, removals, and role changes require confirmation; and
- bulk operations, standing approvals, and configurable risk classes do not exist.

A `needs_confirmation` outcome contains an opaque ID, a short expiry, and an exact preview:

```json
{
  "status": "needs_confirmation",
  "confirmation": {
    "id": "confirm-random",
    "expiresAt": "...",
    "preview": {
      "operation": "delete",
      "resource": {"kind": "task", "id": "task-7", "title": "Draft kickoff"},
      "scope": {"kind": "engagement", "id": "eng-42", "title": "Website Launch"},
      "effect": "Permanently remove this task"
    }
  }
}
```

The pending confirmation is bound to actor, session, operation, scope ID, target ID, canonical
payload, target fingerprint/version, and expiry. Nothing in visible product state changes while it
is pending.

The Confirm button makes a direct authenticated call with the confirmation ID. It does not send a
new natural-language message. A model-supplied `confirmed=true`, copied ID from another actor, or
typed “yes” is not approval. Confirmation re-runs live membership, role, validation, last-owner
protection, target/version checks, and idempotency before committing.

Expired, cancelled, wrong-actor, altered, or stale confirmations do not commit. A stale target
returns `conflict` and requires a fresh preview. A consumed confirmation replays its committed
receipt for the same idempotency key rather than deleting twice.

Pending cards and direct confirmation behavior across the dock and workbench are specified in
[UI/UX](ui-ux.md).

## ETag concurrency and idempotency

The current one-document aggregate is the right level for the first release:

- one personal aggregate per actor for personal JSON state and receipts; and
- one Engagement aggregate/partition for its fields, members, tasks, conventions, artifact
  metadata, activity, pending confirmations, and receipts.

Every command uses an ETag-protected read-modify-write. The in-memory mutator is side-effect-free so
it can be retried. The service performs at most **three** ETag attempts. On each fresh read it
rechecks scope, target, membership, role, resulting-state validation, confirmation validity,
no-op state, and the last-owner invariant.

If a caller supplied `expectedVersion` and it is stale, return `conflict` rather than rebasing the
change. Confirmation always checks the version/fingerprint that produced its preview. If no expected
version was supplied, a retry may apply to the fresh aggregate only when the same stable target and
intent remain unambiguous and valid. Persistent contention returns `conflict`; it never falls back
to last-write-wins.

The adapter assigns an idempotency key to every mutation:

- manual UI: one generated UUID per user action, reused across network retry;
- agent: stable `turnId:toolCallId`, bound outside model arguments; and
- direct confirmation: one action key bound to the confirmation.

For a mutation whose aggregate already exists, that aggregate stores a bounded receipt containing
actor, key, canonical command digest, status, resource ID/version, activity ID, and destination. A
retry with the same actor, key, and digest replays the original outcome. Reusing the key with
different intent is `invalid` with an `IDEMPOTENCY_KEY_REUSED` field error. Receipt retention is
capped by age and count; it is enough for double-clicks, stream retries, and lost acknowledgements,
not a permanent enterprise ledger.

### Top-level Engagement creation

Creating an Engagement has no parent aggregate in which to discover a prior receipt. It therefore
uses one special but deterministic identity rule:

```text
engagementId = "eng-" + UUIDv5(CSA_WORKBENCH_ENGAGEMENT_NAMESPACE,
                                canonical_json([realmId, actorId, idempotencyKey]))
```

The opaque ID is a locator, not an authorization secret. The create operation conditionally writes
that exact Engagement aggregate with the creator as owner and immutable creation provenance:
actor/realm, idempotency-key digest, canonical-command digest, activity ID, and committed outcome.
That small provenance record lasts with the Engagement rather than aging out with rolling retry
receipts. Two deliveries with the same bound actor, realm, and key therefore contend on one ID. The
winner creates it; the loser reads the same aggregate, verifies actor/key/command digests, and
replays the stored outcome. The same key with different intent remains `IDEMPOTENCY_KEY_REUSED`; an
unrelated pre-existing record at the derived ID fails closed.

Creates are critical oracles: replaying `create_task` returns the original task ID without a second
task/activity, and replaying `create_engagement` returns the deterministic Engagement ID without a
second aggregate or creation activity.

### Artifact compensation

Blob operations remain outside the Cosmos ETag mutator and do not trigger a general outbox design.
For create/promotion, durable bytes are written before metadata; if metadata commit fails, the
adapter attempts to remove the inaccessible orphan and returns `failed` when consistency is
uncertain. For deletion, metadata is removed through the confirmed aggregate commit and Blob cleanup
follows; an invisible orphan is preferable to visible metadata pointing at missing bytes. Cleanup
failure is recorded as a structured warning and operational trace, not hidden inside a success
sentence.

## Activity, receipts, and trace

Every committed Engagement mutation writes one bounded activity entry inside the same ETag commit:

```json
{
  "id": "activity-...",
  "timestamp": "...",
  "actorId": "actor-7",
  "channel": "manual | agent",
  "operation": "update",
  "resource": {"kind": "engagement", "id": "eng-42"},
  "summary": "Set status to Yellow — CMS migration slipped",
  "requestId": "req-..."
}
```

The feed remains capped at 100 entries. Activity is a concise user-facing receipt, not a full audit
warehouse: it records attribution, affected resource, safe summary, request ID, and time, but not
credentials, hidden policy, raw document content, or an entire before/after aggregate.

`needs_confirmation`, `ambiguous`, `invalid`, `not_found`, `forbidden`, `conflict`, and `failed`
attempts appear in request/turn traces but do not create Engagement activity because no domain
change landed. Confirmation preparation may write internal pending state without representing it as
a completed product change.

Personal mutations have bounded idempotency/behavior receipts and request or turn traces, but the
first release does not add a personal activity-feed UI. Conversation and turn durability belongs to
[Session and state](session-state.md).

Agent turns persist the command status, request ID, context ID, tool call ID, and terminal run state.
The assistant may summarize only after receiving the structured outcome. A `noop`, denial,
ambiguity, confirmation request, conflict, or failure remains visibly non-committed in both trace and
reply.

## Post-commit navigation

CRUD never pre-navigates and never asks semantic navigation where the committed resource should
open. The application core already knows the stable scope and record.

The sequence is:

1. Commit the domain change, activity, and idempotency receipt.
2. Return `committed` with a destination from the canonical destination catalog.
3. Forward the structured outcome through REST or AG-UI.
4. Invalidate and refetch authoritative application state.
5. Follow the returned destination through the client router if presentation policy calls for it
   and a newer user navigation has not won.
6. Render record content only from authoritative refreshed state.
7. Record the resulting navigation event independently.

Agent create/update/delete follows the destination by default. Manual create normally opens the new
record; manual update may remain on the current record; delete returns the parent collection. Those
are presentation choices over the same canonical destination, not different mutation outcomes.

No non-committing status carries a destination or moves the UI. If route application fails after a
commit, the mutation remains true and becomes visible after refetch; presentation cannot roll back
domain state. Navigation precedence and stale-route handling belong to [Navigation](navigation.md).

## Required failure behavior

| Starting condition and action | Required outcome |
|---|---|
| Viewer attempts any Engagement mutation, including artifact upload | `forbidden`; no activity or navigation |
| Non-member references a known Engagement ID | `not_found`; no hidden title or member detail |
| Editor updates description, customer, target date, status, task, convention, or artifact | Authorized under the same REST/tool rule |
| Editor tries to rename or manage membership | `forbidden` |
| Yellow/Red lacks a reason | `invalid` on `statusWhy`; state unchanged |
| Patch clears the reason on existing Yellow/Red | `invalid` based on resulting state |
| Set Green from Yellow/Red | `committed`; blocker reason cleared atomically |
| Two permitted Engagements have the same referenced name | `ambiguous`; stable-ID candidates only |
| Neutral screen asks to create shared task without naming an Engagement | Non-committing ambiguity/invalid scope; sticky context does not choose |
| Role is revoked during an ETag retry | Fresh authorization returns `not_found` or `forbidden`; no commit |
| Last owner would be removed or demoted | `invalid`; membership unchanged |
| Supplied expected version is stale | `conflict`; no navigation |
| Confirmation target changed after preview | `conflict`; new preview required |
| Confirmation belongs to another actor/session | `not_found` or `forbidden` without leaked preview |
| Same create is delivered twice with the same key | Original committed resource/outcome replays once |
| Same key is reused for different changes | `invalid`; no second mutation |
| Commit acknowledgement may have been lost | `failed` with unknown state; refetch and same-key retry |
| Activity write fails inside aggregate mutation | Whole domain commit fails |
| Blob cleanup fails after metadata removal | Domain deletion remains committed; warning/trace records orphan cleanup |
| UI cannot apply route after commit | State remains committed and recoverable by refetch |
| Parked resource is requested | No model tool or UI exists; internal generic request is `invalid` |

## Deliberate simplifications

- No Engagement delete or archive in v1.
- No bulk or cross-Engagement operations.
- No standing approvals, configurable action classes, workflow engine, or policy DSL.
- No generic JSON Patch and no free-form model CRUD tool.
- No event sourcing, distributed transaction coordinator, permanent audit ledger, or outbox.
- No record locks, collaborative merge UI, or unbounded ETag retry.
- No marker-string outcome protocol or model-mediated confirmation.
- No visible personal activity feed.
- No dormant milestone, risk, action, stage, Engagement-calendar, scheduler, or memory surface.
- Artifact bytes retain targeted compensation rather than introducing a new delivery subsystem.

These constraints are product boundaries, not shortcuts to silent failure. Unknown commit state,
cleanup warnings, and contention still surface honestly.

## Current-to-target evidence at `master@1fcaac6`

The integrated code contains useful foundations, but not the canonical service:

| Current evidence | What it proves | Target change |
|---|---|---|
| `session-container/appdb.py:340-388`, `501-506` | ETag read-modify-write, retry, and fail-loud abort exist | Place this repository primitive below `workbench_core`; cap core attempts at three and add same-aggregate receipts |
| `session-container/appdb.py:281-289` | App-state projection strips Cosmos ETag | Expose a safe aggregate/domain version for expected-version checks |
| `app.py:519-617` | Manual personal REST mutates authoritative state | Convert handlers to typed service adapters rather than rule owners |
| `app.py:842-1091` | Engagement REST has membership/status/task/convention rules | Move those rules into the shared service |
| `session-container/agent.py:514-570`, `628-769`, `943-1050` | Copilot duplicates resolution, mutation, activity, routing, and confirmation | Replace with narrow bound-tool adapters |
| `session-container/agent_deepagents.py:350-406`, `433-712` | Deep Agents contains a near-copy | Use the same `workbench_core` command path as manual REST and Copilot |
| `session-container/agent.py:245-286`; `agent_deepagents.py:248-277` | Outcome and cards are inferred from marker text/trailers | Emit the structured outcome directly |
| `session-container/agent.py:372-375`, `731-769`; Deep Agents `675-712` | Model-visible `confirmed` boolean gates deletion | Replace with direct actor-bound confirmation ID |
| `frontend/src/components/ToolTrace.tsx:75-92` | Confirm sends prose back into chat | Confirm through the authenticated backend directly |
| `frontend/src/hooks/useAgentSession.ts:9-24`, `441-461` | Route following depends on a hard-coded tool-name list | Follow only a structured committed destination |
| `app.py:933-958` versus `agent.py:977-998` and Deep Agents `467-489` | REST and tools disagree on rename/description permissions | Apply the final role matrix once: editor description, owner name/membership |
| `app.py:567-592` versus agent task create/update | REST validates task enums while tools accept arbitrary values | Apply one canonical task schema |
| `frontend/src/components/workbench/EngagementScreens.tsx:30-32`, `330-336` | UI exposes lowercase status labels | Expose Green/Yellow/Red everywhere |
| `app.py:1118-1152` and Engagement document UI | Current code permits viewer artifact upload | Make viewer fully read-only in UI and service |
| `session-container/appdb.py:540-545` | Bounded Engagement activity already fits the product | Enrich it with request/channel/resource attribution and keep it atomic |
| `session-container/appdb.py:400-422`, `548-649` | Parked fields and fixture records remain dormant in data | Keep them outside schemas, tools, destinations, and UI |
| `scripts/engagement_domain_smoke.py:72-104` | Repository-level ETag and abort behavior have executable evidence | Add service-level concurrency, authorization-retry, and idempotency proof |
| `scripts/engagements_e2e.mjs:73-129`, `178-209`, `236-319` | Current UI covers roles, marker/boolean confirmation, and status guard | Replace oracles with shared outcomes and bound confirmation across manual and both harness paths |

Extraction should remove the divergent implementations before claiming parity. Copying existing
logic behind a new class without routing every caller through it would preserve the defect.

## Behavioral evidence oracles

Verification must reconcile the real UI, authoritative state, and stored request/turn receipt. A
green command or assistant sentence alone is not proof.

1. **Manual/agent parity.** Starting from the same seed, execute equivalent create, update, delete,
   and membership actions through manual REST, Deep Agents, and Copilot. Assert the same status,
   role decision, validation fields, state effect, activity shape, and destination.
2. **Status invariant.** From Green, attempt Yellow with blank reason through each caller. Expect
   `invalid`, no activity, no route effect, and Green after refetch. Repeat with a reason and expect
   one committed Yellow plus persisted reason. Set Green and assert the reason is cleared.
3. **Viewer read-only.** As viewer, verify mutation controls are absent and direct REST/tool attempts
   for status, task, convention, membership, artifact upload, and artifact delete all return
   `forbidden` without state or activity changes.
4. **Membership privacy.** As a non-member, list/read/resolve/mutate a known Engagement ID. Expect the
   same not-found shape as a random ID and no hidden candidate or trace payload.
5. **Final role matrix.** Prove editor can change description/customer/target/status/tasks/
   conventions/artifacts but cannot rename or manage membership; prove owner can do both.
6. **Duplicate names.** Seed two permitted Engagements with the same name. Name-only update/delete
   returns `ambiguous`; stable ID commits to exactly one aggregate.
7. **Neutral scope.** From a neutral destination with a sticky Engagement, ask to create a shared
   task without naming scope. Assert no commit. Repeat from a validated Engagement destination and
   assert the reported scope reason is `current_destination`.
8. **Idempotent create.** Deliver the same `create_task` key twice, including after a simulated lost
   acknowledgement. Then deliver the same `create_engagement` concurrently through two callers and
   lose one acknowledgement. Assert one task, one Engagement aggregate, one activity per create,
   deterministic replayed IDs, and identical committed outcomes.
9. **Key misuse.** Reuse the key with a different canonical payload. Expect `invalid` and no second
   mutation.
10. **Concurrency.** Race permitted updates and assert no lost updates where a safe fresh retry is
    possible. Supply a stale expected version and assert `conflict` rather than silent rebase.
11. **Authorization retry.** Revoke or downgrade an editor between the service read and conditional
    replace. Assert the retry reauthorizes and no mutation lands.
12. **Confirmation integrity.** Proposal leaves state untouched. Wrong actor/session, expired ID,
    changed target, and altered payload do not commit. A valid direct confirmation commits once and
    replays on duplicate delivery.
13. **Last owner.** Exercise removal and demotion through manual and agent proposals; confirmation
    still ends in `invalid` when it would remove the last owner.
14. **Honest failure.** Force `invalid`, `forbidden`, `conflict`, and uncertain infrastructure
    failure. Assert trace and UI preserve the exact status, assistant does not claim success, and no
    route follows.
15. **Post-commit destination.** Only `committed` CRUD outcomes carry a catalog destination. A newer
    manual navigation wins over a trailing route effect, and detail content comes from refetched
    state.
16. **Activity and receipts.** Every committed Engagement mutation has the authenticated actor,
    channel, request ID, safe summary, and cap behavior. Non-commits do not appear as completed
    activity. Personal commands have receipts but no personal activity screen.
17. **Artifact compensation.** Prove editor-only promotion/upload/removal, durable bytes before
    metadata visibility, authenticated open, restart durability, and explicit cleanup warning under
    injected Blob failure.
18. **Parked-surface absence.** Assert no route, form, destination, model-visible tool, schema field,
    or prompt instruction exposes excluded stages, milestones, risks, actions, Engagement calendar,
    scheduler, standing approval, or memory capabilities.

The primary behavioral journey runs through the real responsive frontend and deployed Deep Agents
profile when deployment behavior changes. Copilot must meet the same core local contract, but exact
assistant wording and raw SDK event timing are not parity criteria.

## Related authority

- [Authoritative product and system design](../design.md) — high-level scope and boundaries
- [Identity and access](identity-access.md) — actor/session binding, realms, and service identity
- [Context](context.md) — trusted current destination, active Engagement, and projections
- [Navigation](navigation.md) — destination catalog, route effects, and user-navigation precedence
- [Documents and retrieval](documents-retrieval.md) — uploads, Blob lifecycle, artifact promotion,
  retrieval, and citations
- [Session and state](session-state.md) — conversation durability, turn receipts, and rehydration
- [Agent harness](agent-harness.md) — bound tools, structured AG-UI events, and narration behavior
- [UI/UX](ui-ux.md) — forms, confirmation cards, responsive interaction, and accessibility
