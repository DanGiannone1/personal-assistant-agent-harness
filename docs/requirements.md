# MVP requirements and acceptance intent

> **Authority:** Release and acceptance intent. This document does not turn source inspection into live evidence.

## MVP intent

The internal POC should let a colleague understand and demonstrate a small, truthful Engagement workflow: manually create or open an authorized Engagement, then use the Assistant to read grounded Engagement state, make an exact authorized status change, and navigate back to that Engagement.

## Acceptance intent

1. The supported user surfaces are Engagements (default landing), the private Home/Tasks/Calendar/Reminders "My work" surfaces, Assistant, and Settings.
2. Authorized users can manually create and open Engagements; the Assistant operates through structured product tools and structured outcomes. Personal Tasks, Calendar events, and Reminders are owner-only, actor-scoped records; cross-actor access returns a neutral 404 with no mutation, and the Assistant manages them only through typed tools, never chat-text control paths.
3. Durable Engagement artifact metadata/bytes remain distinct from ephemeral session files. Session uploads are Markdown only.
4. The product skill set contains `engagement-meeting-prep`, `tasks`, `calendar`, and `weekly-review`.
5. The versioned MVP evidence has seven atomic cases and one three-turn workflow in `tests/evals/`.
6. Documentation says exactly which evidence is deterministic/source-scoped and which requires live browser, Entra, Azure, or model observation.
7. Azure deployment is isolated by explicit instance slug and model inputs, with human-owned plan and apply confirmation.
8. Reminder email delivery goes only to the owning actor's identity-derived address, is at-most-once, and records failures on the reminder rather than dropping them; with ACS unconfigured, reminders still work in-app without crashing.

## Limits

The acceptance intent excludes a global Library/Search or quick-links surface, unattended agent-generated reminder content (a stored-prompt headless agent turn — reminder email content is always deterministic), broader upload types than Markdown, generic document/retrieval capability, and a Copilot release lane. It also does not claim an accessibility conformance result, external distribution, production readiness, or a currently verified deployment. No deployed-Azure evidence or real-email-send evidence exists yet for reminder delivery; see [deployment](deployment.md).

The canonical demo/evidence sequence is [evals-reference-architecture.md](evals-reference-architecture.md). Focused implementation boundaries are described in [capabilities](capabilities/).
