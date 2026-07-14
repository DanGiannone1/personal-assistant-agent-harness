# UI/UX Capability

> **Authority:** Canonical capability detail subordinate to [CSA Workbench — Authoritative Product and System Design](../design.md)  
> **State:** Target design, reconciled with integrated `master@1fcaac6`  
> **Applies to:** Information architecture, interaction, responsive behavior, accessibility, and visual presentation  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#15](https://github.com/DanGiannone1/personal-assistant-agent-harness/issues/15)

## The short version

CSA Workbench is the place a solution architect runs customer engagements. The Engagement portfolio is the
default landing page; each Engagement has one shared home for status, tasks, people, conventions,
activity, and durable artifacts. The assistant is available in a dock for quick work and in a full
workbench for deeper conversation and document work, but the workspace remains complete without it.

The interface must make truth easy to see. It renders records after re-reading authoritative state,
uses plain outcome language, and never treats assistant prose as proof that an action succeeded. On
wide screens the workspace, navigation, and assistant can coexist. On responsive web layouts down to
390 CSS px, CSA Workbench presents one usable surface at a time without losing conversation or workbench state.

This document owns how those capabilities feel and behave. Product boundaries and system ownership
remain in [the high-level design](../design.md). Context, navigation, mutation, document, session,
harness, and identity contracts are owned by their corresponding sibling capability documents.

## Users and priority journeys

CSA Workbench supports three Engagement roles. Owners run the engagement and manage access, editors contribute
to delivery, and viewers verify the work without mutation affordances. Any authenticated actor may
create an Engagement and becomes its first owner.

### Triage the portfolio

The user signs in and lands on **Engagements**. They can scan Green/Yellow/Red status, the reason for
Yellow or Red, overdue work, and recent activity; then open an Engagement without reconstructing its
context. Asking the assistant which Engagements need attention produces the same permission-filtered
facts with grounded destination links.

### Run an Engagement

An owner or editor opens an Engagement, reviews its current status and next work, updates tasks or
conventions, and changes status. Yellow and Red cannot save without a reason. Setting Green clears the
old blocker reason. A viewer sees the same current record but no create, edit, upload, delete, member,
or confirmation controls.

### Prepare and share a deliverable

The user opens the full workbench, works with private uploads and generated drafts, reviews or edits
the result, and explicitly chooses **Save to Engagement** when it should become a shared durable
artifact. Private chat material never becomes Engagement content merely because the active context is
an Engagement. Artifact lifecycle and retrieval details are owned by
[Documents and retrieval](documents-retrieval.md).

### Navigate and act from anywhere

Known links and records open immediately. A natural-language destination is resolved only against the
actor's authorized catalog. An action may use a clearly active Engagement, but its chosen scope is
shown. Failed, ambiguous, denied, cancelled, or pending-confirmation operations leave the visible
route unchanged. See [Navigation](navigation.md) and [CRUD](crud.md) for the underlying contracts.

### Verify the assistant

The user can expand a compact tool trace to see what ran and how it ended. They can also open
**What I used** for the stored, safe context snapshot applied to the last turn. Current application
state, tool outcomes, and the turn receipt can therefore be reconciled without exposing hidden
chain-of-thought.

## Information architecture and surface contract

### Application frame

The stable navigation order is:

1. Engagements
2. Personal tasks and documents needed for the private workbench
3. Assistant
4. Settings

Secondary personal utilities may remain reachable, but they must not outrank Engagements or make the
product read as a personal-productivity demo. The frame shows the signed-in actor, current location,
and active Engagement when one exists. Breadcrumbs support orientation; they do not replace a clear
page title and Engagement header.

### Engagement portfolio

Each portfolio row or card shows only decision-useful information:

- Engagement name and customer;
- title-case **Green**, **Yellow**, or **Red**;
- the reason for Yellow or Red, without hiding it behind hover;
- the actor's role;
- open or overdue task signal;
- artifact count; and
- optional target date when present.

The primary action is **New engagement**. Creation is available to every authenticated actor, and the
resulting detail view identifies that actor as owner. The empty state explains what an Engagement is
and offers both the manual action and an assistant example.

### Engagement detail

The header persists across the Engagement's tabs and contains its name, customer, status, status
reason when applicable, optional target date, and the actor's role. The v1 tab set is:

- **Overview** — current status and reason, next or overdue work, and recent activity;
- **Tasks** — the Engagement's task list and detail editor;
- **Artifacts** — durable shared files and their provenance;
- **Team & conventions** — membership for owners and working agreements for owners/editors.

Overview should not repeat every count as a large dashboard card. Status, why, next work, and recent
change have higher information value. A missing or inaccessible Engagement uses the same neutral
not-found presentation so the UI does not disclose membership.

Status editing is one atomic interaction. Choosing Yellow or Red reveals and focuses a required
reason field; the status is held locally until the reason is valid. Choosing Green commits Green and
clears the prior blocker reason. Manual saves remain in place unless the user intentionally follows a
returned record link.

### Embedded assistant dock

The dock supports quick navigation, short grounded questions, low-risk CRUD, and confirmations. It
does not replace the Engagement page or become a second navigation system. Its header shows Ready,
Working, or a recoverable error; collapse and expand controls have accessible names and preserve the
entire conversation state.

Tool progress appears inline with the relevant assistant turn. Multi-step traces may collapse after
completion, while errors, ambiguity, and pending confirmations remain visible. Unknown outcomes stay
neutral. Raw model arguments, credentials, internal policy, and hidden reasoning never appear.

### Full assistant workbench

The full workbench gives conversation and artifacts enough room for sustained work. It retains the
same conversation as the dock and adds an artifact canvas with selection, provenance, edit, save,
and **Save to Engagement**. An AI-generated draft is visibly marked unreviewed until the user reviews
it; that label does not imply the artifact is already shared or durable.

A successful request to open a host destination, including an Engagement or task, takes the user to
that grounded host view. Drafting and artifact operations keep the user in the workbench. This avoids
both invisible navigation behind the workbench and the opposite failure of ejecting the user while a
deliverable is being created.

### Tool trace and context inspector

The trace uses ordinary labels such as **Creating task**, **Task created**, **No change**,
**Needs confirmation**, or **Couldn't complete**. A completed multi-step group summarizes the number
of steps and duration, with details on demand. Bound navigation alternatives are direct links and do
not send another assistant message.

**What I used** renders the persisted `CONTEXT_APPLIED` inspector projection for the last turn. It
shows effective scope and reason, applied persona fields, Engagement conventions, safe live summaries,
freshness, and omitted or degraded sources. It includes the context ID and timestamp needed to match
the turn receipt. It does not reconstruct context later from mutable browser state. The projection and
redaction contract is owned by [Context](context.md).

## Dock and workbench continuity

Docked and full-screen assistant modes are two views of one actor-owned conversation, not separate
sessions. Transitioning between them preserves:

- messages and streaming progress;
- unsent composer text and selected attachment;
- pending confirmation or ambiguity choices;
- selected artifact, edit buffer, and save state;
- trace and **What I used** disclosure state where practical; and
- scroll position, unless a new message intentionally follows the latest output.

Collapsing the dock never cancels a turn. A compact launcher continues to communicate Working or
attention-needed state. Starting a new conversation requires confirmation when the current one has
content, clears conversation-private state according to [Session and state](session-state.md), and
never resets Engagement records or durable artifacts.

## Responsive web contract

CSA Workbench is responsive web down to 390 CSS px. Native mobile, offline behavior, and mobile-platform
navigation conventions are not part of v1.

| Regime | Host workspace | Assistant | Full workbench |
|---|---|---|---|
| Wide, `>= 1200px` | Stable 220 px navigation plus fluid content | 360–420 px dock; open when space permits | Navigation, 420–520 px chat spine, and fluid artifact canvas |
| Compact, `768–1199px` | Collapsible navigation; content retains useful working width | 400–480 px overlay sheet | Navigation hidden; split chat/artifact only when both meet minimum width |
| Narrow, `390–767px` | One content surface; navigation drawer | Full-height sheet | One surface at a time with **Chat** / **Artifact** switch and artifact-count badge |

Across every supported width:

- there is no page-level horizontal scroll;
- critical status, reason, errors, and confirmation details are not truncated;
- portfolio rows, task tables, artifact lists, and activity entries become stacked records when a
  table no longer fits;
- controls remain reachable at 200% zoom and with a software keyboard open;
- the composer remains above the keyboard and respects safe-area insets;
- sheets and drawers trap focus, close with Escape and backdrop action, and restore focus;
- the selected route, conversation, and artifact survive layout changes; and
- touch-oriented controls are at least 44 CSS px in their compact dimension on narrow layouts.

Responsive behavior should be expressed through the existing component and token structure. This
capability does not authorize a broad design-system rewrite.

## Interaction and outcome states

The UI presents the structured outcome returned by the application contract; it does not infer
success from tool names or prose. Status schemas and navigation effects are owned by
[CRUD](crud.md) and [Navigation](navigation.md).

| State or outcome | Required presentation | Route behavior |
|---|---|---|
| Initial loading | Stable shell and structural skeleton; announce loading | No route effect |
| Refreshing | Keep last good content, show a subtle scoped refresh indicator | Preserve route |
| Running | Inline operation label; disable only conflicting controls; Stop remains available | Wait for structured result |
| `committed` | Re-read authoritative state, announce completion, briefly identify the affected record | Follow only its canonical destination when specified |
| `noop` | Neutral “Already up to date” or “No change” | Stay put |
| `needs_confirmation` | Bound preview with explicit Confirm and Cancel; move focus into the confirmation | Stay put until confirmed commit |
| `ambiguous` | Show authorized bound choices and the scope distinction that matters | Stay put until direct choice |
| `invalid` | Inline field error and summary; focus the first invalid control | Stay put |
| `not_found` | Neutral explanation without inaccessible names; offer grounded next actions | Stay put |
| `forbidden` | Explain the actor's role limitation without implying success | Stay put |
| `conflict` | Explain that newer state won, refresh, and preserve safe user input | Stay put |
| `failed` or unknown commit state | Loud error, mark freshness unknown until refetch, and offer Retry | Never infer a route effect |
| Cancelled | Mark the turn stopped; invalidate buffered effects; reconcile state | Stay put |

Confirmation calls the backend directly with its actor-bound confirmation ID. A button that sends
“yes” through a second model turn is not approval. Error recovery must not silently discard a valid
conversation, stale state, edit buffer, or uploaded file.

## Accessibility and visual-quality bar

The target is WCAG 2.2 AA for the supported responsive web range.

- All actions, rows, tabs, drawers, dialogs, disclosures, and artifact controls work by keyboard and
  expose an accessible name, state, and focus order.
- Focus is clearly visible on both host and assistant surfaces. Opening or closing a modal, sheet, or
  confirmation moves and restores focus predictably.
- Status, role, progress, error, and selection never rely on color alone.
- Field errors are associated with their controls and announced. Loading, streaming, save completion,
  route changes, and failures use appropriately scoped live regions without repeatedly reading the
  full conversation.
- Text and meaningful UI components meet AA contrast. Muted text remains readable at its actual small
  sizes; disabled appearance remains distinguishable from unavailable content.
- Layout reflows at 200% zoom and remains operable at 400% text zoom where WCAG requires. Tables expose
  headers in wide mode and meaningful labels in their stacked narrow representation.
- `prefers-reduced-motion` disables ambient blobs, pulsing, smooth scrolling, route flashes, and
  decorative entrance animation without removing state feedback.
- Pointer targets meet WCAG minimums everywhere and use the 44 CSS px narrow-web target above.

The visual language is a calm professional workspace: light neutral canvas, restrained blue primary
actions, a purple assistant accent, and semantic status colors reinforced by text. Use sentence case,
ordinary language, stable spacing, and comfortable reading width. Avoid glass effects, uppercase
tracking, gradients, or animation when they compete with Engagement facts. Loading skeletons should
match final geometry, and no supported state may clip headings, tool outcomes, dialogs, the composer,
or primary actions.

## Trusted UI boundaries

The browser owns presentation and user intent; it does not own identity, authorization, trusted
context, target resolution, confirmation policy, or commit truth.

- Role-based affordances improve comprehension, but the backend remains the authority. Viewers have
  no mutation controls and every operation still reauthorizes.
- Routes from browser input, tool arguments, or assistant prose are untrusted. The client follows only
  a successful structured route effect or a direct catalog-backed UI destination.
- Record changes render after authoritative refetch. Optimistic input state may support a form, but it
  is never displayed as a committed record.
- A failed refetch makes freshness visibly unknown; keeping the last good view must not imply it is
  current.
- Tool trace and **What I used** consume safe event projections. They do not expose credentials,
  hidden policy, inaccessible resource names, raw membership data, or chain-of-thought.
- **Save to Engagement** is an explicit owner/editor action. Active context never silently promotes a
  private upload or draft.
- Authentication and actor/session binding are owned by [Identity and access](identity-access.md);
  stream reduction and cancellation are owned by [Agent harness](agent-harness.md).

## Deliberate simplifications and non-goals

- No stage pipeline, milestone, risk, action, Engagement calendar, standing approval, free-form
  memory, schedule, workflow, analytics, notification, comment, or presence UI in v1.
- No native mobile or offline application; 390 CSS px is responsive web support.
- No configurable dashboard, kanban, dependency graph, or general-purpose file manager.
- No harness selector, SDK terminology, raw event console, prompt viewer, or hidden reasoning surface.
- No automatic promotion of private files into an Engagement.
- No AI-only workflow: every v1 product action has a direct manual path.
- No broad redesign of shared components or tokens. Extend the current system only as needed to meet
  this contract.
- IDA may use the finished experience as reference material, but IDA concepts do not add product
  surfaces or requirements.

## Current checkout versus target

The integrated checkout contains useful foundations, but static inspection shows the following gaps.
Runtime behavior remains unverified until exercised through the evidence below.

| Current evidence at `master@1fcaac6` | Target consequence |
|---|---|
| `frontend/src/app/layout.tsx:24-31` and `frontend/src/components/workbench/WorkbenchApp.tsx:118-124` brand the product “Personal Assistant.” | Present CSA Workbench as an Engagement workspace; do not lead with personal-productivity demo language. |
| `master@1fcaac6:docs/spec.md:28-41` defines personal Home as the primary surface, while `master@1fcaac6:docs/manifesto.md:35-47` makes Engagement the unit of work. | Engagements is the default route and first navigation item. |
| `frontend/src/components/workbench/EngagementScreens.tsx:26-32` and `frontend/src/lib/types.ts:158-160` expose lowercase status text. | Render title-case Green/Yellow/Red everywhere; internal serialization may remain separately mapped. |
| `frontend/src/components/HostApp.tsx:17-31` switches only the assistant at 1100 px, while `frontend/src/app/globals.css:424-444` retains a fixed 220 px host rail and has no responsive media contract. | Implement the three responsive regimes and stacked narrow records down to 390 CSS px. |
| `frontend/src/components/AssistantWorkspace.tsx:63-79` keeps a 320 px minimum chat column beside the artifact canvas. | Use Chat/Artifact single-surface switching when both columns cannot remain usable. |
| `frontend/src/components/workbench/EngagementScreens.tsx:126-144`, `:398-420`, and `:624-639` pack portfolio, task, and artifact data into fixed rows. | Preserve hierarchy through responsive cards/rows without hiding status why or actions. |
| `frontend/src/components/workbench/EngagementScreens.tsx:607-618` exposes artifact upload to viewers. | Viewers are strictly read-only; upload and all other mutation affordances are owner/editor only. |
| `frontend/src/components/ArtifactCanvas.tsx:15-20` reads generated session files separately from Engagement artifacts at `EngagementScreens.tsx:560-643`. | Add explicit Save to Engagement promotion with clear private/shared durability labels. |
| `frontend/src/components/AssistantPanel.tsx:157-166` says New Session resets the workspace to seed data. | New conversation never resets Engagement records or durable artifacts; copy names exactly what private state is cleared. |
| `frontend/src/hooks/useAgentSession.ts:484-506` builds trusted-looking prompt context in the browser, and `AssistantPanel.tsx:129-143` renders the fetched bundle. | Render What I used from the stored `CONTEXT_APPLIED` event only. |
| `frontend/src/lib/types.ts:1-16` reduces tool outcomes to `ok`, `noop`, or `error`; `frontend/src/hooks/useAgentSession.ts:9-24` infers navigation from a hardcoded tool list. | Present the full structured outcome vocabulary and follow explicit route effects. |
| `frontend/src/hooks/useAgentSession.ts:358-373` silently retains old app state when refresh fails. | Show degraded freshness and Retry before making any claim about current state. |
| `frontend/src/components/MessageBubble.tsx:46-61` exposes an open-by-default “Thinking” block. | Remove hidden chain-of-thought; show only safe operation summaries and tool outcomes. |
| `frontend/src/components/AssistantPanel.tsx:157-169` lacks dialog semantics/focus behavior, and `EngagementScreens.tsx:398-416` uses pointer-only task rows. | Meet the dialog, keyboard, focus, and announcement requirements above. |
| `review/deep-test/findings.md:59-62` leaves responsive/narrow behavior untested; existing narrow screenshots predate the Engagement UI. | Treat current responsive and Engagement visual quality as unverified until new evidence exists. |

## Behavioral oracles and evidence

A green build is supporting evidence, not the oracle. The primary proof is Playwright driving the real
frontend and reconciling the visible result with authoritative application state and the persisted turn
receipt. Deterministic synthetic identities and seed data make each journey repeatable.

| Starting condition and action | Expected behavior | Required evidence |
|---|---|---|
| Authenticated actor opens CSA Workbench at 1440×900, 1024×768, 768×1024, and 390×844 | Engagement portfolio is the default; no page-level horizontal scroll or clipped critical content | Screenshots, accessibility tree, viewport assertions |
| User opens, collapses, expands, and enters/exits the workbench during a turn | One conversation persists, including pending state, composer draft, selected artifact, and usable focus | UI assertions plus conversation/session ID |
| Viewer opens every Engagement tab | No create, edit, upload, delete, membership, convention, or confirmation affordance is present | Role-specific DOM assertions and denied API probe |
| Any authenticated actor creates an Engagement | Commit creates exactly one Engagement, actor is owner, detail opens from the authoritative result | UI, Cosmos/application state, activity receipt |
| Editor selects Yellow or Red without a reason, then supplies one | First attempt cannot commit; second commits status and reason atomically and survives reload | Field assertions, state, activity and outcome receipt |
| Editor changes Yellow/Red to Green | Green commits and the blocker reason is absent after reload and to another member | Two-user UI/state reconciliation |
| Agent navigates successfully, returns not found, and is cancelled after tool start | Only successful structured route effect moves the UI; other cases remain in place | Route assertions and ordered turn events |
| Manual and agent paths update the same task | Both enforce identical validation/roles and render only after authoritative refetch | UI, state versions, REST/tool outcomes |
| Owner/editor reviews a generated draft and chooses Save to Engagement | One durable shared artifact is created with attribution; private source remains private | Two-user UI, Blob/Cosmos metadata, activity receipt |
| Viewer attempts artifact upload through a forged request | No artifact or activity is created and the UI reveals no inaccessible detail | HTTP/tool outcome plus unchanged state |
| Confirmation is required for delete or membership change | Cancel changes nothing; direct Confirm commits once; replay cannot duplicate the action | Focus assertions, state, idempotency/confirmation receipt |
| App-state refetch fails after an uncertain operation, then recovers | UI marks freshness unknown, does not claim success, and Retry reconciles the real state | Fault-injected Playwright trace and final state |
| User expands What I used | Displayed context ID, scope, applied items, omissions, and freshness match `CONTEXT_APPLIED` exactly | DOM-to-turn-receipt comparison |
| Missing or error tool outcome is rendered | No green success treatment or successful narration appears | Event fixture and screenshot assertion |
| Keyboard, 200% zoom, reduced motion, and screen reader checks run across core journeys | Focus order, dialogs, reflow, announcements, names, contrast, and non-color status satisfy WCAG 2.2 AA | Automated accessibility scan plus recorded manual checks |

Production wording and model timing are intentionally not exact-match oracles. The stable checks are
scope, permission, outcome, route effect, state version, artifact durability, and visible recovery.
