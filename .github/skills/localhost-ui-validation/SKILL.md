---
name: localhost-ui-validation
description: Validate the current CSA Workbench MVP browser slice on an isolated local demo stack and reconcile browser output with structured evidence.
---

# Local MVP browser validation

Use this task-specific workflow only after reading the [local development runbook](../../../docs/development.md) and the [eval reference architecture](../../../docs/evals-reference-architecture.md). Those documents own the environment and evidence rules.

## Preconditions

1. Obtain deliberate human authorization: the browser runner performs a real model turn.
2. Start only an isolated `dev.py` stack with a unique run ID, dedicated loopback ports, and matching local Cosmos names. Do not stop or reuse another developer's stack.
3. Keep the worktree clean: the runner refuses a dirty source tree.
4. Use only loopback targets. Do not set `MVP_ALLOW_REMOTE=1` in this workflow.

## Current entry point

From a parent shell configured for the same isolated run, explicitly carry the paths that `dev.py` supplies only to child processes:

```bash
CSA_LOCAL_RUN_ID=<run-id> \
WORKSPACE="$PWD/.local-runs/<run-id>/workspace" \
ARTIFACTS_DIR="$PWD/.mvp-artifacts/<run-id>" \
IDENTITY_MODE=demo \
DEMO_PASSWORD='<local-only-secret>' \
COSMOS_ENDPOINT='http://localhost:8081' \
COSMOS_DATABASE='csa_workbench_<run-id>_local' \
COSMOS_CONTAINER='appstate_<run-id>_local' \
MVP_RESET_BEFORE_RUN=1 \
MVP_APP_URL=http://127.0.0.1:<frontend-port> \
MVP_API_URL=http://127.0.0.1:<api-port> \
npm run playwright:mvp
```

The reset run requires the demo identity variables and explicit local Cosmos emulator target above. Both Cosmos names must include the run ID and a `demo` or `local` marker; the endpoint must be loopback. The runner performs the current manual Engagement and structured assistant journey, writes ignored evidence under `evidence/mvp/`, and exits nonzero on a failed assertion.

## Report

- State the exact source revision, run ID, and isolated targets.
- Separate what the browser rendered from authoritative state and structured SSE evidence.
- Treat screenshots, tool labels, assistant prose, and a single pass field as supporting material—not proof by themselves.
- Do not broaden this task into a remote deployment, Waza model gate, or unattended Azure action.
