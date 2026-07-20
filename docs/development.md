# Local development runbook

> **Purpose:** Run and verify the current checkout locally. Product and architecture authority
> remains in the [authoritative design](design.md).

## Local shape

The launcher preserves the three application boundaries:

```text
browser -> frontend :3000 -> API :8000 -> runtime :8080 -> Azure OpenAI
                              |             |
                              `------ Cosmos emulator supplied separately
API -> local artifact directory
```

Local development uses deterministic `demo` identity. It does not emulate Entra workload identity,
private endpoints, private DNS, Container Apps scaling, or the deployed network boundary.

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20.9+ and npm
- an Azure OpenAI endpoint/deployment reachable with the developer's Azure identity
- a separately supplied Cosmos emulator

The repository does not start or configure a Cosmos emulator. Its Compose file starts only the
three application services. Azurite is also not wired into the local profile.

## Configure

```bash
cp .env.example .env
az login
uv sync
(cd session-container && uv sync)
(cd frontend && npm ci)
```

Set these values in `.env` for the local environment:

- `IDENTITY_MODE=demo`;
- a nonempty local/test `DEMO_PASSWORD` that is never committed or exposed in browser config;
- `AZURE_ENDPOINT` and `AZURE_DEPLOYMENT`;
- the emulator `COSMOS_ENDPOINT`, `COSMOS_DATABASE`, `COSMOS_CONTAINER`, and emulator-only
  `COSMOS_KEY`; and
- optionally `ARTIFACTS_DIR` for local durable Engagement artifact bytes.

The application requires Cosmos and fails visibly rather than falling back to a local JSON store.
Use database/container names containing `demo` or `local` when running the guarded fixture reset.

Search and document conversion are optional legacy capabilities. Leave them unconfigured for the
MVP profile. Search is not required for navigation, Engagement work, or direct artifact access.

## Start and stop

```bash
uv run dev.py
```

Open <http://localhost:3000>. `dev.py` validates demo mode, points the API at the local runtime,
clears ephemeral workspace/traces, and starts all three processes. Stop the launcher with Ctrl-C;
restart it instead of assuming one independently started process has the same configuration.

Deep Agents is the default. Copilot is a local, non-release-blocking portability check:

```bash
AGENT_BACKEND=copilot uv run dev.py
```

Agent sessions, chat, uploads, generated files, and local traces are ephemeral. Restarting the API
or runtime may require a new session. Cosmos-backed Engagements and locally stored Engagement
artifacts remain separate from that session lifecycle.

## Safe checks

The focused deterministic checks do not require a running browser stack:

```bash
PYTHONPATH=$PWD:$PWD/session-container uv run --project session-container --with pytest \
  pytest -q tests/test_reset_demo_state.py tests/test_identity_modes.py \
  tests/test_engagement_core.py tests/test_structured_control.py \
  tests/test_infra_entra_contract.py tests/test_release_boundaries.py \
  tests/test_skill_runtime.py
npm run test:mvp-evidence
(cd frontend && npm run test:contract && npm run lint && npm run build)
```

The Waza readiness check installs the repository-pinned v0.38.3 binary under the ignored local
evidence tree, verifies its release checksum, and validates the product skill and eval schemas:

```bash
npm run eval:waza:check
```

The on-demand Waza gate makes external Copilot/model calls and may consume premium requests. It is
not part of the deterministic suite:

```bash
npm run eval:waza:gate
```

Live synthetic model/browser evidence requires the emulator and all three services to be running,
an explicit guarded reset, loopback targets, and a clean worktree:

```bash
export IDENTITY_MODE=demo
export DEMO_PASSWORD='local-test-secret'
export COSMOS_ENDPOINT='http://localhost:8081'
export COSMOS_DATABASE='csa_workbench_demo'
export COSMOS_CONTAINER='appstate_demo'
export COSMOS_KEY='your-emulator-key'
export ARTIFACTS_DIR='.mvp-artifacts'

CONFIRM_DEMO_RESET=YES uv run python scripts/reset_demo_state.py
MVP_RESET_BEFORE_RUN=1 npm run eval:mvp
MVP_RESET_BEFORE_RUN=1 npm run playwright:mvp
```

The reset is destructive only to the explicitly guarded local fixture. The runners refuse a dirty
source worktree and do not start or stop services. The agent runner resets before each atomic case,
then resets once before driving the versioned three-turn workflow through one session. Review its
state/event/raw-tool results and the meeting-brief transcript; a runner's `pass` field or assistant
wording is not an oracle by itself. See [Testing and evals](capabilities/testing-evals.md) for the
complete evidence contract and the [Evals MVP reference architecture](evals-reference-architecture.md)
for the customer-demo sequence.
