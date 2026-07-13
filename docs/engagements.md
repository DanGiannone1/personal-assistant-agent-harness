# Engagements — the first-class entity

An **engagement** is the unit of the job: one customer delivery, from Discovery to Closed. It is
both the team's **shared workspace** and the **delivery record** — one place where the status
that used to live in OneNote, Excel, and someone's head actually lives (see
[manifesto.md](manifesto.md)).

## The unified model

Each engagement is one Cosmos document (`eng-*`, its own logical partition), mutated only through
the ETag-safe read-modify-write path, and it carries two layers:

**The workspace** (who and what):

- `members` — `{userId, role}` with roles `owner ⊃ editor ⊃ viewer`. Membership IS
  authorization: non-members get a 404 (existence hidden), under-privileged members a 403 —
  enforced identically in the REST layer and the agent-tool layer.
- `tasks`, `library` — the same record shapes as the personal space, scoped to the
  engagement. Task tools take an optional `engagement` argument; empty means personal.
- `conventions` — working agreements the assistant applies when operating in this engagement.
- `activity` — a bounded feed (100 entries) of who did what, written inside every mutation.

**The delivery record** (how it's going — deliberately slim in v1, docs/mvp-requirements.md R7):

- `customer` — free text, an alias, never a system of record.
- `status` + `statusNote` — **Green/Yellow/Red**, and **status always carries a why**: yellow or
  red cannot be saved without a non-empty note. Enforced three times — the
  `set_engagement_status` tool returns `NOTE_REQUIRED`, the REST layer returns 422 (on the
  *resulting* state, so a patch can't blank the note out from under a yellow), and the UI holds
  the color locally until a why is typed.
- Parked for a later release (fields stay dormant in the data layer, no tools/routes/UI):
  the stage pipeline, milestones, risks, actions, and engagement-scoped calendar events.

Delivery-record mutations are **editor-level**; renames and membership stay **owner-level**.

### Artifacts

Every engagement carries durable artifacts: metadata (name, size, uploader) on the
engagement doc, bytes in a storage adapter (local directory in dev, Azure Blob via managed
identity in prod) that outlives any agent session. Any member can add, list, and open
artifacts; removing one requires editor or above. Bytes always stream through the
orchestrator's membership-gated API — there is no public or key-based path to them.

## The two scopes

The personal space ("your stuff": tasks, calendar, documents, reminders) stays private per user.
Engagements are "our stuff" — shared with exactly the members, nothing else. One assistant
operates both, and answers engagement status questions ("which engagements are red?") from
`list_engagements`, never from memory.

## Navigation

Engagements are destinations like everything else: `/engagements`, `/engagements/{id}` and its
tabs, plus every engagement record, all resolvable by the deterministic resolver with the
user's visit log as context (see
[navigation-reference-architecture.md](navigation-reference-architecture.md)).
