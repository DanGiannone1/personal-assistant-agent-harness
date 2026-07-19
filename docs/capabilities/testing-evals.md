# Testing and evaluation evidence

> **Authority:** Behavioral-evidence detail subordinate to the [authoritative design](../design.md)
> and [MVP requirements](../requirements.md)
>
> **Deployed application revision:** `807a0d6766036aa88dce8dcd9f16a2aabeb187b3`
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## What counts as proof

CSA Workbench tests a claim against the product state and control event that can make that claim
true. A passing result identifies its source revision and environment; local demo, real Entra, and
deployed observations are never interchangeable.

Use this truth order for each behavior:

1. **Authoritative effect** — read back the exact Cosmos state or Blob bytes the behavior should
   create, preserve, hide, or reject.
2. **Structured control** — correlate the typed tool result, navigation event, and one terminal event
   to the same run and target.
3. **Rendered behavior** — drive the real frontend as a user and reconcile what it renders with that
   state and event record.
4. **Supporting record** — use traces, timings, screenshots, manifests, and command output to explain
   the run and make review possible.

The expected behavior must be stated before interpreting the observation. Assistant wording, tool
progress labels, success-like marker text, browser-cached or optimistic state, HTTP health alone, a
screenshot alone, and a green build or command are not application-state oracles. Normalizing
volatile timestamps and store metadata helps compare states; it does not turn wording, static
inspection, or a runner's own `pass` field into proof.

## Evidence profiles

| Profile | Oracle and use | Boundary |
|---|---|---|
| Unit and contract | Deterministic assertions for domain rules, identity and workload boundaries, tool/event schemas, evidence utilities, and infrastructure inventory logic | No browser, model, data service, Entra redirect, or live Azure proof |
| Local deterministic users | Guarded `demo` fixtures for Dan, Ava, and Sam; compare personal portfolios, roles, sharing, denial, and exact state effects in a dedicated local Cosmos emulator | Synthetic actors are not tenant identities; local storage and networking are not Azure |
| Live local model | Deep Agents calls a real configured model; score only typed results, correlated events, and normalized state effects for the versioned seven-case set | Model selection is exercised, but Entra, managed workload identity, and deployed private paths are not |
| Playwright and responsive captures | A real browser drives the frontend/API at 1440, 1024, and 390 CSS px; DOM behavior, overflow, focus, state, and structured SSE evidence are asserted and six representative screenshots are reviewed | Captures support the asserted host journey; they are not broad visual, accessibility, or `/assistant` proof |
| Deployed real Entra | The identified immutable revision exercises tenant auth, actor-bound state, API-to-runtime workload identity, private Cosmos/Blob paths, and a typed live turn | Run-specific deployment evidence does not become proof for another revision, tenant actor, or journey |

One run may contribute to more than one profile, but its claims stay within the environment and
oracles it actually exercised. Broad production, load, disaster-recovery, multi-region, and
generalized security test programs are outside the MVP release bar.

## Current evidence record

### Repository-verifiable focused checks

The focused suites cover the shared Engagement rules, demo/Entra mode separation, session and
workload binding, structured tool/event handling, reset and evidence guards, and the declared Azure
inventory verifier. The source-controlled checks are:

```bash
PYTHONPATH=$PWD:$PWD/session-container uv run --project session-container --with pytest \
  pytest -q tests/test_reset_demo_state.py tests/test_identity_modes.py \
  tests/test_engagement_core.py tests/test_structured_control.py \
  tests/test_infra_entra_contract.py tests/test_release_boundaries.py
npm run test:mvp-evidence
(cd frontend && npm run test:contract && npm run lint && npm run build)
```

These commands prove only their assertions against the checkout on which they run. Infrastructure
contract tests exercise the verifier with fixtures; they do not query or deploy Azure. Frontend
lint/build and contract checks support browser evidence but do not replace it.

### Accepted local browser evidence

The accepted local synthetic Playwright observation has run ID
`2026-07-15T02-57-58-244Z-1e852bb3`. Its ignored local `results.json` records **34/34 checks**, no
failures, and no page errors at
`9142b2a1fe70e86af00b5071b1a4e4215327feb1`. It reconciles three deterministic actors, sharing and
outsider isolation, viewer affordances, rejected validation with unchanged state, a typed agent
status update, authoritative UI refresh, wide/compact/narrow overflow, and narrow drawer focus and
hit-testing.

The same run contains six captures:

- `wide-dan-portfolio.png`;
- `wide-owner-shared-engagement.png`;
- `wide-agent-updated-engagement.png`;
- `compact-sam-viewer.png`;
- `narrow-dan-drawer-open.png`; and
- `narrow-dan-workspace.png`.

One frontend file changed after `9142b2a1fe70e86af00b5071b1a4e4215327feb1`: `MessageList.tsx`
replaced unsupported assistant suggestions with supported Engagement operations. The recorded run
remains supporting evidence for the unchanged host workflows and responsive layout, but it is not a
final-SHA bundle and does not prove the corrected suggestion copy interactively. Contract tests,
lint, build, and a deployed-bundle string check cover that copy-only delta. Generated local bundles
are ignored runtime output, not checked-in release artifacts.

### Live local model evaluation

[`tests/evals/mvp-cases.json`](../../tests/evals/mvp-cases.json) defines seven readable cases:
authorized list, grounded read, typed navigation, editor mutation, missing-reason non-commit,
outsider non-commit, and inert marker/success-like prose. The ignored local observation with run ID
`2026-07-15T01-27-46-902Z-2ecc70df` records 7/7 with Deep Agents at
`7bca264d62bf99f0c654443cc2a38e30c92d4f42`. That is historical supporting evidence, not a
tracked artifact or final-SHA evaluation.

Each case requires one correlated `RUN_STARTED`, exactly one final terminal event, the expected
typed result where required, and the expected normalized state effect. The missing-reason and
outsider cases also allow narrowly named safe-non-execution alternatives observed from the model:
no tool result for the former, or one `list`/`succeeded` result for the latter. Those alternatives
prove unchanged state and no false effect; they do not prove the typed invalid/not-found branch ran.
The marker case requires zero tool results, no navigation, and unchanged state. Exact prose, token
timing, and hidden reasoning are deliberately ungraded.

### Final deployed release observation

Application revision `ce251fbbe03c6b99bc38e676a8be88e9f199f777` repeated frontend root,
`/assistant`, API health, real-Entra `/auth/me`, Engagement, quick-link, immutable-image, and exact
topology checks. Live desktop and 390px browser evidence proved the repaired Microsoft sign-in
color, 4.525:1 contrast, zero horizontal overflow, no page/console errors, and redirect to
`login.microsoftonline.com`. The deployed Next.js 16.2.10/PostCSS 8.5.20 dependency baseline had
zero npm audit findings, and foundation deployment preserved the exact tenant-governance NSG pair.
The typed-agent and Blob round trips below were not repeated for that frontend-only
behavior/dependency change.

The authoritative design records application revision `807a0d6` passing frontend root and
`/assistant` responses, API health, real-Entra `/auth/me`, Engagement and quick-link reads, session
creation, authoritative Engagement state readback, and a Deep Agents turn. The turn
`List my engagements.` emitted typed `list_engagements` and successful `engagement.listed` evidence
before describing the same Cosmos-backed record. It also records a Blob-backed API round trip at the
final private topology: upload, list, byte-for-byte download, and delete. The live post-deployment
topology verifier passed for the three SHA-pinned, scale-to-zero apps, private Cosmos/Blob access,
DNS, exact inventory, managed-identity role containment within `csa-workbench-rg`, the moved Basic
registry, and the exact optional tenant-governance NSG pair.

These are authoritative release observations, but the repository has no checked-in deployment
transcript, per-event turn transcript, Blob request/response and hash record, inventory JSON, or
verifier output. They therefore cannot be independently replayed from this checkout. A successful
health probe alone would not prove auth, state, typed control, or private data paths.

## Safe, repeatable local evidence

The synthetic fixture uses stable actors `dan`, `ava`, and `sam` in a dedicated local Cosmos
emulator database/container. [`scripts/reset_demo_state.py`](../../scripts/reset_demo_state.py) is
destructive only after all of these guards pass:

- `IDENTITY_MODE=demo`, an environment-supplied nonempty `DEMO_PASSWORD`, and
  `CONFIRM_DEMO_RESET=YES`;
- an absolute loopback `COSMOS_ENDPOINT`;
- database and container names that each contain `demo` or `local`;
- no `ARTIFACTS_ACCOUNT`, with deletion restricted to `.mvp-artifacts/`; and
- the repository's fixed `workspace/`, not an arbitrary `WORKSPACE` override.

The reset deletes exactly that guarded local container and the dedicated local trees, seeds through
the application demo path, and reports fixture version, normalized SHA-256 hash, stable IDs, and
counts. Refusal is the expected outcome when any guard is missing.

Both live runners additionally require `MVP_RESET_BEFORE_RUN=1` and refuse source changes reported by
`git status`; only generated files under `evidence/mvp/local-synthetic/` are exempt. This prevents a
committed SHA from labeling uncommitted runner or product code. It also means a documentation edit in
progress correctly prevents a new accepted bundle. The runners then supply the reset acknowledgement,
verify loopback app/API targets, reset the fixture, and write run-scoped results beneath:

```text
evidence/mvp/local-synthetic/agent-evals/<run-id>/results.json
evidence/mvp/local-synthetic/playwright/<run-id>/results.json
evidence/mvp/local-synthetic/playwright/<run-id>/*.png
```

With the emulator and all three services already running, the live commands are:

```bash
export IDENTITY_MODE=demo
export DEMO_PASSWORD='local-test-secret'  # local environment only
export COSMOS_ENDPOINT='http://localhost:8081'
export COSMOS_DATABASE='csa_workbench_demo'
export COSMOS_CONTAINER='appstate_demo'
export COSMOS_KEY='your-emulator-key'
export ARTIFACTS_DIR='.mvp-artifacts'

CONFIRM_DEMO_RESET=YES uv run python scripts/reset_demo_state.py
MVP_RESET_BEFORE_RUN=1 npm run eval:mvp
MVP_RESET_BEFORE_RUN=1 npm run playwright:mvp
```

The password and emulator key stay in the local environment and must not enter source or browser
text. [Local development](../development.md) covers service startup. The runners do not start
services and must never be pointed at Entra or a remote store.

## Release-bar map

| Requirement or journey | Minimum evidence and current boundary |
|---|---|
| R1 | Authority/link/terminology review against the release revision; documentation consistency is not inferred from runtime tests |
| R2 and S5 | Final-SHA deployment plus live topology verifier, health, identity, private data paths, exact inventory, scale, and latency record; raw transcript and cost export remain absent |
| R3–R5 and S1–S2 | Focused role/identity contracts, deterministic multi-user browser state reconciliation, and real-Entra confirmation; the second real tenant actor remains absent |
| R6 and S4 | Reviewed real-frontend Playwright journey and six captures at wide, compact, and 390 px; narrow standalone `/assistant` remains absent |
| R7 and S3 | Tool/schema/event contracts, adversarial inert-text cases, live local model results, and the final typed deployed turn; prose never supplies control or commit evidence |
| R8 | One criterion-level record that names revision, profile, fixture/configuration, oracles, results, screenshots where applicable, and gaps |

## Open evidence gaps

- No clean-worktree browser/eval bundle is stamped with final application SHA `807a0d6`.
- No second real tenant actor proves deployed collaboration or isolation.
- No interactive Entra browser record proves redirect/return, rendered portfolio, collaboration, and
  sign-out.
- The standalone `/assistant` route is not narrow-screen complete or covered at 390 px.
- No deployment transcript, live topology output, Blob round-trip transcript, or Azure cost export is
  checked in; no numeric cost is claimed.
- Commands, agent turns, and deployment checks have no durable, actor-authorized receipts. Local
  traces and generated bundles are ephemeral evidence, not a replay or recovery contract.

Mark a missing profile **UNVERIFIED**. Do not replace it with source inspection, assistant wording,
an older revision's result, or a broader production test requirement outside R1–R8 and S1–S5.
