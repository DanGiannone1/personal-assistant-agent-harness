# Engagement record boundary

> **Authority:** Focused current-boundary note; [design](../design.md) and [requirements](../requirements.md) remain higher authority.

## In plain language

An Engagement is one shared delivery record. A signed-in actor can create one and becomes its first
owner. Members see the same durable Cosmos record, while their role controls what they may change:

- owners can edit everything below and manage the team;
- editors can edit delivery fields, status, tasks, conventions, and artifacts; and
- viewers can read the record and open its artifacts, but cannot change it.

The manual application and the assistant share one small application service,
`workbench_core.EngagementService`, for the basic operations: create, list, get, update, set status,
and add/change a member. The manual application also uses that service to remove a member. It checks
the signed-in actor's current membership, validates the requested result, changes the Cosmos record,
and reports a typed outcome. The web page refreshes its authoritative state after a successful manual
change and after assistant tool activity, so rendered state never depends on assistant wording or an
optimistic browser value.

Tasks, conventions, and artifacts are real, role-gated Engagement features with a complete manual
REST path, but they are not in the assistant's tool inventory — see [Agent harness](agent-harness.md)
for the exact tool list. This distinction matters: the shared core is proven for Engagement basics,
not universal CRUD parity between the UI and the assistant.

Engagement records are not the personal Tasks/Calendar/Reminders surface. Private, actor-owned
personal records live on their own `personal-{uid}` aggregate and are never scoped to or shared
through an Engagement; see [design](../design.md) and [identity and access](identity-access.md).

## Implemented surface

| Operation | Manual application | Assistant | Required access |
|---|---:|---:|---|
| Create Engagement | Yes | Yes | Signed-in actor; creator becomes owner |
| List visible Engagements | Yes | Yes | Current member |
| Get Engagement by stable ID | Yes | Yes | Current member |
| Edit description, customer, start date, or target date | Yes | Yes | Editor or owner |
| Rename Engagement | Yes | No (tool has no `name` field) | Owner |
| Set Green, Yellow, or Red status with a reason | Yes | Yes | Editor or owner |
| Add member or change role | Yes | Yes | Owner |
| Remove member | Yes | No | Owner |
| Create, update, or delete Engagement tasks | Yes | No | Editor or owner |
| Add or remove working conventions | Yes | No | Editor or owner |
| List, open, upload, or remove artifacts | Yes | No | Member to list/open; editor or owner to upload/remove |

There is no Engagement delete or archive operation.

## Roles

| Role | Read | Delivery fields, status, tasks, conventions | Artifacts (upload/delete) | Name and membership |
|---|---:|---:|---:|---:|
| Owner | Yes | Yes | Yes | Yes |
| Editor | Yes | Yes | Yes | No |
| Viewer | Yes | No | Read-only (list/download) | No |

Every request gets its actor outside the Engagement payload. REST handlers use the authenticated API
actor; the runtime binds an agent session to that same actor and closes its tools over that binding.
No model-visible Engagement tool accepts an actor or role.

Reads return only Engagements where the actor is currently a member. A missing Engagement and a real
Engagement hidden from a non-member both produce the same not-found result. A known member whose role
is too low receives a `forbidden` result. Browser controls are a usability aid, not the authorization
boundary — the role check runs again inside the retried Cosmos mutation, so a concurrent membership
change is rechecked before another write attempt. Removing or demoting the final owner is invalid.

## Validation

`EngagementService` accepts an allow-list rather than generic JSON Patch: `name` (required on create,
≤120 chars, owner-only to change), `description` (≤500), `customer` (≤120), `status` (`green`,
`yellow`, or `red`), `statusNote` (≤300; also accepted as `statusWhy`), and `startDate`/`targetDate`
(empty or ISO calendar date). Yellow and Red require a non-empty `statusNote`; setting Green clears
any previous note in the same mutation. Sharing accepts only `owner`, `editor`, or `viewer`; repeating
an existing member's role is a no-op, and the final owner cannot be demoted.

Engagement task REST validation is separate and narrower: a non-empty title, status in `To do`/
`In progress`/`Blocked`/`Done`, priority in `Low`/`Medium`/`High`, and an optional ISO due date.
Artifact upload accepts a non-empty file up to 20 MiB; the server strips path components and caps the
stored name at 120 characters.

## Outcomes

`Outcome` carries a status, operation, optional record, changed fields, field errors, and code. The
implemented vocabulary: `succeeded`/`resolved` (read or resolution, no state effect), `committed` (a
Cosmos write completed), `noop` (requested state already exists), `invalid` (shape/role/final-owner
rule failed), `not_found` (missing or hidden by non-membership), and `forbidden` (member lacks the
required role). The shared result type also accepts `ambiguous`, `needs_confirmation`, `conflict`, and
`failed`, but the current service does not produce them for Engagement operations.

The assistant's `ProductToolResult` carries the same `status`/`code`/`operation` plus an optional
resource and destination; REST returns the record on success and uses `404`/`403`/`422` for the
matching outcome statuses.

## Cosmos concurrency

Each Engagement is one Cosmos document and one partition; delivery fields, members, tasks,
conventions, artifact metadata, and activity are replaced together. The persistence layer reads the
document and its ETag, runs the mutator, conditionally replaces with `IfNotModified`, and retries the
whole mutator on a collision — including the role re-check — for a bounded number of attempts before
raising. This makes an Engagement change and its activity entry atomic and prevents one writer from
silently clobbering a concurrent one, but there is no caller-visible ETag, expected-version argument,
or idempotency key: a later retry applies to the newest document and the last successful value wins.

Artifact bytes and Cosmos metadata cannot share one transaction: upload writes bytes first, then
metadata; a metadata failure deletes the just-written bytes. Delete removes metadata first, then
bytes. These are best-effort ordering rules, not exactly-once guarantees.

## Related authority

- [Design](../design.md)
- [Requirements](../requirements.md)
- [Identity and access](identity-access.md)
- [Agent harness](agent-harness.md)
- [Documents and retrieval](documents-retrieval.md)
- [Testing and evals](testing-evals.md)
