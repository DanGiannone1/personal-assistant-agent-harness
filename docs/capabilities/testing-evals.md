# Testing and evaluation boundary

> **Authority:** Focused evidence note. [Governance testing](../governance/testing-charter.md) controls the repository evidence standard.

`npm run verify` is the deterministic local verification entry point. It includes focused tests, deterministic MVP evidence checks, Waza readiness validation, frontend checks, syntax/compile checks, and `git diff --check`. It does not prove a live browser, Cosmos emulator run, Entra authentication, Azure deployment, or model turn.

`npm run test:mvp-evidence` verifies source/oracle behavior for the seven atomic cases and three-turn workflow. `npm run eval:waza:check` validates the pinned Waza readiness path for the one product skill and its eval schema. Both are deterministic source/readiness checks.

`npm run eval:waza:gate` and `npm run eval:waza:advisory` make external Copilot/model calls and require deliberate human authorization. They evaluate same-skill routing in a laboratory lane, not Deep Agents product state. Live MVP and Playwright runs also require deliberate setup and review. A pass label, assistant prose, or historical observation is not a substitute for state, structured-event, browser, Entra, Azure, or model evidence in the environment actually being claimed.

The [canonical eval reference architecture](../evals-reference-architecture.md) defines the demo sequence and evidence lanes.
