# Local development

This is the runbook for the **current checkout**, not a promise that it meets the
[target design](design.md). Local runtime behavior is **UNVERIFIED** until you run
the relevant journey and record its UI, state, and trace evidence. The target local
topology and evidence bar live in [Infrastructure](capabilities/infrastructure.md)
and [Testing and evals](capabilities/testing-evals.md).

## Before you start

Install Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20.9+ with npm, and
Docker only if you will supply a Cosmos emulator. You also need an Azure OpenAI
endpoint and deployment.

The current application requires Cosmos for app state; it fails rather than falling
back to a file. A laptop should use a Cosmos emulator and its emulator key
(`COSMOS_KEY`), not a private Azure Cosmos account. **Gap:** this repository does
not currently start or configure a Cosmos emulator (the checked-in Compose file
starts only the three application services). Obtain and configure that emulator
separately before expecting the stack to start. Do not infer local/Azure parity from
the code or this page.

## Configure and start

```bash
cp .env.example .env
# Keep IDENTITY_MODE=demo locally and set DEMO_PASSWORD to a local/test secret.
# Do not commit the secret or put it in browser-facing configuration.
az login
uv sync
(cd session-container && uv sync)
(cd frontend && npm install)
uv run dev.py
```

Set `AZURE_ENDPOINT`, `AZURE_DEPLOYMENT`, `COSMOS_ENDPOINT`, the appropriate Cosmos settings,
and a local/test `DEMO_PASSWORD` in `.env` first. Leave `IDENTITY_MODE=demo` for this local launcher.
`az login` supplies the developer identity used by Azure OpenAI and any AAD-authenticated service.
`dev.py` requires `.env`, points the orchestrator to the local runtime, clears `workspace/` and local
traces, then starts:

| Service | Address |
|---|---|
| Next.js frontend | <http://localhost:3000> |
| FastAPI orchestrator | <http://localhost:8000> |
| Session runtime | <http://localhost:8080> |

Stop the launcher with Ctrl-C. It owns all three child processes; restart the
launcher instead of assuming an individually started service has the same local
environment.

## Harness selection

Deep Agents is the current code default. Select Copilot only for the local,
non-release-blocking portability check:

```bash
uv run dev.py
AGENT_BACKEND=copilot uv run dev.py
```

The runtime recognizes `deepagents` and otherwise selects the Copilot adapter; use
those two documented values. The startup log identifies the selected backend.

## Optional current configuration

Search is optional and off when its endpoint/key are absent. Its present adapter
uses an admin key and is not the target baseline; an unavailable search capability
must remain visibly unavailable rather than being treated as grounded retrieval.
ADLS/Content Understanding configuration is also optional in the current code;
without it, conversion is disabled. Authentication and deployment-only settings are
annotated in [`.env.example`](../.env.example).

## Verify the current checkout

The full evidence contract and result interpretation live in [Testing and
evals](capabilities/testing-evals.md). With an independently configured local
Cosmos emulator and `uv run dev.py` already running, use its guarded commands:

```bash
PYTHONPATH=$PWD:$PWD/session-container uv run --project session-container --with pytest pytest -q tests/test_reset_demo_state.py tests/test_identity_modes.py tests/test_engagement_core.py tests/test_structured_control.py
npm run test:mvp-evidence
(cd frontend && npm run lint && npm run build)

# The reset also requires a demo/local Cosmos database+container and this dedicated
# artifact directory (see Testing and evals for the complete local export block).
ARTIFACTS_DIR=.mvp-artifacts CONFIRM_DEMO_RESET=YES uv run python scripts/reset_demo_state.py
MVP_RESET_BEFORE_RUN=1 npm run eval:mvp
MVP_RESET_BEFORE_RUN=1 npm run playwright:mvp
```

The reset and live runners require explicit demo/local-emulator guards; see the
testing document before using them. They do not start or stop user services.
Review the generated `evidence/mvp/local-synthetic/` bundle alongside the
authoritative state and structured events. Until a current bundle is reviewed,
live browser, model, Entra, and deployed behavior remains **UNVERIFIED**.
