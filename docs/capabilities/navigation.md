# Navigation Capability

> **Authority:** Detailed navigation design subordinate to [the authoritative design](../design.md)
>
> **State:** Target MVP contract with current gaps called out below
>
> **Applies to:** Manual navigation, assistant navigation, route effects, and navigation evidence
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## The short version

People navigate CSA Workbench in two ways:

1. They click a visible UI control that already owns a destination.
2. They ask the assistant, which calls a typed navigation tool with a destination identifier.

Both paths end at the same validated destination catalog. Neither path extracts a route from user
text, assistant prose, marker strings, tool names, or raw stream data.

The model may interpret what the person meant. The application remains responsible for validating
where the model asked to go and whether the signed-in actor may go there.

## User outcomes

- A CSA can open their Engagement portfolio immediately.
- A member can open a specific Engagement from a list, card, link, or assistant request.
- A stale, malformed, or unauthorized destination does not move the UI.
- An ambiguous request results in a question or structured choices, not a guessed route.
- Navigation behaves consistently in the wide sidebar, compact layout, and narrow drawer.

## Design rules

1. **Routes are data, not prose.** A route effect is a structured object with a catalog ID and
   canonical path.
2. **The catalog is authoritative.** Every UI link and agent navigation request resolves through one
   destination catalog.
3. **The actor is bound outside the model.** The model never supplies a user ID or role.
4. **Authorization is checked at use time.** A destination that was once valid can be rejected after
   membership changes.
5. **The newest human action wins.** A delayed agent result cannot override navigation the user made
   after the turn began.
6. **Text is never a control protocol.** Chat content and rendered assistant content are inert.

## Destination catalog

The catalog is a small application-owned registry. Static destinations are defined in code; scoped
destinations are completed with an authorized resource ID.

```ts
type DestinationId =
  | "engagements"
  | "engagement_overview"
  | "engagement_tasks"
  | "engagement_artifacts"
  | "workbench";

type Destination = {
  id: DestinationId;
  path: string;
  label: string;
  engagementId?: string;
};
```

The MVP catalog stays intentionally small. A capability does not receive a route merely because a
frontend component exists. Routes that survive from older Personal Assistant screens are not active
MVP destinations unless the root design names them.

The backend owns canonical path construction. The browser and model may request a catalog ID and
resource ID; they do not construct arbitrary paths.

## Manual navigation

Sidebar items, drawer items, Engagement cards, breadcrumbs, and structured suggestion buttons carry
a complete destination object or enough stable identifiers to request one. Clicking them navigates
immediately after local shape validation.

Manual controls do not send their labels through the model and do not ask a text resolver where to
go. A visual label may change without changing the destination contract.

## Assistant navigation

The harness exposes a narrow product tool:

```ts
type NavigateCommand = {
  destinationId: DestinationId;
  engagementId?: string;
};

type NavigateResult =
  | { status: "resolved"; destination: Destination }
  | { status: "ambiguous"; choices: Destination[] }
  | { status: "invalid"; message: string }
  | { status: "not_found" }
  | { status: "forbidden" }
  | { status: "failed"; message: string };
```

The tool adapter binds the authenticated actor and session outside `NavigateCommand`. It then:

1. validates the command schema;
2. resolves the catalog entry;
3. loads any referenced Engagement;
4. checks current membership;
5. returns a canonical structured result; and
6. emits a structured route effect only for `resolved`.

If the model needs an Engagement ID, it uses an authorized read tool such as `list_engagements` or
`get_engagement`. It does not pass the original chat message into a keyword resolver.

## Structured route effect

A successful tool result is translated into an explicit event:

```ts
type NavigationEvent = {
  type: "NAVIGATION_RESOLVED";
  runId: string;
  destination: Destination;
  requestedAtNavigationVersion: number;
};
```

The frontend reducer accepts the event only when:

- its schema is valid;
- its `runId` belongs to the active conversation turn;
- the destination exists in the client catalog;
- the path matches the catalog entry and identifiers;
- the current navigation version still equals `requestedAtNavigationVersion`; and
- no terminal error or cancellation invalidated the run.

The assistant's visible sentence is unrelated to that decision. Text such as “Opening the
Engagement now,” a URL, `NAVIGATE:`, `CHIPS:`, JSON-looking prose, or a tool name cannot move the UI.

## Ambiguity and choices

The application does not guess among duplicate Engagement names. An authorized lookup may return
multiple structured choices. The assistant asks the person to choose, or the UI renders buttons
whose destination objects are already bound.

Selecting a choice is a direct product action. It does not send “the first one” through another
model turn merely to recover an ID the application already knows.

Choices contain only destinations the actor could access when they were created. Membership is
still checked again when a choice is used.

## Quick links

Quick links are optional convenience controls derived from authorized recent destinations. They may
rank by recency or frequency because no chat text is involved. They use the same destination objects
and live authorization check as every other manual control.

Quick links never influence an agent's interpretation of a new request and never grant access.

## Failure behavior

| Condition | Required behavior |
|---|---|
| Unknown destination ID | Return `invalid`; route stays unchanged |
| Missing Engagement | Return `not_found`; reveal no membership information |
| Non-member Engagement | Return the same external shape as `not_found` |
| Malformed structured event | Ignore it, record a safe diagnostic, keep the route stable |
| Ambiguous authorized target | Return structured choices; do not choose automatically |
| Tool or transport failure | Show a neutral error; do not navigate |
| Cancelled run | Ignore later route effects from that run |
| User navigates while agent runs | Preserve the user's newer route |

## Responsive and accessible behavior

- The wide layout exposes the catalog in a stable sidebar.
- Compact and narrow layouts expose the same destinations in a focus-managed drawer.
- The 390 CSS-pixel journey has no page-level horizontal scrolling or unreachable navigation.
- Current location is conveyed semantically as well as visually.
- Drawer open/close restores focus to the invoking control.
- Ambiguous choices are keyboard-operable buttons with unique accessible names.
- Route changes update focus and announce the new page without announcing assistant prose as a
  navigation command.

## Deliberate simplifications

- No embedding index or semantic router is required for MVP navigation.
- No client-side natural-language or keyword resolver exists.
- No generic URL-opening tool exists.
- No model-generated arbitrary path is accepted.
- No cross-tenant or external destination catalog exists.
- Manual search, if retained, is a separate UI feature and not an agent control channel.

## Current implementation versus target

At integrated `master@1fcaac6`, navigation is not yet compliant:

- both harnesses encode navigation and choices into marker text;
- frontend code parses those strings to decide route effects;
- browser-composed context is inserted into the user message;
- catalog and route logic are duplicated across frontend and harness code; and
- the default product route still includes older Personal Assistant navigation.

The divergent `iron-clad-navigation` worktree contains useful UI ideas but also retains lexical
message resolution and marker-based chips. It is evidence to inspect, not a branch to merge. The MVP
must replace the control protocol rather than polish it.

Runtime behavior remains **UNVERIFIED** until the release evidence exercises the structured path.

## Behavioral oracles

| Scenario | Expected evidence |
|---|---|
| Manual portfolio navigation | One direct destination action; no model request |
| Assistant opens an Engagement | Typed `navigate` command, authorized `resolved` result, one matching route event |
| Unauthorized Engagement ID | `not_found`-shaped result, no route change, no leaked title |
| Duplicate names | Structured choices; no automatic navigation |
| Marker-like user text | No route change without a valid navigation tool result and event |
| Marker-like assistant text | No route change without a valid navigation tool result and event |
| Malformed event | Reducer rejects it and keeps the current route |
| User moves during a run | Delayed route event is ignored |
| Narrow viewport | Drawer journey succeeds at 390 CSS px with reviewed screenshot |

Playwright is the primary UI evidence. Contract tests additionally prove schema validation,
authorization, event ordering, and the absence of text-parsing control paths.

## Related authority

- [Authoritative design](../design.md)
- [MVP success criteria](../requirements.md)
- [Agent harness](agent-harness.md)
- [Context](context.md)
- [UI/UX](ui-ux.md)
- [Testing and evals](testing-evals.md)
