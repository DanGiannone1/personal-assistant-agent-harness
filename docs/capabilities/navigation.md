# Navigation boundary

> **Authority:** Focused current-boundary note; [design](../design.md) remains higher authority.

## In plain language

CSA Workbench has two ways to move around:

- A person clicks an application control. The host view changes immediately, without asking the
  assistant.
- The assistant calls the typed `navigate` tool. The application checks the requested destination
  and emits a structured route event only when it resolves successfully.

The assistant can interpret a request, but its words cannot move the application. A URL, route name,
tool name, marker string, or JSON-looking text in either user's or assistant's prose is inert.

The host UI has supported top-level surfaces for Engagements (default landing), the private "My
work" group (Home, Tasks, Calendar, Reminders), Assistant, and Settings. There is no global Library,
Search, or quick-links surface, and My work never scopes to or shares across an Engagement. Manual
controls cover more host views than the assistant catalog below — Engagement team/conventions
settings and `/assistant` are reachable through product controls but are not assistant destinations.

## Implemented contract

### Manual routing

The host starts at `/engagements`. A manual navigation action changes the visible host route
immediately, increments a monotonic navigation version, and starts a non-blocking authoritative-state
refresh. No manual route is sent through the model or SSE stream.

### Assistant destination catalog

`workbench_core.tool_protocol.DESTINATION_IDS` defines exactly eight destinations:

| Destination ID | Canonical path |
|---|---|
| `engagements` | `/engagements` |
| `engagement_overview` | `/engagements/{engagement_id}` |
| `engagement_tasks` | `/engagements/{engagement_id}/tasks` |
| `engagement_artifacts` | `/engagements/{engagement_id}/artifacts` |
| `home` | `/home` |
| `tasks` | `/todo` |
| `calendar` | `/calendar` |
| `reminders` | `/reminders` |

`validate_destination` rejects unknown destination IDs, malformed Engagement IDs, mismatched
Engagement scoping (only the three `engagement_*` destinations may carry an `engagement_id`), and any
path that does not exactly match this catalog. A failed result cannot carry a destination — only
`resolved` or `committed` results may. There is no arbitrary-URL or free-form-path tool. When an
assistant request needs a specific Engagement, the model must first obtain an authorized stable ID
through an Engagement read tool and then pass that ID to `navigate`.

### Actor-authorized Engagement resolution

The model-visible `navigate` command has no actor, role, or session field. For an Engagement-scoped
destination, the resolver validates the ID, loads the current Engagement, and checks current
membership. A missing Engagement and a real Engagement hidden from a non-member both produce
`not_found` with the same code and wording. The browser also requires the Engagement to appear in its
latest actor-filtered application state before applying the route.

### Structured route event

A successful navigation tool call produces a native `ProductToolResult`, followed by
`NAVIGATION_RESOLVED { runId, destination, requestedAtNavigationVersion }`. The reducer changes the
route only when all of these hold: `runId` is the active turn; `requestedAtNavigationVersion` matches
the version captured when that turn was sent; Stop has not cancelled the client-side turn; the
destination ID/Engagement ID/path match the client catalog; and a scoped Engagement is present in the
current authorized application state.

### Supersession, cancellation, and failure

- **Newer manual navigation wins.** Every manual action increments the version, so a delayed route
  event from an older-version turn is ignored.
- **Stop blocks later buffered effects.** It does not roll back a route effect already applied or a
  product mutation already committed.
- **Resolution failures stay put.** Unknown/malformed destinations return `invalid`; missing or
  inaccessible Engagements return `not_found`; neither can carry a route.
- **Stream failures stay visible.** Invalid framing, event ordering, or correlation becomes a
  terminal stream error; the invalid event is not applied.

Only one turn may stream in a session at a time, so two assistant turns never race for the route.

## Evidence status

Focused structured-control tests prove catalog and path validation, live membership filtering,
neutral non-member results, and native result extraction in both harnesses
(`tests/test_structured_control.py`). The frontend contract proves active-run and
navigation-version correlation, cancellation handling, exact path/Engagement-ID validation, and
rejection of marker-like destinations
([`frontend/src/lib/navigation.contract.ts`](../../frontend/src/lib/navigation.contract.ts)). Case
`MVP-E3-navigate-typed` and `MVP-E9-personal-navigate` in
[`tests/evals/mvp-cases.json`](../../tests/evals/mvp-cases.json) exercise a typed Engagement and a
typed personal-work destination respectively; `MVP-E7-marker-prose-is-inert` proves that
navigation-shaped prose alone produces no tool result and no route change.

A local browser journey passed 41/41 checks ([current evidence record](../evidence.md)), including live navigation
between the covered surfaces. `ambiguous` exists in the shared result vocabulary, but the navigation
service does not return structured choices today — the model must ask for clarification before
calling `navigate` with a stable ID.

## Related authority

- [Design](../design.md)
- [UI/UX](ui-ux.md)
- [Agent harness](agent-harness.md)
- [Identity and access](identity-access.md)
- [Testing and evals](testing-evals.md)
