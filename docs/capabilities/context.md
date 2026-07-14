# Context — Canonical Capability Design

> **Authority:** Canonical detailed design for trusted per-turn context and personalization  
> **State:** Target design, reconciled with integrated `master@1fcaac6`  
> **Applies to:** Context composition, projections, precedence, grounding, and the context inspector  
> **Parent:** [CSA Workbench authoritative product and system design](../design.md)  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#15](https://github.com/DanGiannone1/personal-assistant-agent-harness/issues/15)

## The short version

Context is the small amount of trusted information CSA Workbench prepares for one assistant turn so the user
does not have to repeat who they are, where they are working, or how they prefer to communicate.

For a junior developer or technical product owner, the important distinction is:

- **Context helps interpret and personalize.** It can explain that the user is viewing the Website
  Launch Engagement and prefers concise English.
- **Tools establish facts and permission.** A tool must still reread membership and the current
  Engagement record before it reads or changes anything.
- **The inspector shows what was used.** “What I used” comes from the stored event for that exact
  turn, not from a later browser reconstruction.

CSA Workbench creates one immutable context snapshot on the server for every turn. The model, tools, UI, and
inspector receive different safe projections of that snapshot. The user message remains distinct
from trusted context. Changing persona, navigation, or membership after composition affects the next
turn or a live tool read; it does not rewrite the historical snapshot.

The MVP is deliberately small. It includes identity, the validated current destination, an active
Engagement when applicable, minimal persona, Engagement conventions, bounded recent visits, and the
current date. It does not include free-form memory, approvals, document content, retrieval
namespaces, connectors, or a semantic layer.

## Purpose and user outcomes

This capability should make the assistant feel situated without making it surprising or more
powerful than the signed-in user.

A successful implementation lets a user:

- say “add a task here” on an Engagement screen and have “here” resolve to that authorized
  Engagement;
- say “take me to the launch tasks” and receive a deterministic destination ranked by their own
  permitted recent work;
- receive an answer in their saved language and tone, with applicable Engagement conventions taking
  precedence;
- open **What I used** for a completed or failed turn and see the safe context items that actually
  reached the harness;
- trust that status, tasks, membership, and other changing facts came from live application reads;
  and
- continue safely with explicit defaults when optional personalization is unavailable.

Context does not make the UI dependent on the assistant. Direct forms, navigation, and state views
remain complete manual paths under the [UI/UX](ui-ux.md), [Navigation](navigation.md), and
[CRUD](crud.md) contracts.

## Deliberately minimal MVP schema

`TurnContext` is an internal server object. It is not a public REST resource and no consumer is
entitled to every field.

```json
{
  "contextId": "ctx-01J...",
  "asOf": "2026-07-14T14:00:00Z",
  "actor": {
    "actorId": "user-7",
    "displayName": "Dan"
  },
  "currentDestination": {
    "destinationId": "destination:engagement:eng-42:tasks",
    "route": "/engagements/eng-42/tasks",
    "label": "Website Launch tasks",
    "selectedResource": null
  },
  "activeEngagement": {
    "engagementId": "eng-42",
    "name": "Website Launch",
    "membershipRole": "editor",
    "reason": "current_view"
  },
  "persona": {
    "jobRole": "Solution architect",
    "tone": "concise",
    "language": "English",
    "timeZone": "America/New_York"
  },
  "conventions": [
    {
      "conventionId": "conv-3",
      "text": "Status documents are written in French."
    }
  ],
  "working": {
    "stickyEngagementId": "eng-42",
    "recentDestinations": [
      {
        "destinationId": "destination:engagement:eng-42:tasks",
        "visitedAt": "2026-07-14T13:55:00Z"
      }
    ]
  },
  "clock": {
    "today": "2026-07-14"
  },
  "applied": [
    {
      "kind": "engagement",
      "sourceId": "eng-42",
      "reason": "current_view"
    },
    {
      "kind": "convention",
      "sourceId": "conv-3",
      "reason": "active_engagement"
    }
  ],
  "omitted": []
}
```

The example is illustrative; the contract is the field meaning below:

| Field | Meaning |
|---|---|
| `contextId`, `asOf` | Stable correlation and composition time for one immutable snapshot |
| `actor` | Authenticated actor identity; never inferred from the message or browser |
| `currentDestination` | Browser hint resolved against the actor's current authorized destination catalog |
| `selectedResource` | Optional stable ID, kind, and safe label when the destination selects one record |
| `activeEngagement` | Authorized Engagement and current membership role, or `null` |
| `persona.jobRole` | The user's professional role for response framing, never an authorization role |
| `persona.tone`, `language` | Minimal user-editable response preferences |
| `persona.timeZone` | Account time zone; invalid or absent values resolve to `UTC` |
| `conventions` | All current conventions for the active Engagement, permission-trimmed |
| `working` | Bounded history used for navigation ranking and restoration, not raw prompt material |
| `clock.today` | Server-derived date in the effective account time zone |
| `applied`, `omitted` | Safe provenance and degraded-source explanations used to build the inspector event |

`membershipRole` is always separate from `jobRole`. Owner/editor/viewer controls access;
“solution architect” or “engagement lead” only changes framing and style.

Names are display values. Stable IDs remain authoritative, and duplicate names do not become unique
because context prefers one of them.

## Authoritative sources and freshness

Context composition reads each value from the narrowest authoritative source.

| Context value | Authoritative source | Freshness and validation |
|---|---|---|
| Actor ID | Validated sign-in plus immutable owned session/conversation binding | Required and re-established for every turn |
| Display name, persona, time zone | Actor account record | Read at composition; time zone defaults explicitly to `UTC` |
| Current destination | Browser-supplied destination ID/route resolved through the authorized destination catalog | Validate every turn; the browser label is never trusted |
| Selected resource | Resolved destination catalog entry | Include only after current membership/ownership validation |
| Active Engagement | Validated current destination only | Recheck membership during composition; sticky state remains a ranking/restoration input |
| Membership role | Current Engagement membership | Snapshot for explanation only; operations reauthorize live |
| Conventions | Current active Engagement aggregate | Read at composition; never load conventions for an inaccessible Engagement |
| Recent visits and sticky Engagement | Per-actor working-context record | Bounded, clearable, and trimmed against the current destination catalog |
| Date | Server clock evaluated in the account time zone | Recomputed every turn |
| Status, tasks, artifacts, membership changes, or other mutable facts | Application services and durable records | Read at tool use, not copied into prompt context |

The actor/session rules belong to [Identity and access](identity-access.md). Conversation ownership,
receipt durability, and rehydration belong to [Session and state](session-state.md). The context
composer consumes those contracts; it does not create a second identity or persistence model.

## Server-side per-turn composition

The authenticated turn coordinator owns composition. The browser may report its current destination,
but it cannot assemble trusted prompt text or decide what was applied.

```text
untrusted user text + untrusted UI destination hint
        ↓
authenticate actor and verify owned conversation/session
        ↓
validate destination against the actor's live destination catalog
        ↓
read account, working context, membership, and applicable conventions
        ↓
create one immutable TurnContext and its four projections
        ↓
persist the turn receipt; emit CONTEXT_APPLIED
        ↓
invoke AgentSession with user text kept separate from trusted context
        ↓
tools reauthorize and read current facts
```

The coordinator is a logical responsibility inside the authenticated backend, not a new
microservice. The [Agent harness](agent-harness.md) contract defines how each adapter receives a
per-turn prompt projection without turning it into user-authored speech or durable memory. The
browser never prepends bracketed context to the message.

Composition rules:

1. Reject the turn before model invocation if actor or owned-session validation fails.
2. Resolve the UI hint to an authorized destination. An invalid, stale, or inaccessible hint is
   omitted rather than trusted.
3. Read the actor record and normalize persona fields and time zone.
4. Determine the active Engagement from the validated current view. A permitted sticky Engagement
   may be retained for ranking or restoration when the view is neutral.
5. Load membership and conventions only for the resulting authorized Engagement.
6. Filter recent destinations against the current authorized catalog and apply the bounded history
   limit.
7. Build the immutable snapshot, its projections, and the safe inspector payload.
8. Persist and emit `CONTEXT_APPLIED` before the first model or tool event.

The snapshot does not update during a long turn. If state changes after composition, a tool result is
authoritative and may make part of the snapshot stale. The next turn recomposes.

## Four projections from one snapshot

### Prompt projection

The prompt projection contains only context that helps interpret the request or shape the response:

- actor display name, not actor ID;
- the validated current destination and selected-resource label when present;
- active Engagement name and the actor's membership-role label;
- `jobRole`, tone, language, and the effective time zone/date; and
- applicable Engagement conventions.

It excludes credentials, session IDs, raw visit history, full membership lists, full record
collections, mutable status summaries, document content, approvals, and internal authorization
state. User text remains a separate message. Static system policy remains small and cacheable.

### Trusted tool projection

The bound tool runtime receives trusted values outside model-visible arguments:

- actor, conversation/session, run, and context IDs;
- the validated destination and selected resource;
- the active Engagement ID as a scope hint; and
- the workspace/runtime binding required by the adapter.

These values remove the need for the model to choose identity or pass session IDs. They remain hints,
not authorization. Every application operation rereads current scope, membership, role, version, and
relevant facts under the [CRUD](crud.md) contract.

### UI and navigation projection

The UI/navigation projection contains permission-trimmed destination IDs and safe ranking reasons
needed for:

- quick links;
- sticky Engagement restoration;
- recent-work ranking; and
- safe form suggestions on an Engagement screen.

It contains no prompt text. Navigation ranking and ambiguity thresholds belong to
[Navigation](navigation.md). A sticky Engagement may raise or restore a destination, but it never
silently scopes a shared write from a neutral or personal screen.

### Inspector projection

The inspector projection is the safe, stored explanation of what personalized the turn. It includes:

- effective persona fields;
- validated current destination and active Engagement, with the reason it was selected;
- membership-role label;
- each convention supplied to the harness;
- safe recent-work ranking reasons when they affected navigation;
- context and composition timestamps; and
- omitted or degraded sources with reason codes.

It excludes secrets, raw tokens, hidden resource names, inaccessible candidates, full member lists,
raw visit logs, internal policy data, and hidden chain-of-thought. It is generated during composition,
not reconstructed from mutable state later.

## `CONTEXT_APPLIED`

Each turn persists and emits one context event after `RUN_STARTED` and before the first model or tool
event:

```json
{
  "type": "CONTEXT_APPLIED",
  "runId": "run-01J...",
  "contextId": "ctx-01J...",
  "asOf": "2026-07-14T14:00:00Z",
  "currentDestination": {
    "destinationId": "destination:engagement:eng-42:tasks",
    "label": "Website Launch tasks"
  },
  "activeEngagement": {
    "engagementId": "eng-42",
    "name": "Website Launch",
    "membershipRole": "editor",
    "reason": "current_view"
  },
  "applied": [
    {
      "kind": "persona.language",
      "value": "English",
      "source": "actor_account",
      "reason": "saved_preference"
    },
    {
      "kind": "convention",
      "sourceId": "conv-3",
      "value": "Status documents are written in French.",
      "source": "active_engagement",
      "reason": "scope_match"
    }
  ],
  "omitted": []
}
```

The event is the inspector projection, not the full internal context or raw serialized prompt. It is
emitted by the turn/harness boundary only after the trusted projection has been attached. The stored
receipt and streamed event share the same `runId` and `contextId`. The frontend renders this event for
**What I used** and does not refetch persona or conventions to reconstruct the past.

AG-UI framing, terminal-event behavior, cancellation, and harness parity belong to
[Agent harness](agent-harness.md). Receipt persistence belongs to
[Session and state](session-state.md).

## Precedence, scope, and grounding

There is no universal precedence list. Four different questions have different answers.

### Authorization ceiling

Current application policy and membership are absolute. No user instruction, convention, persona,
sticky Engagement, model decision, or old context snapshot can grant access. Context may narrow or
rank only resources already permitted to the actor.

### Mutable facts

Live application state wins. Status, tasks, artifacts, dates, membership, and permissions are read
through application services when needed. A persona field or free-text convention never overrides a
record. If the context snapshot and a later tool result differ, the tool result governs the turn.

### Response style and working conventions

```text
explicit instruction in this turn
  > applicable Engagement convention
  > actor persona
  > application default
```

The order is a behavioral instruction, not a semantic conflict engine. Conventions are free text.
CSA Workbench supplies all applicable conventions in a stable order and shows them in the inspector; it does
not claim to detect that two clauses conflict or to prove which phrase “won.” If conflicting
free-text conventions make the requested output materially ambiguous, the assistant surfaces the
conflict instead of inventing a deterministic resolution.

### Resource and write scope

```text
explicit stable Engagement/resource in the request
  > selected resource or Engagement in the validated current view
  > personal scope or an explicit scope question
```

Sticky Engagement and recent visits may rank and restore navigation. They do not silently default a
shared mutation from `/engagements`, Home, a personal screen, or another neutral destination. A
shared write requires an explicit target or an Engagement-bearing current view. Target resolution,
ambiguity, and committed route effects belong to [CRUD](crud.md) and
[Navigation](navigation.md).

## Privacy and degraded behavior

### Privacy rules

- Permission-trim every source before composition, ranking, persistence, or display.
- Keep actor IDs and runtime bindings out of the prompt and model-visible tool arguments.
- Keep raw recent visits out of the prompt; expose only safe ranking explanations in the inspector.
- Cap working history and provide a user-visible clear-history action.
- Keep records and document content in their authoritative stores until a permissioned tool reads
  them. Document lifecycle belongs to [Documents and retrieval](documents-retrieval.md).
- Store provenance and safe values, not chain-of-thought or private picker reasoning.
- Treat persona as user-authored account data. CSA Workbench does not infer or silently save a persona from
  ordinary conversation.

### Degraded behavior

| Failure | Required behavior |
|---|---|
| Authentication or owned-session binding fails | Reject before context composition or model use |
| UI destination is stale, invalid, or unauthorized | Omit it, reveal nothing about the target, and continue from a neutral context if safe |
| Persona cannot be read | Use documented app defaults; record `persona_unavailable` |
| Time zone is missing or invalid | Use `UTC`; record the default in the inspector |
| Working history cannot be read | Use unpersonalized permitted navigation ranking; record `history_unavailable` |
| Sticky Engagement is no longer authorized | Drop it without revealing the Engagement; record `sticky_scope_unavailable` |
| Conventions cannot be read | Do not invent them; record `conventions_unavailable` |
| Membership changes after composition | Tool reauthorization decides; deny or return not-found/forbidden as appropriate |
| Context receipt cannot be durably created | Do not invoke the model; the turn cannot meet the legibility contract |

Missing optional context reduces personalization, never authorization checks. Degraded context is
visible in `omitted`; it is not a silent fallback.

## Deliberate non-goals

The first professional release does not include:

- free-form agent memory, conversation-derived profile inference, or memory CRUD;
- standing approvals or policy tokens in context;
- retrieval namespaces, full records, document content, or cached mutable facts in `TurnContext`;
- M365, firm-knowledge, web, or other connector signals;
- a semantic layer, knowledge graph, ontology, scenario engine, or generic context platform;
- semantic conflict resolution for free-text conventions;
- a context microservice, external/shared-key MCP endpoint, or MCP migration as a prerequisite;
- cross-Engagement retrieval or an inferred Client scope; or
- background agents, schedulers, autonomous context refresh, or proactive memory formation.

Future durable memory requires a separate approved design. At minimum it must be explicitly
confirmed, scoped, visible, editable, deletable, and unable to store changing facts, permissions,
document copies, or approval authority. Conversation checkpoints remain conversation continuity,
not user memory.

## Current integrated state versus target

The following is static evidence from `master@1fcaac6`; runtime behavior remains **UNVERIFIED** until
captured by current behavioral evidence.

| Area | Current integrated evidence | Target |
|---|---|---|
| Actor/session binding | The orchestrator verifies session ownership before streaming and forwards the authenticated actor ([`app.py`](../../app.py#L332), [`session_manager.py`](../../session_manager.py#L213)); the session container reads `X-User-Id` ([`server.py`](../../session-container/server.py#L83)) | Preserve the trusted binding and keep it outside model arguments under the identity contract |
| Context endpoint | `GET /context-bundle` reads persona, route-derived conventions, and working context ([`app.py`](../../app.py#L1238)) | Compose one immutable context inside the authenticated turn rather than through a browser preflight |
| Browser prompt construction | The hook fetches the bundle, concatenates bracketed values into user text, and silently continues when the fetch fails ([`useAgentSession.ts`](../../frontend/src/hooks/useAgentSession.ts#L484)) | Keep user text unchanged; attach trusted context server-side and report degraded sources |
| Inspector | The panel renders the browser's last fetched bundle ([`AssistantPanel.tsx`](../../frontend/src/components/AssistantPanel.tsx#L129)) | Render the stored per-run `CONTEXT_APPLIED` event |
| Context shape | Frontend type contains user, persona, conventions, Engagement name, working context, and a flat precedence array ([`types.ts`](../../frontend/src/lib/types.ts#L128)) | Adopt the minimal schema, distinct roles, source reasons, and omitted-source reporting |
| Persona | Account records and a user-editable endpoint already exist ([`appdb.py`](../../session-container/appdb.py#L115), [`app.py`](../../app.py#L1216)) | Rename prompt semantics to `jobRole`; add an account time zone with explicit `UTC` default |
| Working history | Per-user context has a 50-entry visit cap and a sticky-context helper ([`appdb.py`](../../session-container/appdb.py#L653)); manual navigation records a route fire-and-forget ([`useAgentSession.ts`](../../frontend/src/hooks/useAgentSession.ts#L415)) | Validate destinations before recording, make history clearable, and wire sticky state only for ranking/restoration |
| Current-view labeling | The browser helper recognizes personal routes and otherwise falls back to Home ([`useAgentSession.ts`](../../frontend/src/hooks/useAgentSession.ts#L301)) | Resolve labels and selected resources from the authorized destination catalog |
| Harness entry | Both harnesses initialize static prompts; Deep Agents submits the browser-composed string as a user message and checkpoints the thread ([`agent_deepagents.py`](../../session-container/agent_deepagents.py#L1152), [`agent_deepagents.py`](../../session-container/agent_deepagents.py#L1179)); Copilot also exposes `send(prompt)` ([`agent.py`](../../session-container/agent.py#L1527)) | Extend the shared turn contract with a non-user context projection and emit the same event in both adapters |
| Live authorization | Engagement tool mutations recheck membership/role inside the update path ([`agent.py`](../../session-container/agent.py#L560)) | Retain live checks while moving domain rules behind the shared application service |
| Context event | The runtime event reducers have no `CONTEXT_APPLIED` path in the integrated baseline ([`useAgentSession.ts`](../../frontend/src/hooks/useAgentSession.ts#L423)) | Persist, stream, reduce, and render exactly one event per invoked turn |

The former design at `master@1fcaac6:docs/context-reference-architecture.md` remains useful history
but includes memories, approvals, retrieval namespaces, salience, and MCP migration beyond this
release. This document is the detailed authority for the deliberately smaller current target.

## Behavioral oracles

The [Testing and evals](testing-evals.md) document owns test layers, fixtures, commands, and release
profiles. The context capability must supply evidence for these behaviors through the real frontend,
authoritative state, and stored turn receipt:

1. **Identity isolation**  
   Given two actors with different persona and memberships, when each sends the same request, then
   each context event, prompt behavior, destination set, and tool result contains only that actor's
   permitted world.

2. **Current-view scope**  
   Given an editor is viewing Engagement A's tasks, when they say “add a task here,” then
   `CONTEXT_APPLIED` records Engagement A with `current_view`, the committed result names A's stable
   scope, and the authoritative Engagement contains the task.

3. **Neutral-screen write safety**  
   Given Engagement A is sticky but the actor is on Home or a personal screen, when they say “add a
   task” without naming a scope, then CSA Workbench does not silently create a shared task in A.

4. **Forged or stale destination**  
   Given a crafted UI hint names an inaccessible Engagement, when a turn starts, then no name,
   convention, destination, or existence signal from that Engagement appears in the prompt, event,
   trace, or result.

5. **Membership-revocation race**  
   Given context was composed while the actor was a member, when membership is removed before a tool
   mutation, then live authorization prevents the write and the assistant does not narrate success.

6. **Style precedence**  
   Given an English persona, a French Engagement convention, and an explicit “write this in German”
   instruction, then that turn is German; a later scoped turn without the override follows French.
   The inspector lists the sources without claiming clause-level semantic resolution.

7. **Live-fact grounding**  
   Given an Engagement status changes after context composition, when the actor asks for current
   status, then the answer follows the later live read rather than any context snapshot.

8. **Inspector immutability**  
   Given persona or conventions change after a completed turn, when the old inspector is reopened,
   then it still shows the original stored event and not the new account/Engagement values.

9. **Event ordering and parity**  
   For Deep Agents and the local Copilot parity path, the receipt shows `RUN_STARTED`, exactly one
   matching `CONTEXT_APPLIED`, then the first model/tool event, and exactly one terminal state.

10. **Explicit degraded context**  
    Given optional persona, history, or convention reads fail, when the turn can continue safely,
    then defaults and `omitted` reason codes are visible and no values are invented.

11. **History privacy and control**  
    Given invalid, old, cleared, or newly inaccessible visits, when navigation is ranked, then only
    current authorized destinations influence results; raw history is absent from the prompt.

12. **No silent memory**  
    Given ordinary conversation asks CSA Workbench to “remember this forever,” when a later conversation
    starts, then no durable free-form memory exists or affects context.

13. **Projection privacy**  
    For a captured turn, the model prompt and inspector contain no actor ID, credential, session
    token, full membership list, raw visit log, full record collection, or document content.

Exact assistant wording is not the oracle. The asserted relationship is between trusted context,
tool/turn receipts, live authorization, and authoritative application state.

## Reference-only IDA crosswalk

Local IDA context and semantic-layer HTML material was reviewed as a non-authoritative comparison.
It creates no CSA Workbench requirement and is not a source for CSA Workbench product behavior, architecture,
integration, ownership, or production constraints.

The useful conceptual crosswalk is:

| IDA reference label | Closest CSA Workbench concept | CSA Workbench boundary |
|---|---|---|
| User Persona | Actor `jobRole`, tone, language, and account time zone | Minimal, user-editable; no inferred behavioral overlay |
| Engagement Context | Active Engagement identity, membership role, and conventions | Engagement is the CSA Workbench scope; `customer` remains an alias, not a separate Client entity |
| Grounding (live work) | Permissioned application-service/tool reads | Read at use and never copied into memory or prompt snapshots |
| Engagement documents | Durable Engagement artifacts | Metadata stays with the Engagement; content is fetched through the document contract, not injected |
| M365 signals | No MVP mapping | Explicitly out of scope |
| Firm-wide knowledge | No MVP mapping | Explicitly out of scope |

CSA Workbench does not adopt the reference's six-type taxonomy as its schema. It also does not import its
scenario engine, thin/heavy MCP categories, A2A agents, semantic-layer discovery, context-procurement
program, Client domain, or ownership model. A future IDA adapter would have to enter through CSA Workbench's
authenticated application contracts and could not bypass actor, Engagement, tool, or receipt rules.

## Contract boundaries

This document owns the `TurnContext` meaning, source/freshness rules, four projections,
`CONTEXT_APPLIED` payload semantics, precedence, inspector behavior, and context-specific degraded
modes.

It intentionally links to rather than redefines:

- actor, session binding, roles, and disclosure behavior — [Identity and access](identity-access.md);
- conversation/receipt durability — [Session and state](session-state.md);
- destination catalog and ranking — [Navigation](navigation.md);
- operation scope, authorization, outcomes, and concurrency — [CRUD](crud.md);
- adapter delivery and AG-UI framing — [Agent harness](agent-harness.md);
- artifact and retrieval lifecycle — [Documents and retrieval](documents-retrieval.md);
- responsive inspector interaction and accessibility — [UI/UX](ui-ux.md); and
- evidence layers and release gates — [Testing and evals](testing-evals.md).
