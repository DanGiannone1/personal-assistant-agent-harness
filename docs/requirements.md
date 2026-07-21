# MVP requirements and acceptance intent

> **Authority:** Release and acceptance intent. This document does not turn source inspection into live evidence.

## MVP intent

The internal POC should let a colleague understand and demonstrate a small, truthful Engagement workflow: manually create or open an authorized Engagement, then use the Assistant to read grounded Engagement state, make an exact authorized status change, and navigate back to that Engagement.

## Acceptance intent

1. The supported user surfaces remain Engagements, Assistant, and Settings.
2. Authorized users can manually create and open Engagements; the Assistant operates through structured product tools and structured outcomes.
3. Durable Engagement artifact metadata/bytes remain distinct from ephemeral session files. Session uploads are Markdown only.
4. The product skill set contains only `engagement-meeting-prep`.
5. The versioned MVP evidence has seven atomic cases and one three-turn workflow in `tests/evals/`.
6. Documentation says exactly which evidence is deterministic/source-scoped and which requires live browser, Entra, Azure, or model observation.
7. Azure deployment is isolated by explicit instance slug and model inputs, with human-owned plan and apply confirmation.

## Limits

The acceptance intent excludes a personal task/calendar/reminder experience, generic Library/Search or quick links, scheduler, generic document/retrieval capability, and a Copilot release lane. It also does not claim an accessibility conformance result, external distribution, production readiness, or a currently verified deployment.

The canonical demo/evidence sequence is [evals-reference-architecture.md](evals-reference-architecture.md). Focused implementation boundaries are described in [capabilities](capabilities/).
