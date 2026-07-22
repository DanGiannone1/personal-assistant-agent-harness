# Context (target design)

> **Authority:** Target design. Not a description of current behavior —
> [../product/overview.md](../product/overview.md) owns the current boundary. See "Where the current
> MVP stands" below for the honest gap to what is implemented today.

## The simple version

Context is what the app already knows so the user does not have to repeat it.

It includes simple things such as:

- Who the user is
- Which Engagement and record they are looking at
- What they have been working on recently
- Preferences they deliberately saved
- Rules that apply to the current Engagement
- Fresh facts such as due dates, blocked work, and permissions

When a session starts, the app composes the relevant pieces into one small bundle and hands it to the
assistant. It uses them to personalize quick links, understand requests such as "update this task,"
choose sensible defaults, and shape the assistant's response. The user can open **What I used** to see
exactly which pieces mattered.

Context should reduce repetition without becoming hidden or surprising.

## Platform-level context: the opening bundle

The failure this design targets is friction, not wrong answers. When an assistant makes a person pick
several menus before it can do or find anything, nobody uses it. Handing the app context it already
has is its own kind of failure, on par with an error — and in a large, mature product it is the more
common one.

Platform-level context is the fix: one small bundle the app composes **once, when a session starts**
(login or first message), so a person lands in their work instead of navigating to it. It answers
three questions before the user types anything:

- **Who are you** — role, tone, output preferences.
- **What matters now** — the small set of things that deserve attention today.
- **Where were you** — the Engagement and place you were last working.

The bundle is deliberately cheap and small: summaries and pointers, never record dumps. It never
decides access — every action still re-reads live state and re-checks permission when it runs.

### Two ways context reaches the assistant

Everything in the opening bundle arrives one of two ways:

- **Injected** — stored, owned, legible values written into the assistant's system context at session
  start: persona and saved workspace memory.
- **Live-queried** — small facts computed from current records at session start: the "what matters
  now" summaries (due, overdue, blocked, most-active Engagement) and the last place you were.

Deep sources — full documents, enterprise search, reference-knowledge retrieval — are **not** in the
bundle. They are fetched on demand by permissioned tools during a conversation, only when the
assistant actually needs them, and they are out of MVP scope regardless (retrieval is a non-goal; see
[../product/overview.md](../product/overview.md)). Keeping them out of the opening is what keeps login
fast and keeps us from rebuilding the bloated surface this design replaces.

### The context classes

The same discipline applies to every class: name where it is stored or grounded, how it reaches the
assistant, and who owns it. Six classes describe the whole platform; three are in MVP scope and three
are named but deferred.

| Class | What it holds | Delivery | Stored vs live | MVP |
|---|---|---|---|---|
| Persona | Role, tone, output preferences, language | Injected | Stored, user-editable | In scope |
| Workspace memory | Confirmed preferences and decisions; Engagement conventions | Injected | Stored, explicit confirm | Partial — conventions yes, free memory no |
| Live grounding / "what matters now" | Due, overdue, blocked, most-active Engagement, where you were | Live-queried | Live, never stored | To build |
| Documents | Files attached to an Engagement | Tool fetch on demand | Content live; pointers only | Deferred |
| Connected signals | Mail/calendar-style signals from a connected account | Tool fetch on demand | Live, consent-gated | Deferred |
| Reference knowledge | Shared, governed knowledge base | Tool fetch on demand | Retrieval index | Deferred |

The first three are the opening bundle. The last three sit behind tools and outside MVP scope; they
are listed so the shape is complete, not because the product builds them now. A finer-grained
storage-and-delivery breakdown of these classes is in the class table further below.

## What matters now (to be defined)

The hardest and most valuable part of the bundle is the "what matters now" list, and its ranking
model is **not yet decided** — that is the next piece of work, deliberately left open here. What is
already settled are the guardrails any answer must honor:

- **Rank by recency first, then urgency, then pins.** Start simple — most-recent and most-active work
  — and grow toward priority signals (due soon, overdue, blocked). The first version can be
  last-visited only.
- **Relevant items over volume.** Never surface raw change counts. A big number tracks how much access
  someone has, not what they should do.
- **Never invent an item.** If nothing is pressing, the list is short or empty. Missing stays missing;
  the app does not manufacture urgency.
- **Small.** A handful of items, each a short summary plus a pointer, not a record dump.
- **Carry "where you were" across login.** A returning user lands back in the Engagement and place
  they left, with a way to switch — not on a generic home screen.
- **Explainable.** Every item that appears is in `CONTEXT_APPLIED`, so "What I used" can show why it
  was chosen.

Deciding the ranking itself — the exact signals, their weights, and how far to lean on the model — is
the open question this section holds a place for.

## Why context matters

| Without useful context | With useful context |
|---|---|
| Everyone sees the same shortcuts | Quick links reflect the user's current work |
| "Add a task" needs a scope question | The current Engagement supplies a safe default |
| "Update this task" is unclear | The selected record makes the reference concrete |
| The user repeats style preferences | Confirmed preferences apply automatically |
| Personalization feels hidden | **What I used** explains every applied item |

## How it works

1. The backend confirms the signed-in actor and current screen.
2. It gathers relevant saved preferences, working history, Engagement conventions, and fresh app data.
3. It creates one context snapshot when the session starts.
4. The UI, assistant, and backend tools each receive only the part they need.
5. Tools still check current data and permissions before they act.
6. The app records a safe explanation for **What I used**.

The technical name for that snapshot is `SessionContext`. Different consumers receive
different views of it so private backend information is never placed in the model prompt.

## Rules that keep context trustworthy

1. **Identity is authenticated, not inferred.** Actor ID, session ownership, memberships, and
   permissions come from trusted transport and backend state.
2. **Stored is not grounded.** Persona and confirmed memory are durable. Tasks, dates, permissions,
   and current UI are queried or computed live rather than copied into memory.
3. **Context never authorizes.** It may rank permitted scopes and targets, but each read or mutation
   performs a live authorization check.
4. **Everything durable is legible.** Actors can view, edit, and delete persona, memories,
   conventions, pins, working context, and standing approvals.
5. **No silent memory.** An agent may propose durable memory, but only explicit confirmation stores
   it.
6. **One snapshot, fully explainable.** Every applied item records source, scope, reason, freshness,
   and precedence. The inspector renders that actual snapshot.
7. **Minimal by default.** Inject small summaries and pointers. Fetch records and document content
   lazily through permissioned tools.
8. **Conversation is not durable context.** A LangGraph checkpointer preserves thread continuity; it
   is not the source of persona, workspace memory, permissions, or live application facts.

## The canonical `SessionContext`

The logical schema is:

```json
{
  "id": "ctx-...",
  "asOf": "2026-07-13T14:00:00Z",
  "actor": {"id": "user-7", "displayName": "Dan"},
  "ui": {
    "destinationId": "destination:engagement:eng-42:tasks",
    "selectedResource": null
  },
  "scope": {
    "kind": "engagement",
    "id": "eng-42",
    "reason": "current_view"
  },
  "persona": {"role": "Engagement lead", "tone": "concise"},
  "memories": [],
  "conventions": [],
  "working": {"engagementId": "eng-42", "recentDestinationIds": []},
  "live": {
    "today": "2026-07-13",
    "timezone": "America/New_York",
    "salience": []
  },
  "retrieval": {"namespaceIds": ["personal:user-7", "engagement:eng-42"]},
  "applied": [],
  "omitted": []
}
```

This is a conceptual schema, not a promise that every projection exposes every field.

### Context classes and storage

| Class | Examples | Source of truth | Delivery rule |
|---|---|---|---|
| Identity | Actor ID, display name, memberships | Auth/session and account store | Trusted runtime only |
| Persona | Role, tone, output preferences, language | User-editable profile | Small prompt projection |
| Working context | Active Engagement, recent destinations, selected record | Per-user context doc plus current UI | UI, prompt, and tool projections |
| Durable memory | Confirmed preferences and decisions | User context doc | Relevant scoped items only |
| Engagement conventions | Language, reporting rules, delivery norms | Engagement document | Only when the turn touches that Engagement |
| Approval policy | Standing grants and restrictions | User context/policy store | Trusted tool projection; safe summary in inspector |
| Live grounding | Current route, records, due/blocked signals, membership | Queried from application state | Small computed summary; full data via tools |
| Documents | Session files and indexed corpus content | File and search stores | Pointers in context; content through cited retrieval |
| Conversation | Recent messages and tool results | LangGraph checkpointer | Model thread only, bounded separately |
| Behavioral signals | Visits, recency, bounded frequency, pins | Per-user context doc | Ranking features; raw history omitted from prompt |

Personal and Engagement data remain separate authorization scopes. Retrieval indexes must carry
owner/Engagement fields and apply mandatory filters before returning content — see
[rag-qa.md](rag-qa.md).

## Four projections from one bundle

### Prompt projection

The model receives only what improves interpretation or response style:

- Actor display name, never credentials or bearer tokens
- Date and timezone
- Validated current view and selected record label
- Resolved working scope with reason
- Relevant persona fields
- Relevant confirmed global memories
- Conventions for the active Engagement
- Small live summaries such as "2 overdue tasks," not full record collections

Documents, full task lists, membership lists, standing-approval tokens, and raw visit history stay
out. The agent uses tools when it needs those facts.

### Trusted tool projection

Backend tools receive opaque runtime context outside model arguments:

- Actor ID and session ownership
- `contextId` and snapshot time
- Validated UI destination and scope hints
- Effective capability hints and retrieval namespace filters
- Workspace binding

These are still hints, not cached authorization. Every tool re-reads current membership and relevant
state before acting.

### UI ranking projection

The app receives safe features and explanations for:

- Personalized quick links
- Working Engagement restoration
- Form defaults
- Salience badges

It contains destination IDs, scores, and reason codes, not model prompt text.

### Inspector projection

The "What I used" panel renders exactly what the composer emitted:

- Applied persona fields and memories
- Engagement conventions and why they matched
- Live grounding summaries and freshness
- Scope selection and precedence decisions
- Navigation candidate scores and context boosts when navigation ran
- Omitted or unavailable sources with reasons

Secrets, internal authorization tokens, inaccessible resource names, and hidden policy data are
redacted at composition time. The inspector never reconstructs context later from mutable state.

## Precedence is typed, not one universal list

Different conflicts have different authorities:

### Authorization

Live policy and membership are an absolute ceiling. No instruction, convention, persona, memory, or
model decision can override them.

### Facts

Live application state and permission-filtered cited retrieval beat durable memory. A stored memory
that says a task is open cannot override a live record that says it is done.

### Instructions and style

```text
explicit instruction in this turn
  > applicable Engagement convention
  > user persona or confirmed global preference
  > application default
```

Specificity wins; within one level, the most recently updated applicable item wins. The inspector
shows the winner and the shadowed item.

### Scope resolution

```text
explicit stable scope or resource in the turn
  > currently selected record or Engagement
  > Engagement encoded by the current view
  > sticky working Engagement
  > personal/default scope
```

Scope resolution narrows interpretation but does not grant membership. CRUD still fails on an
ambiguous update/delete target; navigation may decisively pick from viable permitted destinations.

## Composition at session start

The context composer runs once, when the session opens, at the authenticated session boundary — not
in the browser and not inside the model prompt:

1. **Authenticate.** Bind the actor and verify session ownership.
2. **Validate UI context.** Resolve the actor's landing route (or last place) against their live
   authorized destination catalog.
3. **Read durable context.** Load persona, confirmed memories, pins, working context, and standing
   approval metadata.
4. **Read applicable scope.** Load Engagement membership and conventions for candidate scopes.
5. **Compute live grounding.** Query current versions and derive the small "what matters now"
   summaries such as overdue or blocked counts.
6. **Select relevant context.** Apply scope, precedence, freshness, and token/field budgets.
7. **Build projections.** Produce prompt, tool, UI, and inspector views from the same immutable
   snapshot.
8. **Emit trace.** After `RUN_STARTED` for the session's first turn, emit `CONTEXT_APPLIED` before
   the first model or tool event.
9. **Execute.** The harness and tools reference `contextId`; tools reauthorize and read live state at
   call time.

The bundle is composed once and reused for the life of the session. It is immutable for
explainability. Because every tool re-reads live state, an action never relies on a stale bundle; a
new session — or an explicit refresh — recomposes. A small per-turn UI hint (the current view) may
still ride along with a message so navigation and CRUD can resolve scope, without recomposing the
whole bundle.

## `CONTEXT_APPLIED` event

The event is emitted once, when the opening bundle is composed at session start. It makes the
inspector evidentiary rather than decorative:

```json
{
  "type": "CONTEXT_APPLIED",
  "contextId": "ctx-...",
  "asOf": "2026-07-13T14:00:00Z",
  "scope": {"kind": "engagement", "id": "eng-42", "reason": "current_view"},
  "applied": [
    {"kind": "convention", "id": "conv-3", "reason": "scope_match"}
  ],
  "live": [
    {"kind": "salience", "summary": "2 overdue tasks", "freshness": "live"}
  ],
  "omitted": []
}
```

The trace event contains the inspector projection, not private tool context. Store the event or its
content hash with the session trace so later audits can prove what was supplied.

## How navigation uses context

Navigation is the clearest non-agent consumer:

- Quick links deterministically rank permitted destinations using working scope, recency, bounded
  frequency, pins, salience, and profile defaults.
- A click navigates immediately and asynchronously writes one navigation event.
- Natural-language navigation retrieves semantically viable destinations first, then uses context to
  rank or pick within that set.
- Context cannot add an inaccessible destination or make an irrelevant candidate viable.

See [navigation.md](navigation.md).

## How CRUD uses context

CRUD works without pre-navigation:

- Creates may default to a clearly active Engagement.
- Updates and deletes use context to rank only authorized candidates but require a unique target.
- Approval policy comes from trusted tool context, not the prompt projection.
- The committed outcome states which scope was used and supplies a canonical destination.
- Only a committed result causes post-action navigation.

See [crud.md](crud.md).

## Durable context lifecycle

### Persona and preferences

Actors edit persona directly in Settings. The agent may suggest a change, but it does not silently
infer and store one from ordinary conversation.

### Memory

1. The agent proposes a concise memory with scope (`global` or Engagement).
2. The backend returns a preview and confirmation token.
3. The actor confirms, edits, or rejects it.
4. The canonical CRUD/policy service stores the confirmed item and audit record.
5. Future composition includes it only when relevant and reports why.

Fast-changing facts do not belong in memory. Store "status reports use French"; query whether a task
is currently open.

### Behavioral context

Manual and agent navigation use one event contract. The backend atomically updates the capped visit
log and working Engagement. Actors can clear history, pin destinations, and change the working scope.
Frequency signals are bounded and old visits decay.

### Standing approvals

Approvals are durable policy, not model context. The prompt may receive a safe summary, while the full
grant and any confirmation tokens remain in trusted tool context and are revalidated at use.

## Deep Agents implementation

The harness already does a miniature version of this. Deep Agents builds a long-lived `AgentSession`
whose system prompt is set once, at session creation, by `create_deep_agent(system_prompt=SYSTEM_PROMPT
+ _user_prompt_line(user_id), ...)`, with an `InMemorySaver` checkpointer and the native LangChain
product tools (see [Assistant](../architecture/capabilities/assistant.md)). `_user_prompt_line`
already injects a two-fact grounding line — the actor's display name and today's date — at
`__aenter__`. Platform-level context is that line grown up.

### Where the bundle enters

Compose the opening bundle at session creation and write its **injected** projection into the same
`system_prompt` string, next to the grounding line:

- The session server already holds the authenticated actor when it creates the session — it forwards
  the actor outside the request body and checks the write-once session-to-actor binding. Before or
  during `AgentSession.__aenter__`, it asks the context service to compose the bundle for that actor.
- The injected projection (persona, workspace memory, and the "what matters now" and "where you were"
  summaries) is concatenated into `system_prompt` at creation — never into a user message. The browser
  stops assembling a bracketed preamble into the user's text.
- Because the session is long-lived and the system prompt is set once, this composes **once per
  session**, which is exactly the session-start decision. No per-turn recomposition is required.

### What does not change

- Tools stay closed over the bound actor and re-read live state and permission on every call. The
  bundle is a hint for the opening, never a cached grant.
- `InMemorySaver` keeps conversation continuity only. The bundle lives in the system prompt, set once;
  it is never written into the message history as if the actor said it.
- The twenty typed product tools and their `ProductToolResult` contract are untouched. Deep sources
  (documents, reference knowledge) would arrive as their own tools if and when they are in scope —
  never in the bundle.
- `CONTEXT_APPLIED` is emitted once, when the bundle is composed, and the inspector renders exactly
  that.

### Freshness and a light per-turn hint

Composing once means the opening summaries reflect the moment of login. That is correct for an opening
brief, and actions stay safe because every tool re-reads live state. Two follow-ons stay open: a
long-lived session may want an explicit refresh that recomposes, and a small per-turn UI hint (the
current view) may accompany a message so navigation and CRUD resolve scope without recomposing the
whole bundle. Neither is required for the first version.

### Harness note

`create_deep_agent` today exposes a static `system_prompt` and tool-exclusion middleware only; there
is no per-turn prompt callable wired in. Setting the bundle once at creation fits that shape without
new middleware. Per-turn dynamic context, if a later version wants it, is a harness change — a prompt
callable or middleware — and belongs in its own decision, not here.

The same context service and tool contract apply to the Copilot portability lane, so the AG-UI stream
stays harness-independent. Skills stay reusable procedural instructions; they may explain how to use
context but are not a context store.

## Security, privacy, and consistency

- Permission-trim every source before composition, ranking, or retrieval.
- Reauthorize every tool call against live state; never trust a permission snapshot alone.
- Namespace retrieval indexes by actor and Engagement before any indexed-corpus rollout (see
  [rag-qa.md](rag-qa.md)).
- Cap behavioral history and make it clearable.
- Keep raw documents and record collections out of prompt context unless explicitly retrieved.
- Redact secrets once, when creating projections, not ad hoc in the frontend.
- Log context IDs and provenance, not hidden chain-of-thought or picker reasoning.
- Treat missing context as an explicit degraded mode. Use safe defaults; do not invent values.
- Make context composition observable for latency, bundle size, source failures, and stale snapshots.

## Where the current MVP stands

| Target element | Current MVP status |
|---|---|
| Opening bundle composed at session start and injected into the system prompt | Not implemented. Today the system prompt gets only a two-fact grounding line (display name + date) at session creation; the browser assembles persona and conventions into the user's message text instead. |
| Composed `SessionContext` snapshot with a `contextId` | Not implemented. `GET /context-bundle` computes actor persona and, for an Engagement-scoped route, that Engagement's name/conventions — no persisted snapshot or ID. |
| "What matters now" list | Not implemented, and its ranking model is not yet decided. |
| `CONTEXT_APPLIED` trace event | Not implemented. No event records what context a turn received. |
| Four projections (prompt, trusted tool, UI ranking, inspector) | Only a prompt-style projection exists. The browser concatenates date, view label, persona, and conventions into the user's message text; there is no UI ranking or inspector projection. |
| Durable memory and standing approvals | Not implemented. |
| Working context (active Engagement, recent destinations, pins) | Not implemented. The context-bundle response has a `workingContext: {}` placeholder with no reader or writer. |
| Behavioral ranking and personalized quick links | Not implemented. |
| Typed precedence by conflict kind (authorization / facts / instructions / scope) | Partially. A flat precedence list is sent as prompt text (`turn instruction > engagement convention > user persona > app default`); it is a response-style convention, not a structural enforcement. The real authorization ceiling remains each tool's live re-read, matching this design's authorization rule. |
| Identity bound outside the model; actor/session write-once binding | Implemented today. |
| Tools re-authorize and re-read live state on every call | Implemented today. |
| Shared JSON-schema tool catalog across both harnesses | Implemented today — closer to this design's shared tool-layer goal than the rest of the context contract. |

See [Assistant](../architecture/capabilities/assistant.md) for the authoritative current-state
contract, including the exact turn path and evidence status.

## Architecture checklist

- [ ] One authenticated composer creates one immutable context snapshot at session start.
- [ ] Prompt, tool, UI, and inspector projections derive from that same snapshot.
- [ ] Identity and permissions never come from model-visible arguments.
- [ ] Context ranks/defaults but never grants access or replaces live reads.
- [ ] Persona and memory are user-visible; memory requires explicit confirmation.
- [ ] Fast-changing facts remain live and are not copied into memory.
- [ ] Precedence is explicit for authorization, facts, instructions, and scope.
- [ ] Prompt context is minimal; records and documents are retrieved lazily.
- [ ] `CONTEXT_APPLIED` records exactly what the harness received.
- [ ] The inspector renders the event, not a later reconstruction.
- [ ] Tools reauthorize and read current state at execution time.
- [ ] Quick links, semantic navigation, CRUD, and retrieval consume the same context contract.
- [ ] Deep Agents receives the opening bundle in its system prompt at session creation, never
      checkpointed as actor speech.
- [ ] Indexed-corpus retrieval is actor- and Engagement-filtered (see [rag-qa.md](rag-qa.md)).
