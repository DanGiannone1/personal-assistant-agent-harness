# CSA Workbench MVP design

> **Authority:** High-level product and system design. [Requirements](requirements.md) owns release intent; [governance](governance/README.md) owns lifecycle rules.

## Product boundary

CSA Workbench is an internal vertical-slice POC for solution-architect Engagement work. The supported user surfaces are:

- **Engagements** — create, open, and work with authorized Engagement records; this remains the default landing surface.
- **My work** — private, actor-owned Home, Tasks (with subtasks), Calendar, and Reminders pages, scoped solely to the authenticated actor and never shared or Engagement-scoped.
- **Assistant** — an assistant dock and a dedicated Assistant route using the same product state.
- **Settings** — user settings.

There is no supported generic workbench, global Library/Search, or quick-links surface. Enterprise search and generalized retrieval are future non-goals, not MVP capabilities.

Engagements are durable shared application records. The application stores durable artifact metadata with an Engagement and stores artifact bytes through its durable artifact backend (local isolated directory in local development, Blob when configured for an Entra release). Assistant-session files are separate, ephemeral workspace content; uploads to a session are Markdown (`.md`) only.

Personal Tasks, Calendar events, and Reminders are durable per-actor records held on a single `personal-{uid}` aggregate keyed solely from authenticated identity, never a caller-supplied owner. Reminders can optionally deliver a deterministic email (title, message, due info) to the owning actor's own identity-derived address through Azure Communication Services; see [Reminder email delivery](#reminder-email-delivery) below.

## System shape

```text
Browser -> Next.js frontend -> FastAPI API -> session runtime -> configured model service
                              |                 |
                              +-- Engagement state +-- ephemeral session workspace
                              +-- durable artifact bytes
```

The frontend applies assistant control effects only from validated structured events and refreshes product state after committed operations. The product lane uses Deep Agents. Copilot remains a local portability/evaluation comparison only, not a deployed or release claim.

The product skills are `engagement-meeting-prep`, `tasks`, `calendar`, and `weekly-review`. `engagement-meeting-prep` resolves an authorized Engagement and prepares a grounded meeting brief; `tasks` and `calendar` cover personal to-do and scheduling routines; `weekly-review` chains them into a triage/reschedule/prioritize routine. Direct changes and navigation are ordinary product operations, not skill behavior. The Assistant manages personal Tasks, Calendar events, and Reminders only through the thirteen typed personal tools and the `home`/`tasks`/`calendar`/`reminders` navigation destinations — never through chat-text control paths.

## Reminder email delivery

A reminder can optionally deliver a deterministic email when it comes due. The design keeps the safe properties of at-most-once delivery and removes the unsafe ones of the prior unattended scheduler:

- the recipient is derived only from the owning actor's authenticated identity — an Entra actor's validated sign-in address, or a demo actor's operator-configured `REMINDER_DEMO_EMAIL` — never a client-supplied or reminder-stored address. The Entra address is the token's `preferred_username` claim, which this single-tenant showcase trusts as the actor's real mailbox; a multi-tenant deployment must switch to a verified-email claim first;
- the email body is a deterministic rendering of the reminder's own title, message, and due info; dispatch never creates a session or runs an agent turn, so unattended agent-generated reminder content stays excluded (see Non-goals);
- delivery is at-most-once via a claim-before-send update on the reminder's own record, and failures are recorded on the reminder rather than dropped silently; and
- with Azure Communication Services (ACS) unconfigured, reminders still display in-app and creation/editing still succeeds — only the email step is skipped.

Transport is ACS Email over `DefaultAzureCredential` (AAD-only, no keys). Dispatch runs as an in-process tick inside the API app while it holds a replica (local dev, always-on deployments) or as a one-shot pass invoked by an external scheduler (a cron/ACA Job) for scale-to-zero deployments.

## Evidence boundary

Source inspection and deterministic checks can prove contracts and readiness of the checked-out source. They cannot prove current browser rendering, Entra identity, Azure deployment, external model behavior, or a customer demo. The [reference eval architecture](evals-reference-architecture.md) separates those lanes and requires human review of demo output.

## Non-goals

This MVP does not claim external distribution, production readiness, accessibility conformance, live security validation, broad project-management capability, multi-agent orchestration, continuous metrics/scorecards, or a fixed provider/model configuration. Unattended agent-generated reminder content (a stored-prompt headless agent turn) is a deliberate exclusion, not an oversight; reminder email content is always the deterministic rendering described above. Any such decision needs explicit human ownership.
