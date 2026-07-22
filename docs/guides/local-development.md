# Local development

## Prerequisites

Install:

- Python 3.12 or later
- `uv`
- Node.js and npm
- Azure CLI with Bicep support
- an Azure OpenAI endpoint and model deployment reachable by the developer
- a separately provided Cosmos DB emulator

The repository does not install or configure the Cosmos emulator.

## Install dependencies

```bash
cp .env.example .env
npm ci
uv sync
(cd session-container && uv sync)
(cd frontend && npm ci)
```

Set `IDENTITY_MODE=demo`, a local `DEMO_PASSWORD`, the Azure OpenAI values, and Cosmos emulator values
in `.env`. Do not commit real secrets. Read `.env.example` for the current variable names.

## Start the application

```bash
uv run dev.py
```

The launcher starts the frontend, API, and assistant runtime as separate processes.

## Run an isolated copy

Use a short run ID, three unused loopback ports, and Cosmos names dedicated to that run. For example:

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

Both Cosmos names must contain the run ID and either `demo` or `local`. The endpoint must use
loopback. The launcher creates:

- `.local-runs/demo1/` for runtime files and logs;
- `.mvp-artifacts/demo1/` for local Engagement artifact files; and
- `frontend/.next-local-runs/demo1/` for the frontend build.

The launcher stops only processes that it started.

## Run repository checks

```bash
npm run verify
```

This command checks dependency locks, focused Python tests, assistant contracts, frontend contracts,
lint, frontend build, shell syntax, Bicep compilation, and whitespace. CI uses `npm run verify:ci`,
which skips the local Bicep compilation step.

## Run the assistant evaluation

This command calls the configured model and requires a running isolated application and the user's
approval:

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
npm run eval:mvp
```

`MVP_EVAL_SCOPE` may be `all`, `atomic`, or `workflow`; the default is `all`.

## Run the browser journey

This command calls the configured model and changes the isolated demo data. Run it only with the
user's approval after the isolated application is ready:

```bash
export CSA_LOCAL_RUN_ID=demo1
export WORKSPACE=.local-runs/demo1/workspace
export ARTIFACTS_DIR=.mvp-artifacts/demo1
export IDENTITY_MODE=demo
export DEMO_PASSWORD='local-only-secret'
export COSMOS_ENDPOINT='http://localhost:8081'
export COSMOS_DATABASE='csa_workbench_demo1_local'
export COSMOS_CONTAINER='appstate_demo1_local'
export MVP_APP_URL='http://localhost:13000'
export MVP_API_URL='http://localhost:18000'
export MVP_RAW_TRACE_ROOT='.local-runs/demo1/logs/sdk-events'
export MVP_RESET_BEFORE_RUN=1
npm run playwright:mvp
```

The environment variables in the parent shell must match the values used to start `dev.py`.

## Optional Reminder email

Set `ACS_EMAIL_ENDPOINT` and `ACS_SENDER_ADDRESS` to use Azure Communication Services with the
developer's Azure credentials. Demo users send only to `REMINDER_DEMO_EMAIL`. Without these values,
Reminders continue to work in the application without sending email.
