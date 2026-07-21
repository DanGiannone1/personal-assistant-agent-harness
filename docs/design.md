# CSA Workbench MVP design

> **Authority:** High-level product and system design. [Requirements](requirements.md) owns release
> intent; [governance](governance/README.md) owns lifecycle rules. Detail is authoritative only in
> the named [capability](capabilities/) document.

## Executive summary

CSA Workbench is an engagement workspace for Cloud Solution Architects. It gives each CSA a private
"My work" space and gives an authorized team one shared record for each customer Engagement. The
product is useful without AI: people can create, open, edit, and share Engagements directly in the
web application.

An embedded assistant is an additional control surface over the same records. It reads and changes
them through typed tools, and the UI trusts structured results plus authoritative state — not
assistant prose. This is the defining architecture rule:

> **A claim never outruns reality.**

## What problem it solves

Solution architects commonly reconstruct an engagement from status spreadsheets, notes, chat
history, and personal memory, alongside their own private to-do list, calendar, and reminders spread
across other tools. CSA Workbench makes the **Engagement** the durable unit of shared collaboration
and gives each actor a durable, private "My work" space for the rest. The assistant helps operate
both; it does not become a second source of truth.

## Product boundary

The supported user surfaces are:

- **Engagements** — create, open, and work with authorized Engagement records; this remains the
  default landing surface. An Engagement has four stable sections: Overview, Tasks, Artifacts, and
  Team & conventions.
- **My work** — private, actor-owned Home, Tasks (with subtasks), Calendar, and Reminders pages,
  scoped solely to the authenticated actor and never shared or Engagement-scoped.
- **Assistant** — an assistant dock and a dedicated Assistant route using the same product state.
- **Settings** — user settings, including the persona fields used to personalize assistant tone.

There is no supported generic workbench, global Library/Search, or quick-links surface. Enterprise
search and generalized retrieval are future non-goals, not MVP capabilities.

Engagements are durable shared application records. The application stores durable artifact
metadata with an Engagement and stores artifact bytes through its durable artifact backend (local
isolated directory in local development, Blob when configured for an Entra release). Personal Tasks,
Calendar events, and Reminders are durable per-actor records held on a single `personal-{uid}`
Cosmos aggregate keyed solely from authenticated identity, never a caller-supplied owner.
Assistant-session files are separate, ephemeral workspace content; uploads to a session are Markdown
(`.md`) only.

## Design principles

1. **The work lives here.** Cosmos holds durable Engagement and personal-workspace state; Blob holds
   durable Engagement artifact bytes; chat is a control surface, not a system of record.
2. **Claims follow evidence.** A successful-looking sentence cannot substitute for a committed result
   and authoritative readback.
3. **The product works without AI.** Every Engagement and personal-work operation has a complete
   manual path.
4. **One rule for every caller.** `workbench_core.EngagementService` and
   `workbench_core.PersonalWorkspaceService` back both the manual API and the assistant tools for
   their respective records, so authorization, validation, and outcomes cannot diverge between them.
5. **Structured control only.** Routes, identifiers, commands, and results are typed and validated.
   User text and assistant text are never parsed as an application-control protocol.
6. **Identity is bound outside the model.** The model cannot choose its actor, session, or role; the
   actor ID is never a model-visible tool argument.
7. **Durability is explicit.** Engagement records, their artifacts, and personal-workspace records
   survive compute replacement; conversation workspaces do not.
8. **Frameworks adapt to the product.** Harness code does not own product rules or durable records.
9. **Failure remains visible.** Invalid, ambiguous, denied, missing, and failed outcomes do not
   masquerade as success.
10. **Simplify ruthlessly.** Keep the smallest legitimate boundary that proves the product and defer
    hardening that does not.

## Users, roles, and authorization

There are two application scopes:

| Scope | Owner | Visibility |
|---|---|---|
| Personal work (Tasks, Calendar, Reminders) | Signed-in actor | That actor only |
| Engagement | Engagement members | Current members, according to role |

Any signed-in user may create an Engagement and becomes its first owner. Roles are cumulative:

| Engagement role | Read | Edit delivery fields, tasks, conventions | Manage artifacts | Manage members |
|---|---:|---:|---:|---:|
| Owner | Yes | Yes | Yes | Yes |
| Editor | Yes | Yes | Yes | No |
| Viewer | Yes | No | No | No |

Non-members receive the same not-found behavior as an unknown Engagement. The final owner cannot be
removed or demoted. The server rechecks current membership for every operation; a browser route,
model argument, or stale context snapshot cannot grant access. Personal records use no role matrix at
all: only the authenticated actor may ever read or change that actor's own aggregate, and a
cross-actor request returns the same neutral 404 as a missing record.

Each running environment selects exactly one identity mode:

- `demo` uses deterministic, secret-backed synthetic users (`dan`, `ava`, `sam`) for local and
  automated evidence;
- `entra` accepts validated tokens from one configured tenant for a shared deployment.

The modes are not selectable per request and use separately configured application data stores. A
demo actor's stable ID is `demo:<uid>`; an Entra actor's is validated `<tid>:<oid>`, exposed as
`u-<oid>`.

## System shape

```text
Browser -> Next.js frontend -> FastAPI API -> session runtime -> configured model service
                              |                 |
                              +-- Engagement + personal-workspace state (Cosmos)
                              +-- durable Engagement artifact bytes (local dir / Blob)
```

The frontend applies assistant control effects only from validated structured events and refreshes
product state after committed operations. `workbench_core` is a dependency-light package imported by
both the API and the session runtime; it owns Engagement rules (`EngagementService`), personal-record
rules (`PersonalWorkspaceService`), the transport-neutral tool-result type, and the navigation
destination catalog, so REST handlers and harness tool adapters are thin translations of the same
outcome rather than two competing implementations.

The product lane uses Deep Agents. Copilot remains a local portability/evaluation comparison only,
not a deployed or release claim.

## A trustworthy agent turn

1. The API authenticates the actor and validates ownership of the session.
2. It sends the prompt and a validated navigation version to the internal session runtime.
3. The runtime keeps the write-once actor/session binding separate from user text.
4. The model selects one of twenty typed product tools: `navigate`; the six Engagement tools
   (`list_engagements`, `create_engagement`, `get_engagement`, `update_engagement`,
   `set_engagement_status`, `share_engagement`); and thirteen personal tools spanning Tasks
   (`list_tasks`, `create_task`, `update_task`, `delete_task`, `add_subtask`), Calendar
   (`list_events`, `create_event`, `update_event`, `delete_event`), and Reminders (`list_reminders`,
   `create_reminder`, `update_reminder`, `delete_reminder`).
5. The tool adapter binds the trusted actor and invokes the matching shared service, which re-reads
   authorized state and returns a typed outcome.
6. The runtime emits structured tool and terminal events over SSE.
7. The UI applies structured navigation only when it is valid and not superseded, then refreshes
   authoritative state.

The product skills are `engagement-meeting-prep`, `tasks`, `calendar`, and `weekly-review`.
`engagement-meeting-prep` resolves an authorized Engagement and prepares a grounded meeting brief;
`tasks` and `calendar` cover personal to-do and scheduling routines; `weekly-review` chains
`list_tasks`/`update_task`/`list_events`/`create_event` into a triage/reschedule/prioritize routine.
Direct field changes and navigation are ordinary product operations, not skill behavior. The
Assistant manages personal Tasks, Calendar events, and Reminders only through the thirteen typed
tools and the `home`/`tasks`/`calendar`/`reminders` navigation destinations — never through chat-text
control paths.

## Navigation and UI/UX

Engagements are the default landing surface. A CSA can use manual navigation immediately or ask the
assistant to navigate through a typed destination (`engagements`, `engagement_overview`,
`engagement_tasks`, `engagement_artifacts`, `home`, `tasks`, `calendar`, `reminders`). The destination
catalog validates route and Engagement identifiers; chat text and raw assistant output never select a
route. The detailed surface, breakpoint, and navigation contracts live in [UI/UX](capabilities/ui-ux.md)
and [Navigation](capabilities/navigation.md).

## Reminder email delivery

A reminder can optionally deliver a deterministic email when it comes due. The design keeps the safe
properties of at-most-once delivery and removes the unsafe ones of a prior unattended scheduler:

- the recipient is derived only from the owning actor's authenticated identity — an Entra actor's
  validated sign-in address, or a demo actor's operator-configured `REMINDER_DEMO_EMAIL` — never a
  client-supplied or reminder-stored address. The Entra address is the token's `preferred_username`
  claim, which this single-tenant showcase trusts as the actor's real mailbox; a multi-tenant
  deployment must switch to a verified-email claim first;
- the email body is a deterministic rendering of the reminder's own title, message, and due info;
  dispatch never creates a session or runs an agent turn, so unattended agent-generated reminder
  content stays excluded (see Non-goals);
- delivery is at-most-once via a claim-before-send update on the reminder's own record, and failures
  are recorded on the reminder rather than dropped silently; and
- with Azure Communication Services (ACS) unconfigured, reminders still display in-app and
  creation/editing still succeeds — only the email step is skipped.

Transport is ACS Email over `DefaultAzureCredential` (AAD-only, no keys). Dispatch runs as an
in-process tick inside the API app while it holds a replica (local dev, always-on deployments) or as
a one-shot pass invoked by an external scheduler (a cron/ACA Job) for scale-to-zero deployments.
**UNVERIFIED:** no ACS resource is provisioned in `infra/` today, so a real send has not been
observed; see [deployment](deployment.md).

## Azure deployment profile

`infra/deploy.sh` creates an isolated instance per explicit `INSTANCE_SLUG`: a resource group
`csa-wb-<slug>-rg` holding a public frontend and API Container App, an internal runtime Container
App, Cosmos DB and Blob Storage behind private endpoints, a VNet, a Basic Container Registry, and an
Azure OpenAI account/deployment — all at scale-to-zero (`0-1` replicas), managed identity for every
data plane, and no dedicated Log Analytics/Application Insights resource. The exact resource shape,
identity/RBAC contract, and recovery behavior are owned by
[Infrastructure](capabilities/infrastructure.md) and the [deployment runbook](deployment.md).

## Quality and evidence

A local browser journey passed 41/41 checks at the current revision, including the full page
inventory and a live agent turn, and `npm run verify` is green. Live-model spot checks cover the
personal tools. **Not verified:** a deployed Azure instance, a real Entra sign-in against this code,
a real ACS email send, and a live-model eval run of the `MVP-E8`/`MVP-E9` personal-work cases. The
[reference eval architecture](evals-reference-architecture.md) separates these lanes and requires
human review of demo output; do not infer deployed or live-model behavior from source inspection or
a deterministic check alone.

## Capability ownership

This document owns product intent and high-level boundaries. Detail is authoritative only in the
named capability document:

| Capability | Detailed authority |
|---|---|
| Information architecture, interaction, responsive behavior, accessibility | [UI/UX](capabilities/ui-ux.md) |
| Per-turn personalization and precedence | [Context](capabilities/context.md) |
| Destination catalog and route effects | [Navigation](capabilities/navigation.md) |
| Engagement commands, validation, roles, and outcomes | [CRUD](capabilities/crud.md) |
| Artifacts and the excluded document/retrieval surfaces | [Documents and retrieval](capabilities/documents-retrieval.md) |
| Ephemeral conversations and durable product state | [Session and state](capabilities/session-state.md) |
| Harness seam, tools, events, and traces | [Agent harness](capabilities/agent-harness.md) |
| Actors, sign-in, access rules, and service identity | [Identity and access](capabilities/identity-access.md) |
| Azure/local topology, cost, and deployment | [Infrastructure](capabilities/infrastructure.md) |
| Test, eval, browser, and deployment evidence | [Testing and evals](capabilities/testing-evals.md) |
| Evaluation strategy and roadmap | [Agent evals](capabilities/agent-evals.md) |

[Requirements](requirements.md) owns the release bar. [Development](development.md) and
[Deployment](deployment.md) are runbooks; they describe mechanics and never override design.

## Evidence boundary

Source inspection and deterministic checks can prove contracts and readiness of the checked-out
source. They cannot prove current browser rendering, Entra identity, Azure deployment, external
model behavior, or a customer demo. The [reference eval architecture](evals-reference-architecture.md)
separates those lanes and requires human review of demo output.

## Non-goals

This MVP does not claim external distribution, production readiness, accessibility conformance, live
security validation, broad project-management capability, multi-agent orchestration, continuous
metrics/scorecards, or a fixed provider/model configuration. Unattended agent-generated reminder
content (a stored-prompt headless agent turn) is a deliberate exclusion, not an oversight; reminder
email content is always the deterministic rendering described above. Any such decision needs explicit
human ownership.

## Relationship to external agent platforms

CSA Workbench does not depend on any customer's agent platform, and none is needed to build, run, or
understand the application. Teams building their own agents may reuse this repository's context,
tool, state, outcome, and harness patterns through a future authenticated adapter — one that gets no
bypass around the product's identity or authorization rules.
