# CSA Workbench — Solution Architect Engagement Workspace

Run the engagement. Shape the solution. Keep the record.

The agent-powered engagement workspace for solution architects.

CSA Workbench gives solution architects one durable place to run customer engagements: shared status and its
reason, tasks, people, conventions, activity, and artifacts. An embedded assistant can navigate and
operate the same records the UI renders, so a claim cannot outrun the state that was actually read or
changed.

The application is the product; chat is one control surface. The repository also serves as a
reference implementation for modern agent-harness patterns—trusted context, replaceable runtimes,
structured outcomes, durable state outside compute, and behavior traces—without depending on IDA or
becoming a generic agent platform.

## Start here

- [Authoritative design](docs/design.md) — product promise, scope, domain, system/trust/state
  boundaries, target architecture, and current-versus-target reconciliation.
- [v1 requirements](docs/requirements.md) — release requirements, acceptance scenarios, and
  verification profiles.
- [Development](docs/development.md) — current local prerequisites, configuration, and commands.

The design is the intended architecture, not a claim that every target behavior is implemented.
Runtime behavior at the current integrated baseline remains **UNVERIFIED** unless current evidence is
linked from a work item or review record.

## Product shape

- **Engagement portfolio** — triage Green/Yellow/Red work and understand why it needs attention.
- **Shared Engagement workspace** — role-gated tasks, conventions, activity, and durable artifacts.
- **Private workbench** — resumable conversations and uploads, explicitly unsaved generated drafts,
  a small Personal Library for intentionally kept documents, and minimal user preferences.
- **Embedded assistant** — the same conversation in a dock or full artifact workbench.
- **Truthful operations** — one backend path for manual and agent actions, structured outcomes, and
  authoritative refresh.
- **Legible behavior** — “What I used,” tool outcomes, and turn receipts without exposing hidden
  reasoning.
- **Responsive professional UX** — wide, compact, and narrow web layouts with WCAG 2.2 AA intent.

## Architecture at a glance

```text
Next.js web app
    │ HTTPS + AG-UI/SSE
    ▼
FastAPI orchestrator
    │ authentication, application APIs, session/turn coordination
    ▼
Agent session runtime
    │ Deep Agents primary / Copilot secondary
    ▼
Shared application services ── Cosmos (records/receipts)
                            └── Blob (uploads/artifacts)
                            └── optional scoped Search
```

The frontend, orchestrator, and runtime are separate deployment boundaries. Product authorization,
validation, mutation, and structured outcomes belong to one application layer used by REST and agent
tool adapters. Framework state and runtime files are cache/scratch, never the only copy of work worth
keeping.

## Run the current implementation locally

Prerequisites: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), Node.js/npm, an Azure OpenAI model
deployment, and Cosmos DB (the local design uses the Cosmos emulator; an AAD-accessible development
account also works where network policy permits).

```bash
cp .env.example .env
# Set AZURE_ENDPOINT, AZURE_DEPLOYMENT, COSMOS_ENDPOINT,
# COSMOS_DATABASE, and COSMOS_CONTAINER. Set COSMOS_KEY only for the emulator.

az login
uv sync
(cd session-container && uv sync)
(cd frontend && npm install)
uv run dev.py
```

Open <http://localhost:3000>. The development launcher starts:

- frontend at `:3000`;
- orchestrator at `:8000`; and
- session runtime at `:8080`.

Deep Agents is the current default. To exercise the secondary harness:

```bash
AGENT_BACKEND=copilot uv run dev.py
```

Optional document conversion, Search, Entra, and tracing configuration is described in
[development.md](docs/development.md). Search is not required for navigation, CRUD, direct document
work, or drafting.

## Documentation map

### Authority

| Document | Owns |
|---|---|
| [Design](docs/design.md) | High-level product and system architecture; capability boundaries |
| [Requirements](docs/requirements.md) | v1 release bar and acceptance criteria |

### Capability designs

| Capability | Detailed authority |
|---|---|
| [UI/UX](docs/capabilities/ui-ux.md) | Information architecture, interaction, responsive behavior, accessibility |
| [Context](docs/capabilities/context.md) | Per-turn context, projections, precedence, and inspector |
| [Navigation](docs/capabilities/navigation.md) | Destination catalog, deterministic resolution, and route effects |
| [CRUD](docs/capabilities/crud.md) | Commands, validation, outcomes, confirmation, idempotency, and concurrency |
| [Documents and retrieval](docs/capabilities/documents-retrieval.md) | Uploads, drafts, artifacts, retrieval, and citations |
| [Session and state](docs/capabilities/session-state.md) | Conversation durability, rehydration, and compute boundaries |
| [Agent harness](docs/capabilities/agent-harness.md) | Harness seam, tools, prompts/skills, events, cancellation, and traces |
| [Identity and access](docs/capabilities/identity-access.md) | Actors, sign-in, authorization policy and roles, privacy, and service identity |
| [Infrastructure](docs/capabilities/infrastructure.md) | Local/Azure topology, cost boundary, observability, and degraded modes |
| [Testing and evals](docs/capabilities/testing-evals.md) | Behavioral evidence, test layers, eval datasets, and release profiles |

### Runbooks

| Document | Purpose |
|---|---|
| [Development](docs/development.md) | Operate and verify the current repository locally |
| [Deployment](docs/deployment.md) | Current deployment status, target profile, and safe deployment direction |

The root README is the repository and documentation front door. Capability documents are
subordinate to the high-level design and own only their named detail. Runbooks describe mechanics;
they do not override product or architecture decisions.

## Repository layout

The orchestrator is at the repository root; there is no separate `orchestrator/` directory.

| Area | Important paths |
|---|---|
| Orchestrator and application API | `app.py`, `session_manager.py`, `api_auth.py`, `artifact_store.py` |
| Session runtime and harnesses | `session-container/server.py`, `agent_deepagents.py`, `agent.py`, `appdb.py` |
| Frontend | `frontend/src/components/`, `frontend/src/hooks/useAgentSession.ts`, `frontend/src/lib/` |
| Infrastructure | `infra/`, `.github/workflows/` |
| Behavioral probes | `scripts/`, `tests/` where present |

## Reference relationship to IDA

Local IDA material is comparative input only. It creates no CSA Workbench requirement and is not needed to
build, run, or understand the application. The useful bridge is architectural: an IDA team may reuse
CSA Workbench's context, tool, state, outcome, trace, and harness patterns through a future authenticated
adapter without receiving a bypass around the product's identity or authorization rules.
