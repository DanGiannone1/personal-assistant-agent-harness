# Engagements — the shared scope

The [manifesto](manifesto.md) commits us to an engagement workspace: personal stuff stays
private, engagement records are the collaboration surface. This doc is the design contract for
the first cut.

## Two scopes, one container, one discipline

All app state lives in the `appstate` Cosmos container (partition key `/sessionId`). There are
now two document shapes in it:

| Scope | Doc | Key | Shared with |
|---|---|---|---|
| **Personal** | the owner doc (tasks/events/schedules/library/routes) | stable owner id (`COSMOS_OWNER_ID`, later the Entra `oid`) | nobody |
| **Engagement** | one doc per engagement | `eng-<8 hex>` (its own partition) | everyone on the team |

Both scopes ride the **same ETag-safe optimistic-concurrency path**: read → mutate in memory →
`replace_item` with `IfNotModified` → jittered retry on conflict. One engagement doc per
engagement means a health change and its explanatory note commit atomically, and two colleagues
editing the same engagement converge through the retry loop instead of clobbering each other.
Engagement listing is a cross-partition query on `type = "engagement"` — fine at CSA scale
(dozens of engagements, not thousands).

## The engagement document

```jsonc
{
  "id": "eng-a1b2c3d4",
  "sessionId": "eng-a1b2c3d4",        // PK == id: each engagement is its own partition
  "type": "engagement",

  "title": "Contoso data platform modernization",
  "customer": "Contoso",               // free-text alias — never a system of record
  "stage": "Build",                    // Discovery | Design | Build | Deploy | Live | Closed
  "health": "amber",                   // green | amber | red
  "healthNote": "Security review slipping; owner on PTO",  // health ALWAYS carries a why
  "members": [ { "name": "Dan", "role": "CSA" } ],          // oid field joins when auth threads through
  "startDate": "2026-06-01",
  "targetDate": "2026-11-15",
  "notes": "",

  "milestones": [ { "id": "m-1", "title": "...", "dueDate": "...", "status": "Planned|In progress|Done|Slipped", "notes": "" } ],
  "risks":      [ { "id": "r-1", "title": "...", "severity": "Low|Medium|High", "status": "Open|Mitigating|Closed", "mitigation": "", "owner": "" } ],
  "actions":    [ { "id": "a-1", "title": "...", "owner": "", "dueDate": "", "status": "Open|Done", "notes": "" } ],

  "createdAt": "...", "updatedAt": "..."
}
```

Design choices worth defending:

- **Health is a claim about reality, so it carries evidence.** `health` cannot be set without
  the option of a `healthNote`; the agent tool asks for the why. A red with no reason is noise.
- **Child items live inside the doc** (like subtasks in tasks): atomic updates, no fan-out
  reads, bounded size. If an engagement ever outgrows a doc, that engagement has bigger
  problems than storage.
- **`customer` is an alias, not a link.** We are not a CRM and do not pretend to be one
  (manifesto: never impersonate systems of record we don't own).

## State flow — the invariant extends, unchanged

`GET /sessions/{sid}/app/state` now returns `engagements: [...]` (full docs) alongside the
personal state. The UI — list page and detail page — renders **only** from that payload, which
is assembled from what the tools actually committed. Same for the post-tool state refresh over
SSE. No component ever renders an agent's textual claim about an engagement.

## Surfaces

- **REST** (`app.py`): `GET/POST /sessions/{sid}/engagements`,
  `GET/PATCH/DELETE /sessions/{sid}/engagements/{eid}`, and
  `POST/PATCH/DELETE .../engagements/{eid}/{milestones|risks|actions}[/{item_id}]` — mirroring
  the task endpoints' validation and outcome contract exactly.
- **Agent tools** (both harnesses, same seam): `list_engagements`, `create_engagement`,
  `update_engagement`, `set_engagement_health`, `add_engagement_item`,
  `update_engagement_item` — the item tools take `kind: milestone|risk|action` rather than
  spawning nine near-identical tools.
- **Navigation**: static route `/engagements`; per-engagement routes `/engagements/{id}`
  resolve by title exactly like task routes do. The `/engagements` route is normalized into
  older owner docs on read, so pre-existing deployments pick it up without a migration.
- **Frontend**: an Engagements list (health at a glance) and a detail page (health header,
  milestones/risks/actions sections, notes), manual CRUD to the REST endpoints — the To-Do
  page's twin.

## Multi-user: ready, not switched on

Engagement docs are shared by construction — nothing in them is keyed by the owner. What
remains for true multi-user is identity threading: the orchestrator already validates the
Entra JWT; passing the caller's `oid`/name into the session (and swapping
`appdb._owner_id()` to it for the *personal* scope) is the documented seam
([architecture.md](architecture.md#auth-and-trust-model)). Until then, `members` carries
names, and a single shared deployment behaves as one team member.
