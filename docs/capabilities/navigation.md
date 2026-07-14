# CSA Workbench Navigation Capability

> **Authority:** Canonical subordinate contract for destination discovery, navigation resolution,
> route effects, and navigation context  
> **State:** Target v1 design, reconciled with integrated `master@1fcaac6`  
> **Parent:** [Authoritative Product and System Design](../design.md)  
> **Related contracts:** [UI/UX](ui-ux.md) · [Context](context.md) · [CRUD](crud.md) ·
> [Agent harness](agent-harness.md) · [Identity and access](identity-access.md) ·
> [Session and state](session-state.md)  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#15](https://github.com/DanGiannone1/personal-assistant-agent-harness/issues/15)

## The short version

CSA Workbench navigation should feel like navigation in a professional workspace, not like a conversation
with a routing bot.

1. The complete manual navigation is always available.
2. A sidebar item, card, quick link, bound chip, or committed CRUD result already identifies a real
   destination, so the client opens it immediately without asking a model.
3. When a user describes a destination in natural language, one deterministic resolver matches the
   words against the live places that user may open.
4. Wording determines whether a destination is relevant. Recent work may break a close tie, but it
   can never authorize a destination or make an unrelated result relevant.
5. A clear result moves the UI. Ambiguity, not-found, failure, cancellation, and stale authorization
   leave it in place.

The first release uses lexical matching plus bounded context ranking. It has no embedding index,
vector search, or model picker. Those mechanisms would add a second routing system before the
deterministic one has shown a real limitation.

## Purpose and user journeys

Navigation serves two user jobs: finding work quickly and preserving trust when the user's words
could mean more than one thing.

### Pick up work manually

A solution architect opens CSA Workbench and sees their Engagement portfolio, full navigation, and a few
permission-trimmed quick links. Clicking **Website Launch**, **Tasks**, or a recent artifact opens it
immediately. The assistant and agent runtime are not involved. The accepted navigation is recorded
as a bounded behavioral event after the route changes; failure to record it does not undo the
visible navigation.

### Ask for a known place

The user says, "open Product Launch tasks." The assistant passes those destination words to one
`navigate(intent)` tool. The backend finds a strong lexical match in the user's live catalog,
revalidates it, and returns a structured resolved destination. The client follows that route effect
without parsing assistant prose.

### Resolve a close call from recent work

The user belongs to Website Launch and Product Launch and says, "open the launch tasks." If Website
Launch tasks are decisively more recent, the resolver opens them and shows Product Launch tasks as
a bound **Did you mean** alternate. This is still deterministic. Clicking the alternate is direct
client navigation, not a second model turn.

### Keep a genuine ambiguity honest

The same request with no distinguishing wording or recency leaves the current view unchanged and
shows the viable destinations as bound chips. The user chooses one directly. CSA Workbench does not pretend
that an arbitrary catalog order is confidence.

### Fail without wandering

"Open the crypto mining dashboard" has no viable destination. CSA Workbench returns `not_found`, keeps the
current view, and may show permitted closest-place chips. It never falls back to Home or the first
search result while claiming success.

### Open the result of a change

After an authorized task creation commits, the CRUD result already contains the new task's canonical
destination. The client follows that destination directly. It does not call semantic or lexical
navigation to rediscover the record the backend just created. See the [CRUD contract](crud.md).

## One destination catalog

The backend owns one live destination catalog. It is the shared source for:

- the complete sidebar and drawer navigation;
- Engagement, task, artifact, and other record cards;
- personalized quick links;
- natural-language resolution;
- ambiguity, not-found, and alternate chips; and
- canonical destinations returned by committed CRUD outcomes.

The catalog combines static application surfaces with dynamic destinations derived from live
personal and Engagement state. It is derived rather than copied into a second durable route table.
Names and aliases help matching, but stable destination and resource IDs establish identity.

```ts
type Destination = {
  id: string;                   // stable, opaque catalog identity
  title: string;                // safe user-facing label
  route: string;                // generated only by the catalog
  kind: string;                 // engagement, engagement-tasks, task, artifact, ...
  scope:
    | { kind: "personal" }
    | { kind: "engagement"; id: string };
  aliases: string[];
  version: string;              // app or resource version used for revalidation
  exposure: {
    manual: boolean;            // may appear in the complete navigation
    quickLink: boolean;         // may appear in personalized shortcuts
    assistant: boolean;         // may be selected by navigate(intent)
  };
};
```

Exposure describes where an already-authorized destination belongs; it is not permission. For
example, the assistant workbench may be manually reachable without being a useful target for
`navigate(intent)`. Every channel still consumes the same catalog entry rather than defining its
own route.

### Permission trimming and revalidation

Catalog construction starts with the authenticated actor, not with a model-visible user or scope
argument:

1. Personal destinations are derived only from that actor's records.
2. Engagement destinations are derived only after live membership succeeds.
3. Exposure filters are applied after permission trimming.
4. Context ranks only the remaining authorized set.
5. An agent-selected dynamic destination is resolved again by ID and reauthorized immediately
   before a route effect is returned.
6. The destination's page-data loader rechecks authorization when the client opens it. A stale
   client destination never grants data access.

Non-membership is indistinguishable from non-existence. Inaccessible titles, aliases, scores, and
suggestions never enter model, trace, inspector, or UI payloads. Navigation itself is not an access
control mechanism; the [Identity and access contract](identity-access.md) owns the final read and
mutation boundaries.

## Immediate known-destination navigation

A UI control that already holds a `Destination` uses the client router immediately:

```text
sidebar / drawer / card / quick link / bound chip
  -> applyKnownDestination(destination)
  -> render the destination
  -> asynchronously record one accepted navigation event
```

This path does not wait for an agent, context write, embedding, search, or state refetch. The client
never constructs a dynamic route from names or record fields. A static fallback menu may be shipped
with the application shell, but it is generated from the same static catalog definitions.

An accepted event has this bounded form:

```ts
type NavigationEvent = {
  destinationId: string;
  source: "sidebar" | "drawer" | "card" | "quick_link" | "chip" | "assistant" | "crud";
  occurredAt: string;
  decisionId?: string;
};
```

The backend resolves `destinationId` again before storing the event. The browser does not submit an
authoritative title, route, actor, or Engagement ID. Visit storage is capped per actor and is
described as user data in the [Context contract](context.md).

## Quick links

Quick links are a small projection of the actor's permitted catalog, not an AI feature and not a
replacement for complete navigation.

- Use the same context score as natural-language tie-breaking, with no lexical input.
- Exclude Home, the current destination, and entries with `exposure.quickLink=false`.
- Return at most five destinations.
- Sort by score descending, then explicit catalog order, then destination ID.
- When every context score is zero, use the documented cold-start catalog order beginning with the
  Engagement portfolio and primary workspace surfaces.
- Return safe reason codes such as `recent`, `overdue`, or `due_today` for the context inspector.
- Never hide low-ranked permitted destinations from the complete navigation.

A quick-link fetch or visit-write failure is non-fatal. CSA Workbench keeps the full navigation and either
uses the cold-start shortcuts or hides the personalized section; it does not fabricate behavioral
reasons.

## Deterministic natural-language resolution

The model sees one narrow tool:

```text
navigate(intent: string) -> NavigationResult
```

It supplies only the user's destination words. Actor, session, current destination, permissions,
recent visits, and active Engagement are runtime-bound context, not model-controlled arguments. Both
harnesses adapt to this one product service; neither owns a copied resolver. See the
[Agent harness contract](agent-harness.md).

### Result contract

```ts
type NavigationResult =
  | {
      status: "resolved";
      destination: Destination;
      alternates: Destination[];
      decision: {
        id: string;
        method: "exact" | "lexical" | "context";
        reasons: string[];
      };
      routeEffect: { type: "navigate"; destination: Destination };
    }
  | {
      status: "ambiguous";
      candidates: Destination[];
      decision: { id: string; reasons: string[] };
    }
  | {
      status: "not_found";
      suggestions: Destination[];
      decision: { id: string; reasons: string[] };
    }
  | {
      status: "failed";
      code: string;
    };
```

Only `resolved` carries a navigation route effect. `ambiguous`, `not_found`, and `failed` do not
move the UI. The backend says `resolved`, not `navigated`, because the client may still cancel or
supersede the effect. A `navigated` trace state is emitted only after the client accepts it.

The result and AG-UI event are structured data. Harnesses and clients must not classify outcomes or
recover destinations by parsing marker prose, tool names, delimiters, or assistant text.

### Normalization and lexical score

The resolver is case-insensitive and deterministic:

1. Trim and lowercase the intent.
2. Tokenize with `[a-z0-9]+`.
3. Remove navigation filler words such as `a`, `the`, `my`, `take`, `me`, `go`, `open`, `show`,
   `page`, `screen`, `view`, and the generic scope words `engagement` and `project`.
4. Score every `assistant=true` destination in the permission-trimmed catalog:

| Signal | Lexical score |
|---|---:|
| Exact normalized title, alias, or canonical route | `100` |
| Full query phrase occurs in title or alias, with query length at least 3 | `+40` |
| Content-token coverage | `+30 × matched query tokens / query content tokens` |
| Title specificity | `+10 × min(matched tokens / title tokens, 1)` |

A candidate with no lexical score is not viable. When a match rests on a generic keyword and leaves
unexplained content words, reject it if its lexical score is below `40`. This is the fail-loud guard
that prevents “crypto mining dashboard” from resolving to Home solely because Home has a
`dashboard` alias.

### Context score

Context is applied only to lexically viable candidates. V1 uses bounded, inspectable signals:

| Signal | Context score |
|---|---:|
| Most recent matching visit among the newest 30 | `6, 5, 4, 3, 2, 1`, then `0.5` by visit position |
| Record is overdue | `+4` |
| Record is due today | `+3` |

Only the most recent matching visit contributes; repeated frequency does not compound. The visit log
is capped at 50 entries. V1 deliberately avoids frequency loops, inferred preferences, embeddings,
and model judgment.

Sort candidates by total score descending, then explicit catalog order, then destination ID. The
secondary keys make equal-score output reproducible rather than accidentally dependent on query or
collection order.

### Decision semantics

Let `top` and `second` be the two highest-ranked viable candidates:

1. No viable candidate returns `not_found` with at most five permission-trimmed quick-link
   suggestions.
2. One viable candidate returns `resolved`.
3. A clear lexical winner returns `resolved` when either:
   - `top.lexical >= second.lexical + 12`, or
   - `second.lexical > 0` and `top.lexical / second.lexical >= 1.6`.
4. If the lexical scores differ by less than `12`, context may decide only when
   `top.total >= second.total + 3`. This returns `resolved`, `method=context`, and at most five
   other candidates whose lexical score is within `12` of the winner as `alternates`.
5. Otherwise return `ambiguous` with at most six viable candidates whose total score is within `12`
   of the top.

Lexical relevance therefore beats familiarity. Context settles a relevant close call; it cannot
revive an irrelevant candidate. Thresholds are named product policy constants and changes require
behavioral evidence, not prompt tuning.

### Live revalidation

Before returning `resolved`, the service reloads the selected destination by ID and checks its
current existence, version, membership, and exposure. If it became stale, the service removes it
and may make one deterministic decision from the remaining already-viable candidates. It never
widens the search. If no safe result remains, it returns `not_found` or `failed` and no route effect.

## Bound chips and alternates

Every chip is rendered from a complete `Destination` object supplied by the backend:

- **Ambiguous:** labeled as a choice; no route has occurred.
- **Not found:** optional “Closest places” suggestions; no route has occurred.
- **Resolved by context:** the route effect is applied and alternates appear under “Did you mean”.
- **Resolved by exact or clear lexical match:** no alternates are shown.

Clicking a chip calls `applyKnownDestination(destination)`. It never sends “take me to …” back
through the conversation, calls `navigate` again, or trusts a route encoded in prose. Titles may
contain punctuation, semicolons, or vertical bars without changing the destination because there is
no delimiter-based wire format.

## Route effects, concurrency, and cancellation

The client owns visible route application. Product data refresh is separate from route choice.

1. Every asynchronous agent or CRUD operation captures the client's current navigation epoch when
   it starts.
2. A manual sidebar, drawer, card, quick-link, or chip navigation applies immediately and increments
   that epoch.
3. A later route effect is accepted only when:
   - its turn/request is still active;
   - it is structured and carries a catalog `Destination`;
   - its outcome is `resolved`, or `committed` under the [CRUD contract](crud.md);
   - live destination revalidation succeeded; and
   - no newer manual navigation has changed the epoch since the operation started.
4. A newer manual navigation always wins over a trailing assistant or CRUD effect.
5. Cancellation invalidates every unapplied route effect from that turn. It does not undo a domain
   mutation that already committed.
6. Navigation does not durably mutate a shared `currentRoute` before client acceptance. The browser
   route is the visible truth; the next turn supplies it as an untrusted hint for catalog validation.
7. Authoritative data is refetched after tool completion. Only the newest issued refresh may update
   client data, and a refresh never changes the route by inference.

This avoids inferring navigation from tool-name allowlists or from a later state snapshot. The client
can trace `route_effect_received`, `route_effect_superseded`, `route_effect_cancelled`, and
`navigation_applied` without claiming that a suppressed effect navigated.

## Failure and degraded behavior

| Condition | Required behavior |
|---|---|
| Ambiguous intent | Keep current route; show bound candidates and a neutral trace outcome |
| No viable destination | Keep current route; show honest not-found and optional permitted suggestions |
| Catalog or authorization lookup fails | Return `failed`; reveal no partial dynamic candidates; do not move |
| Selected destination becomes stale or membership is revoked | Revalidate, suppress route effect, and return not-found/failed without leaking the resource |
| Quick-link service fails | Keep complete navigation; use cold-start links or hide personalization |
| Visit write fails | Keep the accepted visible route; mark behavioral context unavailable rather than fabricating it |
| Structured result is absent or malformed | Treat as neutral/failed; never infer success from tool completion or prose |
| Route component cannot render | Show a specific recoverable not-found/error state; never silently render Home or another screen |
| Agent runtime is unavailable | All manual navigation and page authorization continue to work |
| Turn is cancelled | Ignore buffered route effects; preserve truthful state for any already-committed mutation |
| State refresh arrives out of order | Drop it when a newer refresh was issued |

Failure details belong in the stored behavior receipt and user-facing trace without exposing hidden
authorization data. Terminal event and cancellation ownership are defined by the
[Agent harness](agent-harness.md) and [Session and state](session-state.md) contracts.

## Responsive and accessible touchpoints

Navigation presentation follows the [UI/UX contract](ui-ux.md):

- Wide screens show stable navigation, the fluid Engagement workspace, and the assistant dock.
- Compact screens collapse primary navigation and present the assistant as a sheet rather than
  squeezing the workspace.
- Narrow web screens down to 390 CSS px show one primary surface at a time with drawer navigation
  and Chat/Artifact switching.
- Quick links and destination chips wrap without horizontal clipping. Their full labels remain
  available to assistive technology.
- Sidebar items, drawer items, cards, and chips are native keyboard-operable controls with visible
  focus and non-color active state.
- Opening and closing drawers or assistant sheets manages focus and restores it to the invoking
  control.
- Route changes announce the new page title through the application landmark. Ambiguous and
  not-found outcomes are announced without stealing focus from the available chips.
- Reduced-motion settings remove route pulses or transitions without removing state feedback.

Responsive web support does not imply a native mobile or offline product.

## Simplifications and non-goals

- No vectors, embeddings, semantic destination index, or model picker in v1.
- No model call for known destinations, quick links, chips, or committed CRUD destinations.
- No route generation by the main model, harness, or browser.
- No copied resolver or route registry per harness or UI surface.
- No marker strings, delimiter parsing, or assistant prose as a navigation protocol.
- No frequency reinforcement, inferred favorites, hidden profile ranking, or free-form navigation
  memory in v1.
- No use of navigation context to grant access, bypass role checks, or silently scope a shared write.
- No hiding the long tail of permitted destinations because they rank poorly.
- No dependency on Search, MCP, or a new microservice solely to implement navigation. The catalog
  and resolver are application-service responsibilities; transport remains an adapter choice.
- No IDA-specific route model or UI dependency. CSA Workbench is the standalone product.

## Current implementation and target gaps

Useful foundations already exist in integrated `master@1fcaac6`:

- `session-container/navsvc.py` derives destinations from live personal and member Engagement state
  and shares one lexical/context ranker between natural-language resolution and quick links.
- `appdb.list_engagements_for` trims Engagements by membership before both harnesses and the
  quick-link endpoint call the resolver.
- Both harnesses pass the user's destination words to `navsvc.resolve` and surface ambiguity,
  not-found, and context-decided alternates.
- The frontend already makes quick links and candidate chips direct client navigation.
- `useAgentSession.ts` contains last-issued-wins refresh sequencing, manual-versus-agent tracking,
  and buffered-event cancellation guards.

The target still requires these corrections:

| Current evidence | Gap to this contract |
|---|---|
| `navsvc._STATIC`, `appdb._seed_space().routes`, and `WorkbenchNav` define separate route lists | Replace them with one catalog; `/settings`, `/assistant`, and `/engagements` currently differ across lists |
| `navsvc` emits personal event routes such as `/calendar/{id}`, while `WorkbenchApp` handles only exact `/calendar` | Every catalog destination must have a real renderable route; unknown routes must not fall through to Home |
| Resolver outputs are marker strings with `CHIPS: title|path; ...`, parsed independently by both harnesses | Return structured `NavigationResult` and `Destination` objects; punctuation in titles must be inert data |
| The client infers routing from `ROUTE_SETTING_TOOLS` and refetched `currentRoute` | Follow only explicit resolved/committed route effects |
| Navigate tools write durable `currentRoute` before the client sees the result | Move route application to the client so cancellation and supersession are truthful |
| `follow` is captured when a refresh is issued | Recheck the navigation epoch when applying an effect; refreshes never route |
| `/visits` accepts arbitrary browser-supplied path and title | Accept a destination ID and validate it against the actor's current catalog |
| `workingContext` has a setter but no navigation caller updates it | Derive active scope from validated accepted destinations or remove the unused claim |
| Quick links omit destination IDs and explanation reasons and depend on insertion order for ties | Return the shared destination contract, reason codes, and explicit cold-start/tie order |
| The older navigation reference still prescribes embed/search/model-pick and says quick links/Deep Agents parity are absent | This capability document supersedes that speculative and stale navigation direction |

The former navigation reference and personalization exploration remain available in Git history at
`master@1fcaac6`. Where they conflict, this document and its controlling
[product design](../design.md) own the target.

## Behavioral oracles

Verification must reconcile the real UI, the structured navigation/turn receipt, and authoritative
state. A route string in prose or a green command is not proof.

| Case | Starting conditions and action | Required observable oracle |
|---|---|---|
| Manual known destination | Click a sidebar item or record card | Correct screen renders immediately; no agent/tool call; one validated visit is eventually recorded |
| Quick link | Click a personalized shortcut | Correct permitted screen renders directly; no assistant turn; reason code is inspectable |
| Exact lexical match | Ask “open Product Launch tasks” | Exactly one `navigate` call; `status=resolved`, `method=exact/lexical`; correct destination and route effect |
| Relevance beats familiarity | Visit Website repeatedly, then explicitly ask for Product settings | Product settings resolves; familiarity does not redirect; no context alternates for a clear lexical winner |
| Context-decided tie | Two Launch Engagements are viable; one task page is decisively more recent | Recent page resolves with `method=context`; other close page appears as a bound alternate |
| Cold ambiguity | Same destinations, no differentiating wording or recent visit | Route stays unchanged; `status=ambiguous`; at least two authorized bound chips; trace does not say navigated |
| Not found | Ask for “crypto mining dashboard” | Route stays unchanged; `status=not_found`; no unrelated automatic landing; suggestions are authorized |
| Membership trimming | Actor names an Engagement they do not belong to | Not-found behavior indistinguishable from unknown; no inaccessible name in candidates, alternates, suggestions, or trace |
| Membership race | Remove membership after candidate ranking but before effect creation | Live revalidation suppresses the route effect; no protected data renders |
| Bound-chip click | Click an ambiguity, not-found, or alternate chip | Direct client navigation; zero additional messages, model calls, or `navigate` calls |
| Punctuation safety | Destination title contains `;`, `|`, quotes, or Unicode | Exactly one chip with the correct catalog ID/route; no parsing or injected destination |
| Committed CRUD destination | Create or update a task successfully | CRUD returns `committed` with catalog destination; client follows it; no `navigate` tool call |
| Failed/no-op CRUD | Mutation is invalid, ambiguous, forbidden, no-op, or uncommitted | No route effect and no visible route change |
| Newer manual navigation | Start an agent/CRUD operation, then manually open another destination before its effect arrives | Manual destination remains; trailing effect is recorded as superseded |
| Cancellation | Cancel before a navigation effect is applied | No route change now or after rehydration; cancelled effect is traceable; already-committed data remains truthful |
| Out-of-order refresh | Delay an older state fetch until after a newer one completes | Older snapshot is dropped and cannot change data or route |
| Catalog degradation | Make dynamic catalog loading fail | Natural-language navigation fails closed with no leaked candidates; manual static shell remains usable |
| Visit degradation | Make visit storage fail after a valid click | User remains on the chosen page; next context reports unavailable behavior signal |
| Harness parity | Run the same deterministic cases through Deep Agents and Copilot | Same statuses, destination IDs, candidates, effects, and terminal semantics; exact prose need not match |
| Wide responsive | Exercise navigation and chips at a wide desktop viewport | Stable nav and dock remain visible; no clipping or obscured destination controls |
| Compact responsive | Exercise the same cases below the wide breakpoint | Collapsed nav and assistant sheet work by keyboard and pointer; manual route still wins races |
| Narrow responsive | Exercise at 390 CSS px and 200% zoom | One surface at a time; drawer/chips reflow without horizontal loss; focus and announcements remain correct |

Focused deterministic tests should prove catalog construction, authorization trimming, scores,
thresholds, and outcomes. Integration tests should prove REST/tool adapters share those rules.
Playwright should prove the real route, responsive controls, direct-chip behavior, races, and
cancellation while reconciling stored receipts. Both harnesses run the core local contract, but the
deployed Deep Agents path is the release proof.
