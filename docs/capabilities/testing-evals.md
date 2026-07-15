# Testing and evaluation evidence

> **Authority:** Behavioral evidence detail subordinate to the [authoritative design](../design.md) and [MVP requirements](../requirements.md)
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)
> **Current state:** The commands below create local synthetic evidence when run. They do not prove a checkout until their generated bundle is reviewed.

## The rule

CSA Workbench evidence reconciles three things: the real rendered UI, the
authoritative application state, and structured tool/turn events. Assistant
prose, a tool label, screenshots alone, and a green command are never success
oracles.

Every result records the source revision, fixture version/hash, local identity
mode, harness, model deployment, timing, viewport where applicable, structured
events, normalized state before/after, and its criterion-level verdicts.
Generated evidence is local runtime output under
`evidence/mvp/local-synthetic/<runner>/<run-id>/`; it is not source-controlled
proof and must not be fabricated.

## Start with deterministic local fixtures

The MVP synthetic actors are `dan`, `ava`, and `sam`. Their stable fixture gives
Dan owner access to Website Launch and editor access to Product Launch, Ava owner
access to Product Launch and Q3 Budget, and Sam viewer access to Website Launch.
The browser runner creates one additional Engagement to prove sharing and
outsider isolation without relying on a pre-existing ID.

`scripts/reset_demo_state.py` is intentionally destructive, and only to a
clearly named local Cosmos emulator database/container. It requires all of:

- `IDENTITY_MODE=demo` and a nonempty environment-supplied `DEMO_PASSWORD`;
- a direct `CONFIRM_DEMO_RESET=YES` acknowledgement;
- a loopback `COSMOS_ENDPOINT`; no Azure or other remote hostname;
- `COSMOS_DATABASE` and `COSMOS_CONTAINER` whose names explicitly include
  `demo` or `local`; and
- no `ARTIFACTS_ACCOUNT`, because reset deletes only the dedicated
  `.mvp-artifacts/` subtree. It clears only this repository's `workspace/` path,
  never an arbitrary `WORKSPACE` override.

It removes all documents in that guarded container and the local artifact tree,
then uses the application demo seeding path. The JSON output reports fixture
version, normalized SHA-256 hash, stable IDs, and counts. A missing guard is a
refusal, not a best-effort cleanup.

## Local verification layers

Run the focused contracts first. They are fast checks of reset guards and the
event/state oracle, not browser or model proof.

```bash
PYTHONPATH=$PWD:$PWD/session-container uv run --project session-container --with pytest pytest -q tests/test_reset_demo_state.py tests/test_identity_modes.py tests/test_engagement_core.py tests/test_structured_control.py
npm run test:mvp-evidence
(cd frontend && npm run lint && npm run build)
```

With a pre-existing local emulator and the three services running through
`uv run dev.py`, run the guarded reset and the live evidence commands. These
commands do not start or stop the emulator or application services.

```bash
export IDENTITY_MODE=demo
export DEMO_PASSWORD='local-test-secret'  # environment only; never source/UI text
export COSMOS_ENDPOINT='http://localhost:8081'
export COSMOS_DATABASE='csa_workbench_demo'
export COSMOS_CONTAINER='appstate_demo'
export COSMOS_KEY='your-emulator-key'
export ARTIFACTS_DIR='.mvp-artifacts'

CONFIRM_DEMO_RESET=YES uv run python scripts/reset_demo_state.py
MVP_RESET_BEFORE_RUN=1 npm run eval:mvp
MVP_RESET_BEFORE_RUN=1 npm run playwright:mvp
```

The runner repeats the reset itself only when `MVP_RESET_BEFORE_RUN=1` is set,
which is the runner-level destructive acknowledgement; it supplies the reset's
`CONFIRM_DEMO_RESET=YES` acknowledgement itself. Each result therefore starts
from a verified fixture without a password argument or static secret.
Both live runners refuse a dirty Git worktree before reset, so a captured source
revision cannot be mistaken for the contents of uncommitted evidence code.

## MVP browser journey

`scripts/mvp_playwright.mjs` drives the real frontend and real API. It captures
wide `1440×900`, compact `1024×768`, and narrow `390×844` screenshots, checks
page-level overflow, and verifies narrow drawer focus, Escape closure, and focus
restoration. It exercises and reconciles:

1. distinct Dan/Ava portfolios and a Dan-created Engagement where Dan is owner;
2. owner sharing Ava as editor, Ava's UI edit, and Dan's authoritative refresh;
3. Sam's hidden list entry, direct read, forged write, unchanged owner state, and
   seeded viewer affordances;
4. visible status-reason validation without an accidental commit; and
5. a real assistant status change. The runner accepts that change only when a
   `TOOL_CALL_RESULT` is structured `committed` and the refreshed authoritative
   Engagement has the exact change. It does not inspect assistant wording as an
   oracle.

Page errors and failed DOM/state/event checks are written to `results.json`.
Loading/failure injection is deliberately not a broad local fault framework;
the MVP has validation and permission evidence here, while dependency failures
remain a separate targeted test when their behavior changes.

## MVP live agent evaluation

`tests/evals/mvp-cases.json` is small, versioned, and intentionally readable.
The live runner covers authorized list/read/navigation, an editor mutation, a
missing reason, an outsider mutation, and marker/success-like prose. Each case
requires exactly one terminal event and scores only typed `TOOL_CALL_RESULT`
data, normalized authoritative state effects, and structured navigation events.
It records latency but does not grade exact wording, token timing, or hidden
reasoning.

Every case begins with one correlated `RUN_STARTED` and ends with exactly one
final terminal event. Except for a case explicitly requiring zero tool results,
it requires a valid structured result; operation and status must occur on the
same result. Where a result includes an Engagement resource ID, it must match
the case target. A committed update also proves the requested status/reason and
that no state outside its named Engagement aggregate changed. Its target record
may differ only in status/reason and the one expected `engagement.updated`
activity receipt; names, members, customer data, and other business fields stay
identical.

A non-commit case must demonstrate unchanged state. The marker case cannot
create route or success evidence merely by including route/tool/result-looking
text in the prompt. A case with a missing, duplicated, malformed, or wrong
terminal event fails closed.

## Separate profiles

| Profile | What it proves | What it does not prove |
|---|---|---|
| Focused contracts | Guard semantics, event parsing, structured-oracle logic, identity/core contracts | A running browser, Cosmos, model, or Azure |
| Local synthetic browser/evals | Real frontend/API/Deep Agents behavior with deterministic demo actors and a local emulator | Entra, Azure networking, managed identity, or deployment behavior |
| Real-Entra smoke | Two actual tenant users can sign in and perform the scoped shared Engagement smoke | Broad production hardening or a substitute for local repeatable coverage |
| Deployed evidence | The identified deployed revision's identity, storage, runtime, and UX behavior | A timeless claim about later revisions |

Real-Entra and deployed runs use their own non-demo data store and explicitly
record revision/image/configuration. The destructive demo reset is unavailable
there. No current local result should be relabelled as either profile.

## Review checklist

For R3–R8 and S1–S4, review the generated `results.json` and named screenshots
at the same run path. Confirm the source revision, fixture hash, structured
terminal/tool results, normalized state deltas, UI checks, no-leak assertions,
and screenshots all refer to the same run. Mark unavailable live behavior
**UNVERIFIED**, rather than replacing it with static plausibility.
