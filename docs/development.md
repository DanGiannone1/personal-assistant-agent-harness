# Local Development

## Prerequisites

- **Python 3.12+** with [`uv`](https://docs.astral.sh/uv/)
- **Node 20+** with `npm` (Next.js 16 requires Node ≥ 20.9)
- **Azure CLI** signed in (`az login`) — app state lives in Cosmos DB (AAD-only) and the agent
  calls Azure OpenAI; both authenticate via `DefaultAzureCredential` locally
- **AAD data-plane roles on your signed-in principal** — `az login` alone is not enough. Without
  these you'll boot but get `403 Forbidden` on the first request:
  - **Cosmos DB Built-in Data Contributor** on the Cosmos account (required — app state)
  - **Cognitive Services User** on the Azure OpenAI/Foundry resource (the agent)
  - For optional RAG: today the Library uses the Search **admin key** (`AZURE_SEARCH_KEY`); a
    managed-identity path is a known follow-up (see [deployment.md](deployment.md))
  - Also ensure the Cosmos account's **network firewall allows your IP** (`publicNetworkAccess`
    enabled, or your IP in the allow-list) — a blocked IP surfaces as the same `403`
- A `.env` file at the repo root (`cp .env.example .env`)

The repo is **two independent `uv` projects**: the root (orchestrator) and `session-container/`,
each with its own `pyproject.toml` + `uv.lock`. Add orchestrator deps with `uv add` from the root;
add agent deps with `uv add` from `session-container/`.

## Setup

```bash
cp .env.example .env          # fill in Azure OpenAI + Cosmos (+ optional Search/ADLS) values
az login                      # Cosmos + Azure OpenAI auth
uv sync                       # root (orchestrator) deps
cd session-container && uv sync && cd ..   # agent deps
cd frontend && npm install && cd ..        # frontend deps
```

## Run the stack

```bash
uv run dev.py                 # starts all three services
```

| Service | Port | Command (run by `dev.py`) |
|---|---|---|
| Frontend (Next.js) | 3000 | `npm run dev` |
| Orchestrator (FastAPI) | 8000 | `uv run uvicorn app:app` |
| Session container (FastAPI) | 8080 | `uv run uvicorn server:app` |

Open <http://localhost:3000>.

`dev.py` owns all three child processes and sets the environment they need (`WORKSPACE`,
`POOL_MANAGEMENT_ENDPOINT=http://localhost:8080`, the `LOG_*` trace vars) and loads `.env`.
(`POOL_MANAGEMENT_ENDPOINT` points the orchestrator at the single local session container as if it
were the production ACA session pool.) To restart, stop `dev.py` and relaunch it — don't run the
services by hand without those vars, or uploads and tracing will misbehave.

### Selecting the agent harness

The session container runs either harness, chosen at launch by `AGENT_BACKEND` (default `copilot`):

```bash
uv run dev.py                          # GitHub Copilot SDK (default)
AGENT_BACKEND=deepagents uv run dev.py  # LangGraph Deep Agents
```

See [harnesses.md](harnesses.md). The startup log prints `Agent backend: <name>` so the active
harness is unambiguous.

## Configuration

**Minimum to boot:** `AZURE_ENDPOINT`, `AZURE_DEPLOYMENT`, and the `COSMOS_*` vars — app state is
required and fails loud if Cosmos is unreachable. Search and ADLS are optional and unlock RAG and
upload-conversion respectively. Core variables (see [`.env.example`](../.env.example) for the
complete, annotated list):

| Var | Purpose |
|---|---|
| `AZURE_ENDPOINT` | Azure OpenAI / Foundry resource endpoint |
| `AZURE_DEPLOYMENT` | Model deployment name (e.g. `gpt-4.1`) |
| `AZURE_API_VERSION` | Azure OpenAI API version (default `2024-10-21`) |
| `COSMOS_ENDPOINT` / `COSMOS_DATABASE` / `COSMOS_CONTAINER` | App-state store (AAD-only) |
| `AZURE_SEARCH_ENDPOINT` / `AZURE_SEARCH_KEY` | Document retrieval — see [retrieval.md](retrieval.md) |
| `ADLS_ACCOUNT_NAME` / `ADLS_FILESYSTEM` | Upload + conversion pipeline — see [retrieval.md](retrieval.md#document-upload-and-conversion) |
| `AGENT_BACKEND` | `copilot` (default) or `deepagents` |
| `CHAT_TIMEOUT_SECONDS` | Per-turn agent timeout (default 300) |
| `LOG_TRACE` / `LOG_RAW_SDK_EVENTS` / `LOG_TRACE_DIR` | Local trace logging (below) |

Authentication (`API_AUTH_REQUIRED`, `ENTRA_*`) and the deployment-only variables are documented in
[`.env.example`](../.env.example) and [deployment.md](deployment.md).

## Tracing

With `LOG_TRACE=true` and `LOG_RAW_SDK_EVENTS=true` (both set by `dev.py`), each run writes:

- `logs/trace.jsonl` — structured cross-tier trace (HTTP requests, tool starts/ends with outcomes,
  turn boundaries), truncated per session for easy isolation.
- `logs/sdk-events/<session_id>.jsonl` — the per-session raw agent event stream.

These are the source of truth for reconciling what the UI showed against what the agent actually
did.

## Testing

The only meaningful test is **Playwright driving the real frontend as a user**, with screenshots
examined and reconciled against the traces above — not API-only checks or "it compiles."

The core journey runner walks the core capabilities (navigation, task/event CRUD, document draft,
RAG), screenshots each step, and reconciles the rendered UI against `/app/state`:

```bash
node scripts/deepagents_poc.mjs      # → screenshots/deepagents-poc/ + state dumps
```

It is named for its origin (the Deep Agents POC) but is harness-agnostic — it runs against whichever
harness the stack was launched with, so the same journey validates both. It does **not** cover the
Copilot-only Schedules/Library tools; `scripts/` holds additional targeted journeys (e.g.
`flow_crud_e2e.mjs`, `flow_reminders_e2e.mjs`) for those.

Frontend checks:

```bash
cd frontend && npm run lint     # eslint
cd frontend && npm run build    # production build
```
