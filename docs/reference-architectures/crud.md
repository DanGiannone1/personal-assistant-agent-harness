# CRUD (target design)

> **Authority:** Target design. Not a description of current behavior — [../design.md](../design.md)
> owns the current boundary. See "Where the current MVP stands" below for the honest gap to what is
> implemented today.

## The simple version

The user should be able to create, update, or delete something without first finding the right
screen.

1. The app uses the current user, current Engagement, and current work to understand the request.
2. The backend checks the request and saves the change.
3. Once the save succeeds, the app opens the new or updated record.

For example, "add a high-priority task to prepare the steering deck" should work from Home, chat, or
another screen. The user does not need to open the Engagement first. The app works out the scope,
creates the task, and then opens it.

The assistant does not change data itself. It calls the same backend service used by the rest of the
app through a typed tool, and reports success only after that backend confirms the save.

## What happens behind the scenes

1. The assistant turns the request into a small, typed command.
2. The tool adapter sends that command to the shared backend service.
3. The backend uses trusted context to find the right Engagement and record.
4. The backend checks access, validates the change, and asks for confirmation when needed.
5. The backend saves the change safely and records who did it.
6. The result tells the UI exactly which record was changed.
7. The UI reloads the saved data and opens that record.

Navigation is not a prerequisite and is not another AI decision. The backend already knows the
destination of the record it just changed.

## Five rules

1. **No pre-navigation.** CRUD commands work from any page. Current view is context, not a workflow
   requirement.
2. **Trusted context.** Identity, permissions, session, and context defaults come from authenticated
   runtime state, never model-supplied IDs.
3. **One application service.** REST and the assistant tool layer are adapters over the same
   validation, authorization, approval, mutation, and outcome logic.
4. **Commit before claim.** A record is changed only after an authorized concurrency-safe commit; the
   UI renders records only after re-reading backend state.
5. **Open only after success.** Only `committed` carries a grounded destination. Errors, no-ops,
   ambiguity, and pending confirmations do not move the UI.

## User experience

### Create from anywhere

"Add a high-priority task to prepare the steering deck" can be issued from Home, chat, or another
Engagement. Context identifies the active Engagement; the backend validates that default and the
actor's editor role, creates the task, and returns its canonical detail destination. The UI then opens
it.

### Update without opening the record

"Mark the steering-deck prep task done" does not first navigate to tasks. The backend searches only
accessible records, uses current and working context to rank strict matches, revalidates a unique
target, commits, and returns the updated task's destination.

### Destructive action

"Delete the completed personal tasks" resolves candidates and policy but does not mutate. The backend
returns `needs_confirmation` with a preview and a signed, expiring confirmation token. Only a later
command presenting that token can commit, and the policy and record versions are checked again.

## Scopes and records

The shared collaboration scope is an **Engagement**. Personal space (Tasks with subtasks, Calendar
events, and Reminders) remains available for records that never belong to an Engagement — each
actor's own aggregate, authorized by ownership alone, not a role matrix.

An Engagement combines:

- Account-backed membership with `owner`, `editor`, and `viewer` roles
- Engagement fields such as description, customer, status (`green`/`yellow`/`red`) with a required
  reason for yellow or red, and start/target dates
- Engagement tasks, working conventions, and artifacts
- Activity history and one ETag-safe document per Engagement

The architecture does not treat a display name in a members list as authorization. Membership is
bound to stable actor IDs and checked on every read and mutation.

## Context-aware resolution

The [context service](context.md) supplies a snapshot with provenance. CRUD uses it in this order:

```text
explicit scope or stable ID in the turn
  > currently selected record or Engagement
  > Engagement encoded by the current view
  > sticky working Engagement
  > personal/default scope
```

These are resolution hints, not authority. The service first generates candidates from resources the
authenticated actor may access, then uses context to rank that permitted set.

Rules by operation:

- **Create:** may default to a clearly active Engagement and must report the chosen scope.
- **Update:** requires one resolved target. A close call returns `ambiguous`; it never updates the
  highest-scored guess.
- **Delete or bulk change:** requires one resolved target set plus approval policy. High contextual
  confidence does not waive confirmation.
- **Cross-Engagement request:** must carry an explicit authorized scope or resolve uniquely from the
  request. Working context cannot silently spread a mutation across scopes.

The backend re-resolves document-dependent references and rechecks membership inside any optimistic
concurrency retry.

## One service, multiple adapters

```text
Manual UI    -> REST adapter --------\
                                       -> CRUD application service -> repositories
Deep Agents  -> tool adapter --------/
Copilot      -> tool adapter --------/
```

Both REST handlers and tool adapters delegate to the same in-process application service; neither
re-implements validation or mutation rules of its own.

That service owns:

- Actor and session binding
- Context lookup and scope resolution
- Membership and role authorization
- Entity schemas, defaults, and cross-field validation
- Strict target resolution
- Confirmation and standing-approval policy
- Idempotency and expected-version handling
- ETag-safe mutation
- Activity/audit recording and side-effect outbox entries
- Structured outcome construction
- Canonical post-success destination generation

The repository layer owns storage mechanics. It does not decide authorization, user-visible outcomes,
or route behavior.

## Typed command contract

Agent tools should remain narrow and typed (`create_task`, `update_task`, `delete_task`) while
normalizing into one internal command envelope:

```json
{
  "requestId": "req-...",
  "idempotencyKey": "turn-...:tool-...",
  "operation": "update",
  "resourceType": "task",
  "targetRef": "steering deck prep",
  "scopeHint": {"kind": "engagement", "ref": "launch"},
  "changes": {"status": "Done"},
  "expectedVersion": null,
  "approvalToken": null
}
```

The following values are **not** model arguments:

- Acting actor ID
- Session/workspace ownership
- Effective permissions
- Trusted current route
- Standing approvals
- `contextId`

The REST or tool adapter binds those from authenticated transport and the turn runtime. Treat every
model-provided scope, target, and field value as intent to validate, not trusted state.

## Execution pipeline

The application service executes commands in this order:

1. **Bind actor and context.** Load the authenticated actor and immutable turn-context snapshot.
2. **Build authorized candidates.** Query only personal and Engagement resources visible to that
   actor.
3. **Resolve scope and target.** Apply explicit references and contextual precedence.
4. **Authorize operation.** Viewers cannot mutate; editors can change records; owner-only operations
   include membership and Engagement administration.
5. **Validate.** Apply canonical field schemas, state transitions, and cross-field rules.
6. **Evaluate approval.** Check action class, risk, standing grants, and any confirmation token.
7. **Commit.** Use an idempotent ETag-protected mutation and re-run document-dependent checks after
   conflicts.
8. **Audit.** Write actor, operation, scope, before/after summary, approval basis, and request ID in
   the same aggregate commit when possible.
9. **Queue external effects.** Email, indexing, and other non-transactional work use an outbox or a
   compensating workflow after the state commit.
10. **Return outcome.** Construct one structured status and a canonical destination only when the
    mutation committed.

## Concurrency and idempotency

The existing read-with-ETag, retry-with-fresh-state mutation primitive supplies the right core
behavior: read with ETag, run a side-effect-free in-memory mutator, conditionally replace, and retry
against fresh state after a conflict.

The target service adds these requirements:

- Recheck authorization, membership, target resolution, and approval validity on every retry.
- Attach an idempotency key to every agent tool call so a retried stream or network request cannot
  duplicate a create.
- Store the resulting outcome or operation receipt long enough to replay duplicate requests.
- Bind confirmation tokens to actor, operation, scope, target IDs, proposed payload, expected
  versions, and expiry.
- Never perform email, search indexing, or other external side effects inside a retryable mutator.
- Raise a loud `conflict` after bounded retries rather than silently accepting last-write-wins.

## Structured outcomes

Marker strings are presentation, not a protocol. The application service returns one envelope:

```json
{
  "requestId": "req-...",
  "status": "committed",
  "operation": "update",
  "scope": {"kind": "engagement", "id": "eng-42"},
  "resource": {"kind": "task", "id": "t-7", "version": "etag-..."},
  "destination": {
    "id": "destination:engagement:eng-42:task:t-7",
    "title": "Prepare steering deck",
    "route": "/engagements/eng-42/tasks/t-7"
  },
  "auditId": "activity-..."
}
```

| Status | Mutation? | Navigate? | Meaning |
|---|---:|---:|---|
| `committed` | Yes | Yes | Authorized mutation landed |
| `noop` | No | No | Request was already satisfied or changed nothing |
| `needs_confirmation` | No | No | Backend-issued preview/token must be accepted |
| `ambiguous` | No | No | More than one authorized target remains |
| `invalid` | No | No | Fields or transition violate the canonical schema |
| `not_found` | No | No | No authorized target matched |
| `forbidden` | No | No | A known scope or operation is not permitted |
| `conflict` | No | No | Concurrent change prevented a safe commit |
| `failed` | Unknown/No | No | Infrastructure failure; the client must refetch before claiming state |

Adapters translate this envelope to HTTP and AG-UI without parsing prose. Candidate lists, field
errors, previews, approval tokens, and retry guidance are typed optional fields on the same result.

## Confirmation and standing approvals

The backend, not the model, decides whether a mutation may commit.

- Create and low-risk update may commit immediately according to user policy.
- Delete, bulk mutation, membership changes, and high-risk transitions normally return
  `needs_confirmation`.
- Standing approvals are user-visible, revocable grants scoped to an action class and optionally an
  Engagement.
- A confirmation token is single-use and bound to the exact preview and record versions.
- Confirmation re-runs authorization, policy, and version checks before commit.
- Every policy decision and committed action writes an audit entry.

A boolean such as `confirmed=true` supplied by an agent is not proof of user approval.

## Navigate after completion

The order is deliberate:

1. Commit the record and audit.
2. Return `status=committed` with a grounded canonical destination.
3. Emit the structured tool result through AG-UI.
4. Invalidate and refetch authoritative app state.
5. Apply the returned route effect through the client router.
6. Record the resulting navigation event for future context.

There is no semantic `navigate` call before or after CRUD. The backend already knows the record it
committed. If client navigation fails, the mutation remains committed and visible after refetch; UI
presentation cannot roll back domain truth.

Agent-driven CRUD follows the destination by default. A manual form can deliberately remain in place
as a presentation choice, but it receives the same committed result from the same service.

## Deep Agents and the shared tool layer

The LangGraph Deep Agents harness should consume typed tools backed by the application service:

- Keep local per-harness CRUD implementations out of the harness adapter; the adapter only translates
  a typed tool call into the shared service call and back.
- Bind actor, session, workspace, and tool-context projection outside model arguments.
- Let the backend resolve Engagement defaults; do not prompt the model to guess a scope argument from
  the current route.
- Forward structured outcomes and route effects as AG-UI events.
- Keep the LangGraph checkpointer for conversation continuity, not durable application state or
  approval evidence.

Copilot and future harnesses use the same shared service through their own tool adapters. Harness
parity becomes a property of shared execution rather than duplicated code.

## Where the current MVP stands

The current MVP already implements meaningful pieces of this design for Engagement and
personal-workspace operations:

- One shared application service per domain (`workbench_core.EngagementService`,
  `workbench_core.PersonalWorkspaceService`) backs both REST and both agent harnesses — this design's
  core rule, already true for the operations both surfaces expose.
- ETag-safe, retrying, read-modify-write mutation backs every Engagement and personal-workspace write,
  and role/ownership authorization is rechecked on every retry.
- Outcomes are structured (`succeeded`/`resolved`, `committed`, `noop`, `invalid`, `not_found`,
  `forbidden`, with `ambiguous`/`needs_confirmation`/`conflict`/`failed` reserved in the shared
  vocabulary but not yet produced by these services) — not inferred from text.

What this design adds beyond today:

- Context-based scope resolution and defaulting so a command works without pre-navigation — today,
  every tool call requires an explicit ID; there is no "add a task to the active Engagement" default.
- Confirmation tokens and standing approvals for destructive or high-risk operations — today, delete
  operations commit immediately once authorized.
- Idempotency keys and duplicate-request receipts — not implemented.
- Canonical post-commit navigation destinations on CRUD results — today only the `navigate` tool
  itself carries a validated destination; Engagement and personal-workspace commit outcomes do not.
- Assistant coverage of Engagement tasks, conventions, artifacts, and member removal — these remain
  manual-only; see [Agent harness](../capabilities/agent-harness.md#model-visible-tools).

See [../capabilities/crud.md](../capabilities/crud.md) for the authoritative current-state contract
for Engagement records.

## Architecture checklist

- [ ] CRUD works from any view and never requires pre-navigation.
- [ ] Actor, permissions, session, and context are runtime-bound rather than model arguments.
- [ ] Context ranks only authorized candidates and never grants access.
- [ ] Creates report their chosen scope; updates/deletes require a unique target.
- [ ] REST and the assistant tool layer delegate to one application service with one validation
      policy.
- [ ] Every mutation is idempotent, ETag-safe, retry-safe, and fail-loud.
- [ ] Authorization and approval are rechecked inside retries.
- [ ] Destructive operations require a backend-verifiable policy or confirmation token.
- [ ] Outcomes are structured and transport-independent.
- [ ] Only `committed` carries a destination and triggers navigation.
- [ ] The UI re-reads authoritative state and never renders from model claims.
- [ ] Deep Agents and Copilot call the same shared application service through their own tool
      adapters.
