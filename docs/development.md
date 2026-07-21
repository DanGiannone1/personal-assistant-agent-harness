# Local development runbook

> **Purpose:** Run the current checkout locally. This runbook is not evidence of a live Azure, Entra, browser, or model result.

## Prerequisites and setup

Install Python 3.12+, `uv`, Node.js/npm, Azure CLI with Bicep support, an Azure OpenAI endpoint/deployment reachable by the developer, and a user-provided Cosmos emulator. The repository does not start or configure the external Cosmos emulator. Sign in with `az login` if the configured local model path relies on Azure CLI credentials.

```bash
cp .env.example .env
uv sync
(cd session-container && uv sync)
(cd frontend && npm ci)
```

Configure local demo identity, the Azure OpenAI endpoint/deployment, and Cosmos emulator values in `.env`. Never commit a real secret. Read the current `.env.example` and source for the exact variables.

## Isolated local run

`dev.py` runs a frontend, API, and session runtime. For an isolated stack, select a conservative run ID and three unused, distinct loopback ports. This illustrative configuration uses `demo1`, `18080`, `18000`, and `13000`:

```bash
export CSA_LOCAL_RUN_ID=demo1
export CSA_RUNTIME_PORT=18080
export CSA_API_PORT=18000
export CSA_FRONTEND_PORT=13000
export IDENTITY_MODE=demo
export DEMO_PASSWORD='local-only-secret'
export COSMOS_ENDPOINT='http://localhost:8081'
export COSMOS_DATABASE='csa_workbench_demo1_local'
export COSMOS_CONTAINER='appstate_demo1_local'
uv run dev.py
```

For an isolated run, both Cosmos names must contain the run ID and either `demo` or `local`; the endpoint must be loopback. `dev.py` uses `.local-runs/demo1/` for the run workspace and logs, `.mvp-artifacts/demo1/` for local durable Engagement artifact bytes, and `frontend/.next-local-runs/demo1/` for the frontend build output. That separate frontend output lets the run coexist with another developer's normal Next dev server. The launcher stops only the processes it launched. Session files are ephemeral and session uploads accept Markdown (`.md`) only; they are not durable Engagement artifacts.

The launcher passes child environment variables only to its three child processes. Shell commands run afterward do not inherit those calculated values. Any parent-shell reset, live-eval, or browser command must explicitly export matching `CSA_LOCAL_RUN_ID`, `WORKSPACE=.local-runs/<id>/workspace`, and `ARTIFACTS_DIR=.mvp-artifacts/<id>` (along with matching Cosmos settings).

## Deterministic verification

```bash
npm run verify
```

`npm run verify` performs repository-local locks, focused tests, deterministic MVP evidence checks, Waza readiness validation, frontend contract/lint/build checks, shell syntax, Bicep compilation, and whitespace checking. It does not run an Azure deployment, a browser journey, or a model gate.

`npm run test:mvp-evidence` is a deterministic source/oracle check. `npm run eval:waza:check` downloads or verifies a checksum-pinned Waza binary under ignored local evidence output, then validates the one product skill and evaluation schema; it is a readiness check, not product behavior proof.

`npm run eval:waza:gate` and `npm run eval:waza:advisory` make external Copilot/model calls. Live MVP evaluation also calls the configured model; it and Playwright require the user-provided emulator and running local services. Run them only with deliberate human authorization; review the resulting state, structured events, and demo output with a human rather than treating an assistant response or pass label as sufficient proof.

## Live MVP evaluation scope

The default `npm run eval:mvp` run uses `MVP_EVAL_SCOPE=all`: it executes both the atomic cases and the versioned three-turn workflow. Use it for the full local readiness evidence.

After starting the isolated `demo1` stack above, run a live evaluator from a separate parent shell with the matching isolation values. The launcher passes its calculated values only to child processes, so the evaluator needs these explicit exports:

```bash
export CSA_LOCAL_RUN_ID=demo1
export WORKSPACE=.local-runs/demo1/workspace
export ARTIFACTS_DIR=.mvp-artifacts/demo1
export IDENTITY_MODE=demo
export DEMO_PASSWORD='local-only-secret'
export COSMOS_ENDPOINT='http://localhost:8081'
export COSMOS_DATABASE='csa_workbench_demo1_local'
export COSMOS_CONTAINER='appstate_demo1_local'
export MVP_API_URL='http://localhost:18000'
export MVP_RAW_TRACE_ROOT='.local-runs/demo1/logs/sdk-events'
export MVP_RESET_BEFORE_RUN=1
MVP_EVAL_SCOPE=workflow npm run eval:mvp
```

`MVP_EVAL_SCOPE` accepts only `all` (the default), `atomic`, or `workflow`; an invalid value fails before the evaluator makes live calls. `workflow` performs one guarded fixture reset, one session, and the three versioned workflow turns only. It is useful after a transient provider limit, but it is subset evidence and does not replace `npm run eval:mvp` full readiness.
