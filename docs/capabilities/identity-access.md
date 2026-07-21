# Identity and access boundary

> **Authority:** Focused current-boundary note.

Local development uses deterministic demo identity and requires a nonempty local `DEMO_PASSWORD`. The launcher is intentionally local-only for isolated demo stacks. Azure release configuration can use Entra identity and managed identities; its live behavior requires a separately authorized observation.

Engagement access is actor-bound. The API and agent tools use the effective actor rather than accepting an arbitrary caller identity from a model. This document describes source-level boundaries only; it does not claim live Entra or security validation.
