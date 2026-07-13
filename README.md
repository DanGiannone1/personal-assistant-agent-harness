# Personal Assistant — Agent Harness Accelerator (POC)

A proof-of-concept for embedding an AI assistant **inside** a real web app so it can actually
operate the app — navigate it, create/read/update/delete real records, retrieve over a document
library, and draft documents — rather than just chat beside it. Every action mutates the real
application state the UI renders, so the assistant can only claim work it actually did.

**The harness is the product. Personal Assistant — a small personal-productivity app — is disposable dressing**
chosen because it's self-evident to any audience and maps cleanly onto the four capabilities we
want to prove. (An earlier skin was a tax tracker; the domain was swapped because domain-correctness
rabbit holes are not the point.)

See the [documentation](docs/) for the product spec, architecture, and operations.

## What it is

- **Personal Assistant** — a mock productivity app: Home (today's agenda), To-Do, Calendar, Documents, Reminders,
  and an AI Workbench.
- **The assistant** — an embedded agent that navigates the app and acts on its data through tools.
- Split-screen UI: chat (a docked co-pilot, or the full-screen Workbench) + the live app. Agent
  actions visibly change the app.

### The four capabilities

1. **Navigation** — "take me to my calendar", "open the project brief".
2. **CRUD** — create/update/delete real tasks and calendar events that persist in app state.
3. **RAG** — semantic retrieval over a document library, with grounded, cited answers.
4. **Document ops** — draft and edit markdown documents in an artifact canvas.

(Plus scheduled emailed reminders and a persistent document Library — see [docs/spec.md](docs/spec.md).)

## Two interchangeable agent harnesses

A core goal of this project is to show the **agent runtime is swappable** behind the same streaming
protocol. The session container runs either harness, selected at launch by `AGENT_BACKEND`:

| `AGENT_BACKEND` | Harness | Status |
|---|---|---|
| `copilot` (default) | GitHub Copilot SDK (`session-container/agent.py`) | Shipped — full toolset |
| `deepagents` | LangGraph **Deep Agents** SDK (`session-container/agent_deepagents.py`) | Working POC — 14 core tools |

Both expose an identical `AgentSession` interface and emit the same event stream, so the
orchestrator, frontend, and app-state store are unchanged between them. Both pass the same **core**
end-to-end journeys (navigation, CRUD, documents, RAG); the Schedules and Library tools are
Copilot-only today (see [docs/harnesses.md](docs/harnesses.md) for the parity gap and the
[A/B findings](review/2026-06-24-deepagents-poc/FINDINGS.md)).

> **Direction (not built):** lift the tools into a shared **Personal Assistant MCP server** (Model Context
> Protocol) and load the markdown skills from one place, so every harness taps the same reusable
> substrate. See [docs/harnesses.md](docs/harnesses.md#the-reusable-substrate-direction--not-yet-built).

## Architecture

A Next.js **frontend** (:3000) streams from a FastAPI **orchestrator** (:8000) — a pure SSE proxy
that never runs the agent SDK — which proxies to an isolated **session container** (:8080) that runs
the agent against Azure OpenAI, Cosmos DB (app state), Azure AI Search (retrieval), and ADLS +
Content Understanding (upload conversion). Full detail, including the event flow and a turn
walkthrough, is in [docs/architecture.md](docs/architecture.md).

- **App state** lives in **Azure Cosmos DB** as a single AAD-only document; the app pane renders only
  from `GET /sessions/{id}/app/state`, so the verifiable-execution invariant holds.
- **Documents/files** live in a per-session workspace folder; promoted documents are indexed in the
  Azure AI Search **Library**.

## Run locally

```bash
cp .env.example .env                       # fill Azure OpenAI + Cosmos (+ optional Search/ADLS) values
az login                                   # Cosmos + Azure OpenAI auth (DefaultAzureCredential)
uv sync                                     # orchestrator deps
(cd session-container && uv sync)           # agent deps
(cd frontend && npm install)                # frontend deps
uv run dev.py                               # frontend :3000, orchestrator :8000, session container :8080

AGENT_BACKEND=deepagents uv run dev.py      # …or run the Deep Agents harness
```

Open <http://localhost:3000>. Full setup, configuration, and testing: [docs/development.md](docs/development.md).

## Documentation

| Doc | What it covers |
|---|---|
| [docs/use-cases.md](docs/use-cases.md) | The core use cases with concrete, runnable examples — start here |
| [docs/spec.md](docs/spec.md) | Product spec — capabilities, surfaces, data model, tools, skills, theme |
| [docs/architecture.md](docs/architecture.md) | System design — tiers, the AG-UI/SSE flow, a turn walkthrough, state, security, limitations |
| [docs/harnesses.md](docs/harnesses.md) | The two agent harnesses, the `AgentSession` seam, parity gap, reusable-substrate direction |
| [docs/retrieval.md](docs/retrieval.md) | RAG (Library + Azure AI Search) and the upload/conversion pipeline |
| [docs/development.md](docs/development.md) | Local setup, configuration, running, switching harnesses, testing |
| [docs/deployment.md](docs/deployment.md) | Azure Container Apps deployment, RBAC, and the deploy-time gotchas |

Portable, inactive-by-default developer governance and PPEL templates live in
[`developer-harness/`](developer-harness/README.md). They are not loaded by the
application or agent runtime unless deliberately adopted.

## Key files

The **orchestrator is the repo root** (there is no `orchestrator/` directory).

| Tier | Files |
|---|---|
| Orchestrator (repo root) | `app.py`, `session_manager.py`, `content_processing.py`, `scheduler.py`, `email_acs.py`, `api_auth.py` |
| Session container | `session-container/server.py`, `agent.py` (Copilot), `agent_deepagents.py` (Deep Agents), `appdb.py`, `library.py`, `skills/` |
| Frontend | `frontend/src/hooks/useAgentSession.ts`, `components/workbench/WorkbenchApp.tsx`, `components/AssistantWorkspace.tsx` |
