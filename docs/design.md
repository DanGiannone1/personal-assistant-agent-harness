# CSA Workbench MVP design

> **Authority:** High-level product and system design. [Requirements](requirements.md) owns release intent; [governance](governance/README.md) owns lifecycle rules.

## Product boundary

CSA Workbench is an internal vertical-slice POC for solution-architect Engagement work. The supported user surfaces are:

- **Engagements** — create, open, and work with authorized Engagement records.
- **Assistant** — an assistant dock and a dedicated Assistant route using the same product state.
- **Settings** — user settings.

There is no supported personal task, calendar, reminder, home, generic workbench, Library, Search, quick-links, or scheduler surface. Enterprise search and generalized retrieval are future non-goals, not MVP capabilities.

Engagements are durable shared application records. The application stores durable artifact metadata with an Engagement and stores artifact bytes through its durable artifact backend (local isolated directory in local development, Blob when configured for an Entra release). Assistant-session files are separate, ephemeral workspace content; uploads to a session are Markdown (`.md`) only.

## System shape

```text
Browser -> Next.js frontend -> FastAPI API -> session runtime -> configured model service
                              |                 |
                              +-- Engagement state +-- ephemeral session workspace
                              +-- durable artifact bytes
```

The frontend applies assistant control effects only from validated structured events and refreshes product state after committed operations. The product lane uses Deep Agents. Copilot remains a local portability/evaluation comparison only, not a deployed or release claim.

The only product skill is `engagement-meeting-prep`. It resolves an authorized Engagement and prepares a grounded meeting brief; direct changes and navigation are ordinary product operations, not skill behavior.

## Evidence boundary

Source inspection and deterministic checks can prove contracts and readiness of the checked-out source. They cannot prove current browser rendering, Entra identity, Azure deployment, external model behavior, or a customer demo. The [reference eval architecture](evals-reference-architecture.md) separates those lanes and requires human review of demo output.

## Non-goals

This MVP does not claim external distribution, production readiness, accessibility conformance, live security validation, broad project-management capability, multi-agent orchestration, continuous metrics/scorecards, or a fixed provider/model configuration. Any such decision needs explicit human ownership.
