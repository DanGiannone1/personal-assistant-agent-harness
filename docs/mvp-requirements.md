# Requirements Path Moved

> **Authority:** Compatibility pointer only; superseded 2026-07-14 by issue #15.

The reconciled release bar is [requirements.md](requirements.md). It resolves the former viewer
artifact-permission conflict, responsive-scope conflict, and compute-profile conflict in favor of
the [authoritative design](design.md).

Legacy source comments may still name old requirement IDs. Use this temporary routing map:

| Old ID | Current authority |
|---|---|
| R7 — parked domain capabilities | [Design non-goals](design.md#deliberately-not-in-the-first-release) and [v1 non-goals](requirements.md#non-goals-for-v1) |
| R11 — harness selection | [R18](requirements.md#assistant-behavior) and [Agent harness](capabilities/agent-harness.md) |
| R17 — scale-to-zero/cost | [R24](requirements.md#durability-platform-and-evidence) and [Infrastructure](capabilities/infrastructure.md) |
| R18 — private/identity-based data access | [R25–R26](requirements.md#durability-platform-and-evidence), [Identity](capabilities/identity-access.md), and [Infrastructure](capabilities/infrastructure.md) |

The previous requirement set remains in Git history at
`master@1fcaac6:docs/mvp-requirements.md`.
