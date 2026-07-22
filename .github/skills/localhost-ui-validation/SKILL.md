---
name: localhost-ui-validation
description: Check the current CSA Workbench browser journey on an isolated local demo instance.
---

# Local browser check

Read the [local development guide](../../../docs/guides/local-development.md) and
[demo guide](../../../docs/guides/demo.md) first.

## Preconditions

1. Obtain the user's approval because the browser runner performs a real model turn.
2. Start an isolated `dev.py` instance with a unique run ID, dedicated loopback ports, and matching
   local Cosmos names.
3. Do not stop or reuse another developer's processes.
4. Keep the worktree clean because the runner rejects a dirty checkout.
5. Use loopback addresses only. Do not set `MVP_ALLOW_REMOTE=1`.

## Command

From a parent shell configured for the same isolated run:

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

Both Cosmos names must contain the run ID and either `demo` or `local`. The endpoint must use
loopback.

## Report

- State the source revision, run ID, and isolated addresses.
- Describe what the browser showed, what application state contained, and which structured assistant
  events were received.
- Do not expand this task into remote deployment, another model check, or an Azure change.
