# Testing and evaluation evidence

> **Authority:** This document covers testing and evaluation evidence; see [design.md](../design.md)
> and [MVP requirements](../requirements.md) for the full picture.
>
> **Deployed application revision:** `ce251fbbe03c6b99bc38e676a8be88e9f199f777`
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## What counts as proof

CSA Workbench checks a claim against two things: the actual product state, and the structured event
that would prove the action happened. A passing result always names the source revision and
environment it came from; local demo, real Entra, and deployed observations are never interchangeable.

Trust these kinds of evidence in this order:

1. **What actually happened** — read back the exact Cosmos state or Blob bytes the behavior should
   create, preserve, hide, or reject.
2. **What the system reported as it happened** — match the typed tool result, navigation event, and
   final event to the same run and target.
3. **What the user saw** — drive the real frontend and check it against that state and event record.
4. **Supporting detail** — traces, timings, screenshots, manifests, and command output that help
   explain a run and make it reviewable.

You have to state the expected behavior before you look at the observation, not after. Assistant
wording, tool progress labels, success-like marker text, browser-cached or optimistic state, HTTP
health alone, a screenshot alone, and a green build or command are none of them proof of application
state on their own. Normalizing volatile timestamps and store metadata helps compare states; it does
not turn wording, static inspection, or a runner's own `pass` field into proof.

## Kinds of test evidence

| Kind of evidence | What it proves, and how it's used | What it doesn't prove |
|---|---|---|
| Unit and contract | Deterministic assertions for domain rules, identity and workload boundaries, tool/event schemas, evidence utilities, and infrastructure inventory logic | No browser, model, data service, Entra redirect, or live Azure proof |
| Local deterministic users | Guarded `demo` fixtures for Dan, Ava, and Sam; compare personal portfolios, roles, sharing, denial, and exact state effects in a dedicated local Cosmos emulator | Synthetic actors are not tenant identities; local storage and networking are not Azure |
| Live local model | Deep Agents calls a real configured model; score only typed results, correlated events, and normalized state effects for the versioned seven-case set | Model selection is exercised, but Entra, managed workload identity, and deployed private paths are not |
| Playwright and responsive captures | A real browser drives the frontend/API at 1440, 1024, and 390 CSS px; DOM behavior, overflow, focus, state, and structured SSE evidence are asserted and six representative screenshots are reviewed | Captures support the asserted host journey; they are not broad visual, accessibility, or `/assistant` proof |
| Deployed real Entra | The identified immutable revision exercises tenant auth, actor-bound state, API-to-runtime workload identity, private Cosmos/Blob paths, and a typed live turn | Run-specific deployment evidence does not become proof for another revision, tenant actor, or journey |

One run may contribute evidence of more than one kind, but its claims stay limited to the environment
and checks it actually exercised. Broad production, load, disaster-recovery, multi-region, and
generalized security test programs are outside what this release requires.

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
`2026-07-19T14-35-51-193Z-779df115`. Its ignored local `results.json` records **34/34 checks**, no
failures, and no page errors at
`e641082f377d4a05f81d5489cfb54d390fddb575`. It reconciles three deterministic actors, sharing and
outsider isolation, viewer affordances, rejected validation with unchanged state, a typed agent
status update, a refresh of the current UI, wide/compact/narrow overflow, and narrow drawer focus and
hit-testing.

The same run contains six captures:

- `wide-dan-portfolio.png`;
- `wide-owner-shared-engagement.png`;
- `wide-agent-updated-engagement.png`;
- `compact-sam-viewer.png`;
- `narrow-dan-drawer-open.png`; and
- `narrow-dan-workspace.png`.

The run exercised the corrected assistant suggestions and the patched frontend dependency baseline.
Generated local bundles remain ignored runtime output rather than checked-in release artifacts; the
run record identifies the exact clean source revision that produced them.

### Live local model evaluation

[`tests/evals/mvp-cases.json`](../../tests/evals/mvp-cases.json) defines seven readable cases:
authorized list, grounded read, typed navigation, editor mutation, missing-reason non-commit,
outsider non-commit, and inert marker/success-like prose. The ignored local observation with run ID
`2026-07-19T14-36-18-536Z-0a399fbe` records 7/7 with Deep Agents at
`e641082f377d4a05f81d5489cfb54d390fddb575`. It is source-labelled local evidence rather than a
tracked portable artifact.

Each case requires one correlated `RUN_STARTED`, exactly one final terminal event, the expected typed
result where required, and the expected normalized state effect. The missing-reason and outsider
cases also allow a narrow, named alternative where the model safely does nothing: no tool result for
the former, or one `list`/`succeeded` result for the latter. Those alternatives prove the state didn't
change and nothing false happened — they don't prove the typed invalid/not-found branch actually ran.
The marker case requires zero tool results, no navigation, and unchanged state. Exact prose, token
timing, and hidden reasoning are deliberately left ungraded.

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
creation, a readback of the current Engagement state, and a Deep Agents turn. The turn
`List my engagements.` emitted typed `list_engagements` and successful `engagement.listed` evidence
before describing the same Cosmos-backed record. It also records a Blob-backed API round trip at the
final private topology: upload, list, byte-for-byte download, and delete. The live post-deployment
topology verifier passed for the three SHA-pinned, scale-to-zero apps, private Cosmos/Blob access,
DNS, exact inventory, managed-identity role containment within `csa-workbench-rg`, the moved Basic
registry, and the exact optional tenant-governance NSG pair.

These are real observations from this release, but the repository has no checked-in deployment
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

## What's required before release, and current status

| Requirement or journey | Minimum evidence and current boundary |
|---|---|
| R1 | Authority/link/terminology review against the release revision; documentation consistency is not inferred from runtime tests |
| R2 and S5 | Final-SHA deployment plus live topology verifier, health, identity, private data paths, exact inventory, scale, and latency record; raw transcript and cost export remain absent |
| R3–R5 and S1–S2 | Focused role/identity contracts, deterministic multi-user browser state reconciliation, and real-Entra confirmation; the second real tenant actor remains absent |
| R6 and S4 | Reviewed real-frontend Playwright journey and six captures at wide, compact, and 390 px; narrow standalone `/assistant` remains absent |
| R7 and S3 | Tool/schema/event contracts, adversarial inert-text cases, live local model results, and the final typed deployed turn; prose never supplies control or commit evidence |
| R8 | One record per requirement that names the revision, the kind of evidence, the fixture/configuration, what it checked against, the results, screenshots where applicable, and gaps |

## Open evidence gaps

- The clean-worktree browser and agent-eval bundles are ignored local evidence rather than portable
  artifacts committed to Git.
- No second real tenant actor proves deployed collaboration or isolation.
- No interactive Entra browser record proves redirect/return, rendered portfolio, collaboration, and
  sign-out.
- The standalone `/assistant` route is not narrow-screen complete or covered at 390 px.
- No deployment transcript, live topology output, Blob round-trip transcript, or Azure cost export is
  checked in; no numeric cost is claimed.
- Commands, agent turns, and deployment checks have no permanent, actor-authorized record proving they
  happened. Local traces and generated bundles are ephemeral evidence, not a replay or recovery
  guarantee.

Mark a missing kind of evidence **UNVERIFIED**. Do not replace it with source inspection, assistant
wording, an older revision's result, or a broader production test requirement outside R1–R8 and
S1–S5.
