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
- `tasks`, `events`, `library` — the same record shapes as the personal space, scoped to the
  engagement. Record tools take an optional `engagement` argument; empty means personal.
- `conventions` — working agreements the assistant applies when operating in this engagement.
- `activity` — a bounded feed (100 entries) of who did what, written inside every mutation.

**The delivery record** (how it's going):

- `customer` — free text, an alias, never a system of record.
- `stage` — `Discovery | Design | Build | Deploy | Live | Closed`.
- `health` + `healthNote` — green/amber/red, and **health always carries a why**: amber or red
  cannot be saved without a non-empty note. Enforced three times — the
  `set_engagement_health` tool returns `NOTE_REQUIRED`, the REST layer returns 422 (on the
  *resulting* state, so a patch can't blank the note out from under an amber), and the UI holds
  the color locally until a why is typed.
- `milestones` (`Planned | In progress | Done | Slipped`), `risks` (severity + mitigation,
  `Open | Mitigating | Closed`), `actions` (owner + due date, `Open | Done`) — managed by two
  kind-parametrized tools (`add_engagement_item`, `update_engagement_item`) and matching
  REST collections (`/engagements/{id}/milestones|risks|actions`).

Delivery-record mutations are **editor-level**; renames and membership stay **owner-level**.

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
