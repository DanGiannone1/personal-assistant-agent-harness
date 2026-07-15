# CRUD Capability

> **Authority:** Canonical CRUD detail subordinate to the [authoritative design](../design.md)
>
> **Deployed application revision:** `c544f6ca7d70a80d9aa5708d22c590f8f13c88d6`
>
> **Applies to:** Implemented Engagement reads and changes through the manual application and assistant tools
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## In plain language

An Engagement is one shared delivery record. A signed-in CSA can create one and becomes its first
owner. Members see the same durable record, while their role controls what they may change:

- owners can edit everything in the implemented Engagement surface and manage the team;
- editors can edit delivery details, status, tasks, conventions, and artifacts; and
- viewers can read the Engagement and open its artifacts, but cannot change it.

The application and assistant share one small Engagement service for the release's basic operations:
create, list, get, update, set status, and add or change a member. The manual application also uses
that service to remove a member. It checks the signed-in actor's current membership, validates the
requested result, changes the Cosmos record, and reports an outcome. The web page refreshes its
authoritative state after a successful manual change and after assistant tool activity, so rendered
state does not depend on assistant wording or an optimistic browser value.

The release also has manual task, convention, and artifact operations. Those are real, role-gated
features, but they have not yet been moved into the shared service or exposed in the current assistant
tool inventory. This distinction matters: the release proves a shared core for Engagement basics, not
universal CRUD parity.

## Implemented surface

| Operation | Manual application | Assistant | Required access |
|---|---:|---:|---|
| Create Engagement | Yes | Yes | Signed-in actor; creator becomes owner |
| List visible Engagements | Yes | Yes | Current member |
| Get Engagement by stable ID | Yes | Yes | Current member |
| Edit description, customer, start date, or target date | Yes | Yes | Editor or owner |
| Rename Engagement | Yes | Yes | Owner |
| Set Green, Yellow, or Red status | Yes | Yes | Editor or owner |
| Add member or change role | Yes | Yes | Owner |
| Remove member | Yes | No | Owner |
| Create, update, or remove Engagement tasks | Yes | No | Editor or owner |
| Add or remove working conventions | Yes | No | Editor or owner |
| List, open, upload, or remove artifacts | Yes | No | Member to list/open; editor or owner to upload/remove |

There is no Engagement delete or archive operation. The current assistant receives exactly seven
product tools: `navigate`, `list_engagements`, `create_engagement`, `get_engagement`,
`update_engagement`, `set_engagement_status`, and `share_engagement`. Legacy task and document helper
functions remain in the harness source but are not returned to the model.

## Roles and privacy

| Role | Read | Delivery fields and status | Tasks, conventions, artifacts | Name and membership |
|---|---:|---:|---:|---:|
| Owner | Yes | Yes | Yes | Yes |
| Editor | Yes | Yes | Yes | No |
| Viewer | Yes | No | No | No |

Every request gets its actor outside the Engagement payload. REST handlers use the authenticated API
actor. The orchestrator binds an agent session to that actor and forwards the actor to the
workload-authenticated runtime; the runtime closes its tools over that binding. No model-visible
Engagement tool accepts an actor or role.

Reads return only Engagements where the actor is currently a member. A missing Engagement and a real
Engagement hidden from a non-member both become the same not-found behavior. A known member whose role
is too low receives a forbidden result. Browser controls are a usability aid, not the authorization
boundary.

Mutation authorization is checked inside the Cosmos read-modify-write function. Because that function
runs again after an optimistic-concurrency collision, a concurrent membership removal or downgrade is
rechecked before another write attempt. Removing or demoting the final owner is invalid.

## Shared Engagement core

`workbench_core.EngagementService` is a dependency-light application service instantiated in both the
orchestrator and the runtime. `AppdbEngagementRepository` adapts it to the shared Cosmos persistence
module. The current split is:

```text
Manual Engagement basics -> FastAPI REST adapter -> EngagementService -> AppdbEngagementRepository
Assistant basics          -> harness tool adapter -> EngagementService -> AppdbEngagementRepository

Manual tasks/conventions/artifacts -> FastAPI handlers -> appdb / artifact_store
```

The shared service owns current-role checks, visible-target resolution, basic Engagement validation,
member rules, no-change detection, activity creation, and its transport-neutral `Outcome`. REST
handlers translate that outcome into record JSON or HTTP errors. The two harnesses translate the same
outcome into a native `ProductToolResult`; neither adapter parses assistant prose to decide success.

This core is intentionally smaller than the aggregate. Task, convention, and artifact rules still
live in the REST and harness modules, although the current model tool inventory makes only their REST
path active. They must not be described as shared-core parity.

## Basic command validation

The service accepts an allow-list rather than generic JSON Patch:

- `name`: required and at most 120 characters;
- `description`: at most 500 characters;
- `customer`: at most 120 characters;
- `status`: `green`, `yellow`, or `red`;
- `statusNote` (also accepted internally as `statusWhy`): at most 300 characters;
- `startDate` and `targetDate`: empty or an ISO calendar date.

Validation applies to the resulting Engagement. Yellow and Red require a non-empty reason. Green
clears any previous reason in the same mutation. Optional delivery strings and dates may be explicitly
cleared. Changing `name` requires owner access; other listed fields require editor access.

Member operations resolve a user by stable user ID or sign-in name and accept only `owner`, `editor`,
or `viewer`. Sharing an existing member with another role changes that role. Repeating the same role is
a no-op. The final owner cannot be removed or demoted.

Task REST validation is narrower and separate: create requires a non-empty title up to 300 characters,
status must be `To do`, `In progress`, `Blocked`, or `Done`, and priority must be `Low`, `Medium`, or
`High`. Task status and priority updates use the same enums. The implementation does not currently
validate task due dates as calendar dates, and an update can clear the title; those are known contract
gaps rather than intended behavior.

Artifact upload accepts a non-empty file up to 20 MiB, strips path components, sanitizes the stored
name, and caps it at 120 characters. Members may list and download; only editors and owners may upload
or remove. Artifact bytes live in Blob-compatible storage and metadata lives in the Engagement Cosmos
document.

## Outcomes and HTTP behavior

The service result is typed as an `Outcome` with status, operation, optional record, changed fields,
field errors, code, and optional target user. Its implemented vocabulary, including the internal
visible-name resolver, is:

| Status | Meaning | State effect |
|---|---|---|
| `succeeded` / `resolved` | Authorized read or target resolution completed | None |
| `committed` | A Cosmos create or conditional replacement completed | Requested record changed |
| `noop` | The requested state already exists | None |
| `ambiguous` | The internal resolver found more than one visible name match | None |
| `invalid` | Shape, field, resulting status, role, user, or final-owner rule failed | None |
| `not_found` | Target is missing or hidden by non-membership | None |
| `forbidden` | A current member lacks the required role | None |

The product result schema also accepts `needs_confirmation`, `conflict`, and `failed`, but the current
Engagement service does not implement confirmation records, stale-version conflicts, or typed storage
failures. Those vocabulary entries are not evidence that those behaviors exist.

Assistant basics emit `ProductToolResult` as native harness metadata/artifact and then as a structured
`TOOL_CALL_RESULT`. It carries `status`, `code`, `operation`, and an Engagement resource ID where one
is available. The runtime fails closed with a structured failure if an active tool does not provide a
valid native result. The visible tool text is explanatory only.

REST retains a simpler adapter contract. It returns records on success, uses 404 for missing or hidden
Engagements, 403 for insufficient roles, 422 for validation, and 409 only if a core conflict were
returned. Unhandled Cosmos, Blob, or adapter exceptions become ordinary request failures rather than a
typed Engagement outcome.

## Authoritative refresh

Manual Engagement controls await the REST call and then reload `/sessions/{session_id}/app/state`.
That state endpoint checks session ownership and builds the Engagement list from current Cosmos
membership. Create uses the returned stable ID only to choose the new route; the record content comes
from the refreshed application state.

For assistant turns, the frontend refreshes after each tool completes and again when the run finishes
or errors. Refresh requests use a monotonic sequence so an older response cannot replace a newer one.
A failed refresh leaves the last good state visible, marks it stale, and offers Retry. Structured
navigation is separate and cannot make an uncommitted mutation true.

Manual controls currently refresh only after a request reports success. If a cross-store artifact
operation changes Cosmos and then fails while cleaning up Blob, the page can show an error with stale
state until the next refresh. This is a remaining honesty gap.

## Cosmos concurrency and atomicity

Each Engagement is one Cosmos document and one partition. Its delivery fields, members, tasks,
conventions, artifact metadata, and bounded activity feed are replaced together. The persistence layer:

1. reads the document and its private Cosmos ETag;
2. runs the mutator;
3. conditionally replaces the document with `IfNotModified`;
4. on an ETag collision, reads fresh state and retries the complete mutator; and
5. raises after ten failed attempts.

This prevents one writer from silently replacing an unrelated concurrent change. The successful
single-document replacement also makes an Engagement change and its activity entry atomic. The ETag
is not exposed to callers, there is no expected-version argument, and same-field stale edits are not
rejected: a later retry can apply to the newest document and the last successful value wins. Persistent
contention surfaces as a generic server or turn failure, not a typed `conflict`.

Top-level creation uses a random Engagement ID and a Cosmos create. A same-actor, same-name owner
record is returned as `noop`, but this is name-based duplicate suppression, not idempotency. There are
no idempotency keys, durable receipts, replay guarantees, or conditional deterministic create IDs.

Artifact bytes and Cosmos metadata cannot share one transaction. Upload writes bytes first, then
conditionally adds metadata and activity; if the metadata step raises, the API attempts to delete the
bytes. Delete removes metadata and activity first, then deletes the bytes. These are best-effort ordering
rules, not compensation or exactly-once guarantees. A cleanup failure may leave an orphan or return an
error after the visible metadata change already committed.

## Honest failure boundary

- Validation, role denial, missing targets, ambiguity, and no-op outcomes do not write the Engagement.
- Non-membership does not leak an Engagement title or membership details.
- Activity is written only inside a successful Engagement document mutation and is capped at 100
  entries.
- A Cosmos or Blob exception is not converted into success. The request or turn fails and the UI's next
  authoritative refresh determines visible state.
- There is no durable commit receipt, so a lost response cannot be safely replayed as the same command.
- Delete buttons for tasks, conventions, members, and artifacts use a local two-step armed control.
  The backend receives a direct delete request; there is no actor-bound confirmation record, expiry,
  replay protection, or confirmation API.

## Evidence status

Focused core and structured-control tests cover create/list/get, role gates, hidden non-membership,
status-with-a-reason, final-owner protection, field limits, no-op behavior, native result mapping, and
Copilot/Deep Agents schema and result parity. The structured evidence-oracle tests reject prose-only
success and malformed event lifecycles.

Local synthetic evidence bundles are source-labelled rather than timeless. The latest available browser
bundle reports 34 passing checks at source revision `9142b2a`, including two-user sharing, outsider
read/write rejection, viewer affordances, validation with unchanged state, structured agent mutation,
and authoritative UI refresh. The available live agent bundle reports seven passing cases at revision
`7bca264`. Both precede the deployed application revision; the focused contracts run against the current checkout,
but a fresh clean-worktree browser/eval bundle for `c544f6c` is not present. The browser bundle checks
that a blank Engagement task is rejected without changing state; it does not exercise a complete task
mutation or artifact lifecycle at that revision.

## Remaining gaps

- Task, convention, and artifact operations are not routed through `EngagementService` and are not in
  the current model-visible tool inventory.
- Member removal is manual-only.
- REST success and failure bodies are not the same `ProductToolResult` envelope used by agent tools.
- The `get_engagement` tool's structured payload identifies the authorized record but does not carry the
  full record fields; listing remains the assistant's detailed read path.
- No caller-visible ETag, expected-version conflict, idempotency key, durable receipt, backend
  confirmation, or safe lost-response replay exists.
- Artifact Blob/Cosmos cleanup is best effort and can return failure after one store changed.
- Infrastructure failures are generic HTTP or terminal failures rather than typed, state-aware domain
  outcomes.

These are release limitations, not promises to add hardening or expand scope.

## Related authority

- [Authoritative design](../design.md)
- [MVP success criteria](../requirements.md)
- [Identity and access](identity-access.md)
- [Agent harness](agent-harness.md)
- [Documents and retrieval](documents-retrieval.md)
- [Session and state](session-state.md)
- [UI/UX](ui-ux.md)
- [Testing and evals](testing-evals.md)
