# MVP requirements and acceptance intent

> **Authority:** Release and acceptance intent. This document does not turn source inspection into live evidence.

## What the MVP must prove

CSA Workbench is successful when it is a working, professional engagement workspace for solution
architects — a personal "My work" space plus a shared Engagement portfolio — and a clear reference
implementation of typed-tool agent architecture. The application, documentation, tests, and (when
deployed) the Azure environment must describe and prove the same behavior. Accuracy and simplicity
take precedence; cost and latency are minimized within that boundary.

## MVP intent

The internal POC should let a colleague understand and demonstrate a small, truthful Engagement workflow: manually create or open an authorized Engagement, then use the Assistant to read grounded Engagement state, make an exact authorized status change, and navigate back to that Engagement.

## Acceptance intent

1. The supported user surfaces are Engagements (default landing), the private Home/Tasks/Calendar/Reminders "My work" surfaces, Assistant, and Settings.
2. Authorized users can manually create and open Engagements; the Assistant operates through structured product tools and structured outcomes. Personal Tasks, Calendar events, and Reminders are owner-only, actor-scoped records; cross-actor access returns a neutral 404 with no mutation, and the Assistant manages them only through typed tools, never chat-text control paths.
3. Durable Engagement artifact metadata/bytes remain distinct from ephemeral session files. Session uploads are Markdown only.
4. The product skill set contains `engagement-meeting-prep`, `tasks`, `calendar`, and `weekly-review`.
5. The versioned MVP evidence has nine atomic cases and one three-turn workflow in `tests/evals/`.
6. Documentation says exactly which evidence is deterministic/source-scoped and which requires live browser, Entra, Azure, or model observation.
7. Azure deployment is isolated by explicit instance slug and model inputs, with human-owned plan and apply confirmation.
8. Reminder email delivery goes only to the owning actor's identity-derived address, is at-most-once, and records failures on the reminder rather than dropping them; with ACS unconfigured, reminders still work in-app without crashing.

## Acceptance journeys

- **Personal and shared work.** Two different actors sign in, each see only their own "My work"
  pages, and see only Engagements where they are current members. One actor shares an Engagement
  with the other; both then observe the same shared record. An outsider cannot read it.
- **Structured agent control.** The assistant opens an authorized Engagement and performs one
  supported change through a typed tool and a structured result. A prompt containing route names,
  tool names, marker-like strings, or success-like prose cannot trigger navigation or a false
  success without the corresponding structured event and committed outcome; personal-work requests
  follow the identical rule through the thirteen typed personal tools.
- **Responsive UI.** The Engagement and "My work" journeys remain usable at wide, compact, and 390
  CSS-pixel widths, including loading, empty, validation, permission, and failure states.
- **Clean, isolated Azure deployment.** A release revision deploys into its own `INSTANCE_SLUG`
  resource group behind an explicit human plan/apply confirmation. The resource inventory shows the
  intended scale-to-zero, private-network profile, and observed cold-start latency is recorded
  rather than hidden.

## Limits

The acceptance intent excludes a global Library/Search or quick-links surface, unattended agent-generated reminder content (a stored-prompt headless agent turn — reminder email content is always deterministic), broader upload types than Markdown, generic document/retrieval capability, and a Copilot release lane. It also does not claim an accessibility conformance result, external distribution, production readiness, or a currently verified deployment. No deployed-Azure evidence or real-email-send evidence exists yet for reminder delivery; see [deployment](deployment.md).

The canonical demo/evidence sequence is [evals-reference-architecture.md](evals-reference-architecture.md). Focused implementation boundaries are described in [capabilities](capabilities/).
