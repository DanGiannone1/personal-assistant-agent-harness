# UI/UX boundary

> **Authority:** Focused current-boundary note; [design](../design.md) remains higher authority.

## In plain language

CSA Workbench opens on **Engagements** — the signed-in actor's portfolio of authorized Engagement
records. Opening one moves into the shared record used by its members; the header shows status and
the current actor's role, and four stable tabs (Overview, Tasks, Artifacts, Team & conventions) hold
the rest. The private "My work" group (Home, Tasks, Calendar, Reminders) sits alongside it in the
same navigation rail, plus Assistant and Settings.

The product remains usable without the assistant. The assistant is a second way to navigate and
change the same records: a dock supports quick work beside the application, and a separate
`/assistant` workbench gives chat and generated session files more room. Both use the same session
and conversation.

The UI treats application state and structured tool results as truth. After a manual or agent
operation it refreshes the authoritative workspace; assistant prose can explain an outcome but never
proves it.

## Information architecture

`/engagements` is the initial view. Each portfolio card shows name, customer, Green/Yellow/Red
status and reason, the actor's role, and counts. Any signed-in user can create an Engagement and
becomes its owner. Yellow and Red status changes require a reason; the reason control receives focus
and a save without one is rejected with an associated `role="alert"`.

The private "My work" pages (`/home`, `/todo`, `/calendar`, `/reminders`) are scoped solely to the
signed-in actor. A non-member or cross-actor route resolves to the same neutral not-found
presentation as a missing record — see [Navigation](navigation.md) and
[Identity and access](identity-access.md).

### Role-gated actions

| Role | UI capabilities |
|---|---|
| Owner | Edit identity/delivery fields; manage tasks, artifacts, conventions, members, and roles |
| Editor | Edit delivery fields; manage tasks, artifacts, and conventions; cannot manage membership or rename |
| Viewer | Read the record and open artifacts; sees a view-only explanation and no mutation controls |

Role gating helps a user understand what they can do; the server remains the authorization boundary
(see [CRUD](crud.md)).

## Assistant surfaces and continuity

The dock and `/assistant` are two presentations of the session owned by the root session provider.
Moving between them preserves the session, messages, streaming state, and application state. The
dock contains chat, uploads, tool progress, and a link to the full workbench; the full workbench
presents the same chat beside an artifact canvas for the session's generated files (marked
AI-generated and unreviewed).

## Structured-result presentation

The stream reducer accepts the full structured status vocabulary (`committed`, `resolved`,
`succeeded`, `noop`, `needs_confirmation`, `ambiguous`, `invalid`, `not_found`, `forbidden`,
`conflict`, `failed`) and presents it as a compact inline trace: a running-tool label while a call is
in flight, a completed label for `committed`/`resolved`/`succeeded`, a neutral **No change** for
`noop`/`needs_confirmation`/`ambiguous`, and **Couldn't complete** for the failure statuses. Tool
completion and turn termination trigger authoritative refreshes; a failed refresh keeps the last good
workspace, marks it possibly stale, and offers Retry.

Navigation is applied only from a validated `NAVIGATION_RESOLVED` event bound to the active run and a
matching structured tool result; cancellation, a later manual navigation, an unknown destination, or
assistant text cannot move the host view (see [Navigation](navigation.md)).

## Responsive behavior

| Layout | Breakpoint | Implemented behavior |
|---|---|---|
| Wide | `>= 1200px` | Persistent 220px-class navigation rail; dock visible beside the host content |
| Compact | `768–1199px` | Navigation becomes a modal drawer opened by a 44px toggle; dock opens as an overlay |
| Narrow | `<= 767px` | Same drawer; portfolio cards, forms, task rows, and stats stack to a single column; controls keep a 44 CSS-pixel minimum target |

The drawer traps focus, closes on Escape or backdrop activation, and restores focus to its launcher.
The standalone `/assistant` workbench uses the same host rail/drawer pattern and, below its own
~1100px threshold, stacks the chat and artifact canvas vertically at narrow widths rather than
keeping a side-by-side split off-screen.

## States and accessibility intent

Implemented host states include initial loading, session failure and retry, empty portfolio/task/
artifact states, inline busy labels during saves/uploads, field validation with `role="alert"` and
associated descriptions, neutral not-found presentation, visible viewer-role guidance, and a
stale-workspace notice with Retry. Accessibility implementation includes semantic buttons for
navigation and records, `aria-current` for active navigation/tabs, visible `:focus-visible` styling,
and keyboard focus containment/restoration for drawer and dock overlays.

The release intent is WCAG 2.2 AA across the supported host range; full keyboard, screen-reader,
contrast, zoom/reflow, and automated accessibility audits have not been recorded as a conformance
result.

## Evidence status

A local browser journey (`scripts/mvp_playwright.mjs`) passed 41/41 checks ([current evidence record](../evidence.md)) at
1440, 1024, and 390 CSS px, covering: distinct personal portfolios and Engagement isolation; owner
creation and sharing; editor updates and viewer affordance gating; outsider-neutral 404s; visible,
state-preserving validation failures; a typed agent Engagement update followed by authoritative UI
refresh; stable wide layout before/during/after the agent turn; the narrow navigation drawer's focus
entry, Escape restoration, and hidden launcher; the standalone `/assistant` workbench stacking at
390px with no horizontal overflow; a full page inventory across Engagements/My work/Assistant/
Settings; and personal Task/Calendar/Reminder create flows plus cross-actor isolation. **UNVERIFIED:**
a formal WCAG 2.2 AA conformance audit and broader accessibility tooling coverage.

## Related authority

- [Design](../design.md)
- [Navigation](navigation.md)
- [CRUD](crud.md)
- [Testing and evals](testing-evals.md)
