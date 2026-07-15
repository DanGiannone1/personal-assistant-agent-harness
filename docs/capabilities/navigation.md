# Navigation Capability

> **Authority:** Canonical navigation detail subordinate to the [authoritative design](../design.md)
>
> **Deployed application revision:** `c544f6ca7d70a80d9aa5708d22c590f8f13c88d6`
>
> **Applies to:** Manual host navigation, assistant destinations, route effects, and navigation evidence
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## In plain language

CSA Workbench has two ways to move around:

- A person clicks an application control. The host view changes immediately, without asking the
  assistant.
- The assistant calls the typed `navigate` tool. The application checks the requested destination
  and emits a structured route event only when it resolves successfully.

The assistant can interpret a request, but its words cannot move the application. A URL, route name,
tool name, marker string, or JSON-looking text in either user's or assistant's prose is inert.

The current implementation has a deliberately small assistant destination catalog. Manual controls
cover more host views than that catalog; they are direct product controls, not natural-language
navigation. Engagement destinations are resolved with the authenticated actor's current membership,
not a user ID or role supplied by the model.

## Implemented contract

### Manual routing

The host starts at `/engagements`. Host navigation items, portfolio cards, tabs, task links, and quick
links call `onNavigate` with application-owned routes. A manual action:

1. changes the visible host route immediately;
2. increments a monotonic navigation version;
3. records the visit; and
4. starts a non-blocking authoritative-state refresh.

No manual route is sent through the model or SSE stream. Engagement detail routes accept only canonical
Engagement and task IDs. The screen then renders only an Engagement present in the actor-filtered
application state; malformed, missing, and inaccessible Engagement routes use the same neutral
not-found presentation.

Manual navigation is broader than assistant navigation. Personal utilities, task detail, Engagement
team settings, and `/assistant` are reachable through product controls but are not assistant catalog
destinations.

### Assistant destination catalog

Both harnesses expose the same `NavigateCommand`: a required `destination_id` from a `Literal` type and
an optional `engagement_id`. The current catalog is:

| Destination ID | Canonical path |
|---|---|
| `engagements` | `/engagements` |
| `workbench` | `/home` |
| `engagement_overview` | `/engagements/{engagement_id}` |
| `engagement_tasks` | `/engagements/{engagement_id}/tasks` |
| `engagement_artifacts` | `/engagements/{engagement_id}/documents` |

`workbench_core.tool_protocol` rejects unknown destination IDs, malformed Engagement IDs, mismatched
scoping, and paths that do not exactly match this catalog. A failed result cannot carry a destination;
only `resolved` or `committed` results may do so. There is no arbitrary-URL or free-form-path tool.

The current service does not resolve natural-language text. When an assistant request needs a specific
Engagement, the model must first obtain an authorized stable ID through an Engagement read tool and then
pass that ID to `navigate`.

### Actor-authorized Engagement resolution

The model-visible command has no actor, role, or session field. The orchestrator authenticates the
caller, verifies that caller owns the agent session, and forwards the bound actor to the internal
runtime. The runtime keeps the session-to-actor binding write-once and closes over that actor when it
builds the tool.

For an Engagement-scoped destination, the resolver validates the ID, loads the current Engagement, and
checks current membership. A missing Engagement and a real Engagement hidden from a non-member both
produce `not_found` with the same `engagement.not_found` code and unavailable wording. A successful
result contains the stable Engagement ID and the canonical destination. The browser also requires that
the Engagement appear in its latest actor-filtered application state before applying the route.

### Structured route event

A successful navigation tool call produces a native `ProductToolResult`, followed by:

```ts
{
  type: "NAVIGATION_RESOLVED";
  runId: string;
  destination: Destination;
  requestedAtNavigationVersion: number;
}
```

The runtime emits this event only from the validated native tool result. The orchestrator validates the
SSE lifecycle and requires the event to match exactly one still-open `resolved` or `committed` tool
result in the same run. The browser repeats that correlation check before its reducer sees the event.

The reducer changes the route only when all of these are true:

- `runId` is the active turn;
- `requestedAtNavigationVersion` is the version captured when that turn was sent;
- Stop has not cancelled the client-side turn;
- the destination ID, Engagement ID, and path match the client catalog; and
- a scoped Engagement is present in the current authorized application state.

Assistant text is rendered only as text and is not searched for navigation markers or paths.

### Supersession, cancellation, and failure

- **Newer manual navigation wins.** Every manual action increments the version, so a delayed route event
  from a turn sent under an older version is ignored.
- **Stop blocks later buffered effects.** Stop marks the active turn cancelled before aborting the
  stream. Subsequent buffered events from that turn are ignored. Stop does not roll back a route effect
  already applied or a product mutation already committed.
- **Resolution failures stay put.** Unknown or malformed destinations return `invalid`; missing or
  inaccessible Engagements return `not_found`; neither result can carry a route.
- **Stream failures stay visible.** Invalid framing, event ordering, run correlation, or tool-result
  correlation becomes a terminal stream error. The invalid event is not applied.
- **A later terminal error does not undo earlier success.** `NAVIGATION_RESOLVED` is applied when it
  arrives, before `RUN_FINISHED`. If a valid route event was already accepted and the turn later ends in
  `RUN_ERROR`, the current implementation reports the error but does not roll the route back.

Only one turn may stream in a session at a time, so two assistant turns do not race each other for the
route.

### Responsive and accessible interaction

At 1200 CSS px and above, manual destinations are exposed in the persistent navigation rail. Below
1200 px, the same controls move into a modal drawer. The drawer moves focus inside when opened, traps
Tab, closes on Escape or backdrop activation, and restores focus to its launcher. Navigation items and
Engagement tabs are semantic buttons and expose the current page with `aria-current`; narrow host
controls use the implemented 44 px minimum target size.

The verified 390 px host journey opens the drawer, checks focus entry and Escape restoration, reaches
the final Engagement card, and finds no page-level horizontal overflow. The separate `/assistant`
layout is not part of that narrow-screen claim.

## Evidence status

### Implemented and verified

The focused structured-control tests prove catalog and path validation, live membership filtering,
neutral non-member results, native result extraction in both harnesses, matching tool schemas, framed
SSE lifecycle validation, and rejection of unbound navigation events:
[`tests/test_structured_control.py`](../../tests/test_structured_control.py).

The frontend contract proves active-run and navigation-version correlation, cancellation handling,
exact path and Engagement-ID validation, cached authorized membership, and rejection of marker-like
destinations: [`frontend/src/lib/navigation.contract.ts`](../../frontend/src/lib/navigation.contract.ts).

The ignored local Deep Agents observation with run ID
`2026-07-15T01-27-46-902Z-2ecc70df` passed all seven cases. `MVP-E3` contains a typed `navigate` call, a
`resolved` native result, one matching `NAVIGATION_RESOLVED`, and one correlated terminal event.
`MVP-E7` placed `NAVIGATION_RESOLVED`, `TOOL_CALL_RESULT`, success-like text, and an Engagement path in
the user prompt; it produced no tool result, no navigation event, and no state change.

The ignored local browser observation with run ID
`2026-07-15T02-57-58-244Z-1e852bb3` passed 34 checks against the real host UI, including the 390 px
drawer interaction and responsive assertions described above. Neither ignored result is portable
evidence in a fresh clone.

### Remaining gaps

- The agent eval and browser evidence were recorded at earlier source revisions, not the final release
  SHA. A later copy-only `MessageList.tsx` change did not alter navigation code, so the browser run
  remains supporting navigation evidence, but a final-SHA rerun is absent.
- The browser journey verifies a structured Engagement mutation and refresh, but it does not drive an
  assistant navigation and assert the resulting visible route. The live agent eval proves the stream,
  while the visible route effect is covered by the frontend contract rather than end-to-end browser
  evidence.
- Cancellation and version supersession are contract-tested at the reducer boundary, not in a live
  browser race. A route accepted before Stop or a later terminal failure is not rolled back.
- `ambiguous` exists in the shared result vocabulary, but the current navigation service does not
  return structured choices and the UI does not render navigation choice controls. The model must ask
  for clarification before calling `navigate` with a stable ID.
- Destination definitions are repeated across the Python resolver/core and TypeScript client. Current
  tests cover their accepted behavior, but the catalog is not generated from one cross-language source.
- Route changes do not explicitly focus or announce the new page, and full keyboard, screen-reader,
  reduced-motion, zoom/reflow, and WCAG 2.2 AA conformance evidence has not been recorded.

## Related authority

- [Authoritative design](../design.md)
- [MVP success criteria](../requirements.md)
- [UI/UX](ui-ux.md)
- [Agent harness](agent-harness.md)
- [Identity and access](identity-access.md)
- [Testing and evals](testing-evals.md)
