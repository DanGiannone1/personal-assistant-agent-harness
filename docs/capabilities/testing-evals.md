# Testing and evaluation boundary

> **Authority:** Focused evidence note. [Governance testing](../governance/testing-charter.md) controls the repository evidence standard.

## What counts as proof

A passing result is checked against actual product state and the structured event that would prove
the action happened — not against assistant wording, a screenshot alone, an HTTP health check alone,
or a green build alone. Local demo, real Entra, and deployed observations are never interchangeable;
a passing result always names the source revision and environment it came from.

## Kinds of test evidence

| Kind of evidence | What it proves | What it doesn't prove |
|---|---|---|
| Unit and contract | Deterministic assertions for Engagement and personal-workspace rules, identity/workload boundaries, tool/event schemas, and infrastructure inventory logic | No browser, model, data service, Entra redirect, or live Azure proof |
| Local deterministic users | Guarded `demo` fixtures for `dan`, `ava`, and `sam`; personal isolation, Engagement roles, sharing, and denial in a dedicated local Cosmos emulator | Synthetic actors are not tenant identities |
| Live local model | Deep Agents calls a real configured model against the nine atomic cases plus one three-turn workflow, graded by typed results, correlated events, raw model-visible tool outputs, and normalized state | Entra, managed workload identity, deployed private paths, and general reliability are not exercised |
| Waza skill laboratory | The `engagement-meeting-prep` skill runs through Waza/Copilot against hermetic mocks; routing and tool constraints are hard checks | Not Deep Agents product-runtime, Cosmos, AG-UI, or navigation evidence; does not cover the `tasks`/`calendar`/`weekly-review` skills |
| Browser captures | A real browser drives the frontend/API across the covered surfaces; DOM behavior, state, and structured SSE evidence are asserted | Captures support the asserted journey; they are not a broad visual/accessibility audit |
| Deployed real Entra | An identified revision exercises tenant auth, actor-bound state, workload identity, and private data paths | Run-specific evidence does not become proof for another revision |

## `npm run verify`

`npm run verify` (`scripts/verify.sh`) is the deterministic local verification entry point: `uv lock
--check` for both projects, the focused pytest suite below, `npm run test:mvp-evidence`, `npm run
eval:waza:check`, frontend contract/lint/build checks, shell-syntax checks, Bicep compilation
(skippable with `CSA_VERIFY_SKIP_BICEP=1`, matching `npm run verify:ci`), and `git diff --check`. It
does not prove a live browser, Cosmos emulator run, Entra authentication, Azure deployment, or model
turn.

The exact focused pytest suite it runs is `test_dev_launcher`, `test_reset_demo_state`,
`test_local_quality`, `test_identity_modes`, `test_engagement_core`, `test_structured_control`,
`test_infra_entra_contract`, `test_release_boundaries`, `test_skill_runtime`,
`test_personal_workspace`, and `test_reminder_dispatch` — covering both the Engagement domain and the
personal-workspace/reminder-dispatch domain added since the MVP's initial evidence set.

`npm run test:mvp-evidence` verifies source/oracle behavior for the nine atomic cases and the
three-turn workflow. `npm run eval:waza:check` validates the pinned Waza readiness path for the
`engagement-meeting-prep` skill specifically and its eval schema — it does not cover the `tasks`,
`calendar`, or `weekly-review` skills. Both are deterministic source/readiness checks.

`npm run eval:waza:gate` and `npm run eval:waza:advisory` make external Copilot/model calls and
require deliberate human authorization. They evaluate same-skill routing in a laboratory lane, not
Deep Agents product state. Live MVP evaluation (`npm run eval:mvp`) and Playwright
(`npm run playwright:mvp`) also require deliberate setup, a running local stack, and human review —
see [development](../development.md) for the exact isolated-run procedure.

## Current evidence status

A local browser journey has passed 41/41 checks ([current evidence record](../evidence.md)), including the full page
inventory (Engagements, My work, Assistant, Settings) and a live agent turn. Live-model spot checks
cover the personal tools. **UNVERIFIED from this repository:** a deployed Azure instance, a real
Entra sign-in against this code, a real Azure Communication Services email send, and a live-model
eval run of the `MVP-E8`/`MVP-E9` personal-work cases specifically. A pass label, assistant prose, or
an older revision's result is never a substitute for state, structured-event, browser, Entra, Azure,
or model evidence in the environment actually being claimed.

The [canonical eval reference architecture](../evals-reference-architecture.md) defines the demo
sequence and evidence lanes in detail.

## Related authority

- [Design](../design.md)
- [Requirements](../requirements.md)
- [Agent harness](agent-harness.md)
- [Agent evals](agent-evals.md)
- [Governance testing charter](../governance/testing-charter.md)
