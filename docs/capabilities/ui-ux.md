# UI/UX Capability

> **Authority:** Canonical UI/UX detail subordinate to the [authoritative design](../design.md)
>
> **Deployed application revision:** `807a0d6766036aa88dce8dcd9f16a2aabeb187b3`
>
> **Applies to:** Information architecture, interaction, responsive behavior, accessibility intent, and presentation
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## In plain language

CSA Workbench opens on **Engagements**. This is the signed-in CSA's personal portfolio: it contains
only the Engagements they are allowed to see. Opening one moves into the shared record used by its
members. The header makes the Engagement's status and the current user's role visible; its tabs hold
the delivery overview, tasks, artifacts, team, and conventions.

The product remains usable without the assistant. The assistant is a second way to navigate and
change the same records: a dock supports quick work beside the application, and a separate workbench
gives chat and generated artifacts more room. Both assistant surfaces use the same session and
conversation.

The UI treats application state and structured tool results as truth. After a manual or agent
operation it refreshes the authoritative workspace. Assistant prose can explain an outcome, but it
does not select a route or prove that a record changed.

The Engagement journey is implemented for wide, compact, and 390 CSS-pixel host layouts. WCAG 2.2
AA is the intent, not a conformance claim. Verified behavior and remaining gaps are separated below.

## Information architecture

### Personal portfolio

`/engagements` is the initial view and **Engagements** is the first navigation item. The portfolio
shows each authorized Engagement's name, customer, Green/Yellow/Red status, status reason when
applicable, the actor's role, open-task count, artifact count, and optional target date. Any signed-in
user can choose **New engagement**; successful creation opens the authoritative new record and makes
that user its owner. An empty portfolio explains the purpose of an Engagement and offers creation.

The navigation also retains secondary personal utilities under **My work**, plus Assistant and
Settings. They do not replace the Engagement portfolio as the release entry point.

### Shared Engagement

An Engagement has four stable sections:

- **Overview** — status, delivery fields, counts, and recent activity;
- **Tasks** — shared tasks and task detail;
- **Artifacts** — durable Engagement files; and
- **Team & conventions** — membership and working agreements.

The persistent header shows name, customer when present, status, role, target date when present, and
the reason for Yellow or Red. A missing, malformed, or inaccessible Engagement uses the same neutral
not-found wording.

Yellow and Red require a reason. The reason control receives focus after either status is selected
and a save without a reason is rejected with an associated alert. Choosing Green clears the old
reason. Successful manual changes refresh the workspace before the committed record is rendered.

### Role-gated actions

| Role | UI capabilities |
|---|---|
| Owner | Edit identity and delivery fields; manage tasks, artifacts, conventions, members, and roles |
| Editor | Edit delivery fields; manage tasks, artifacts, and conventions; cannot manage membership or rename the Engagement |
| Viewer | Read the record and open artifacts; sees a view-only explanation and no mutation controls |

Role gating helps users understand what they can do; the server remains the authorization boundary.
An outsider does not receive enough UI or API detail to distinguish a private Engagement from a
missing one.

## Assistant surfaces and continuity

The dock and `/assistant` are two presentations of the session owned by the root `SessionProvider`.
Moving between them preserves the session, messages, streaming state, application state, and the
session's generated files. A running turn continues when the wide dock is collapsed, and the launcher
continues to show that the assistant is working.

The dock contains chat, uploads, tool progress, and a link to open generated artifacts in the full
workbench. The full workbench presents the same chat beside an artifact canvas. The canvas renders
session-generated files, marks them as AI-generated and unreviewed, and allows text, Markdown, and
CSV edits to be saved back to the ephemeral session workspace.

The assistant empty state suggests only the active Engagement capabilities: review, navigate,
create, and update status. It does not advertise task, calendar, document, or Library tools that are
inactive in the release inventory.

Continuity does not currently include component-local state. An unsent composer draft, the selected
artifact, and an in-progress artifact edit are not guaranteed to survive a route change between the
dock and full workbench. The canvas also has no implemented **Save to Engagement** action; durable
Engagement artifacts are uploaded and managed from the Engagement's Artifacts section.

Starting a new session deletes the current agent session and reloads durable Engagement state into a
new one. It does not delete Engagements or their durable artifacts. The current confirmation copy
still says that the workspace resets to seed data; that wording is inaccurate for the durable
Engagement record.

## Structured-result presentation

The stream reducer accepts the full structured status vocabulary: `committed`, `resolved`,
`succeeded`, `noop`, `needs_confirmation`, `ambiguous`, `invalid`, `not_found`, `forbidden`,
`conflict`, and `failed`.

The current UI presents those results as a compact inline trace:

| Structured result | Current presentation |
|---|---|
| Running tool | Operation label such as **Reviewing engagements** or **Updating engagement** |
| `committed`, `resolved`, `succeeded` | Completed label, with tool-specific wording where defined |
| `noop`, `needs_confirmation`, `ambiguous` | Neutral **No change** |
| `invalid`, `not_found`, `forbidden`, `conflict`, `failed` | **Couldn't complete** |
| Missing or unknown result | Neutral **Outcome unavailable** |

Multi-step traces are expandable and show a final tool-call count and duration. Tool completion and
turn termination trigger authoritative refreshes. A failed refresh keeps the last good workspace,
marks it as possibly stale, and offers Retry.

Navigation is applied only from a validated `NAVIGATION_RESOLVED` event bound to the active run and a
matching structured tool result. Cancellation, a later manual navigation, an unknown destination, or
assistant text cannot move the host view. The current trace does not yet render distinct, actionable
confirmation or ambiguity choices; both appear as **No change**.

## Responsive behavior

| Layout | Implemented host behavior | Assistant behavior |
|---|---|---|
| Wide, `>= 1200px` | 220 px navigation rail and fluid Engagement content | Dock is visible beside the host at 360–420 px |
| Compact, `768–1199px` | Navigation becomes a modal drawer | Dock starts collapsed and opens as a modal overlay up to 440 px / 92 vw |
| Narrow, `390–767px` | Same drawer; portfolio cards, forms, task rows, counts, and metadata stack | Same overlay; launcher is hidden while navigation is open |

The host shell clips ambient decoration, gives the work area its own vertical scroll, reserves bottom
space for the assistant launcher, and stacks Engagement content below 768 px. Narrow host controls
use a 44 CSS-pixel minimum height. Navigation and assistant overlays trap focus, close on Escape or
backdrop activation, and restore focus to their launchers.

The standalone `/assistant` workbench is different: below 1100 px it hides the navigation rail but
keeps a split chat/artifact layout with a chat minimum width of 320 px. A single-surface narrow
workbench is neither implemented nor verified, so 390 px support must not be claimed for that route.

## States and accessibility intent

The implemented host states are:

- initial loading, session failure, and retry;
- empty portfolio, task, artifact, and activity states;
- inline busy labels and disabled conflicting controls during saves and uploads;
- field validation with `role="alert"`, `aria-invalid`, associated descriptions, and focus on the
  first invalid Engagement or task field;
- neutral inaccessible/not-found presentation;
- visible viewer role guidance;
- armed delete with explicit Confirm and Cancel; and
- stale-workspace notice with Retry after authoritative refresh failure.

Accessibility implementation includes semantic buttons for navigation and records, `aria-current`
for active navigation and tabs, visible `:focus-visible` treatment, named drawers/dialogs, keyboard
focus containment and restoration for the host overlays, status text in addition to color, and 44 px
narrow host controls.

The release intent is WCAG 2.2 AA across the supported host range. Full keyboard, screen-reader,
contrast, zoom/reflow, reduced-motion, and automated accessibility audits have not been recorded.
The new-session confirmation also lacks dialog semantics and focus management, and no
`prefers-reduced-motion` override is implemented. These are evidence or implementation gaps, not
verified behavior.

## Evidence status

### Implemented and verified

The latest recorded local synthetic browser observation has run ID
`2026-07-15T02-57-58-244Z-1e852bb3`. Its ignored local result reports 34 passing checks, no failures,
and no page errors at source revision
`9142b2a1fe70e86af00b5071b1a4e4215327feb1`. One frontend file changed afterward:
`MessageList.tsx` replaced unsupported empty-state suggestions with supported Engagement list, open,
create, and status-update prompts. Contract tests, lint, and production build passed for that
copy-only change, and the final deployed JavaScript contains the corrected strings.

That run proves, against the real frontend and authoritative `/app/state`:

- distinct personal portfolios for three deterministic users;
- owner creation and sharing, editor update, viewer affordance gating, and outsider-neutral 404s;
- visible and state-preserving validation failures;
- a typed agent Engagement update followed by authoritative UI refresh;
- stable wide layout before, during, and after the agent turn;
- no host horizontal overflow at 1440, 1024, and 390 CSS px;
- compact viewer presentation; and
- the 390 px navigation drawer's focus entry, Escape restoration, unobstructed sign-out, hidden
  assistant launcher, and reachable final portfolio card.

The run also wrote captures in the same evidence directory: wide portfolio, shared owner record,
agent-updated record, compact viewer, narrow drawer, and narrow portfolio. The result record does not
identify a separate visual-review sign-off.

### Remaining evidence gaps

- The browser run is not stamped with the final application SHA. It remains supporting evidence for
  the unchanged host workflows and responsive layout, but it does not prove the corrected suggestion
  copy interactively; the recorded captures may show the prior copy.
- The responsive run does not exercise `/assistant`; its narrow split layout remains an
  implementation and evidence gap.
- Dock-to-workbench continuity, collapse during a turn, and component-local draft behavior are not
  asserted by the MVP Playwright runner.
- Distinct interactive UI for `needs_confirmation` and `ambiguous` results is not implemented or
  verified.
- Engagement artifact upload/delete, full viewer tab coverage, and artifact access are not covered
  by the recorded browser journey.
- Accessibility evidence is limited to the focused validation and 390 px drawer assertions listed
  above; WCAG 2.2 AA conformance is unverified.

The executable browser oracle is [`scripts/mvp_playwright.mjs`](../../scripts/mvp_playwright.mjs).
It requires a clean local demo worktree, resets deterministic fixtures, reconciles UI behavior with
authoritative state and structured SSE events, and writes immutable run-scoped evidence.
