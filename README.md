# CSA Workbench — Solution Architect Engagement Workspace

Run the engagement. Shape the solution. Keep the record.

The agent-powered engagement workspace for solution architects.

CSA Workbench gives solution architects a personal place to organize their work and a shared place
to run customer engagements. An embedded assistant can navigate and operate the same records the UI
renders, so a claim cannot outrun the state that was actually read or changed.

The application is the product; chat is one control surface. The repository also serves as a
reference implementation for modern agent-harness patterns—trusted actor binding, replaceable
runtimes, structured outcomes, durable product state outside compute, and behavioral
evidence—without depending on IDA or becoming a generic agent platform.

## Start here

- [Authoritative design](docs/design.md) — product promise, scope, domain, system/trust/state
  boundaries, implemented architecture, verified evidence, and explicit gaps.
- [v1 requirements](docs/requirements.md) — release requirements, acceptance journeys, and
  verification profiles.
- [Development](docs/development.md) — current local prerequisites, configuration, and commands.

The design distinguishes implemented behavior, verified evidence, and intentionally deferred
patterns. The current application revision is deployed and behaviorally verified as recorded there;
remaining evidence gaps are named rather than hidden behind a generic target-state disclaimer.

## Product shape

- **Personal CSA space** — see the Engagements that belong to the signed-in user.
- **Shared Engagement workspace** — create, open, edit, and share role-gated Engagement records.
- **Embedded assistant** — the same conversation in a dock or full artifact workbench.
- **Truthful operations** — shared rules for manual and agent actions, structured outcomes, and
  authoritative refresh.
- **Responsive professional UX** — wide, compact, and narrow web layouts with WCAG 2.2 AA intent.

## Architecture at a glance

```text
Next.js web app
    │ HTTPS + AG-UI/SSE
    ▼
FastAPI orchestrator
    │ authentication, application APIs, session/turn coordination
    │ Entra workload identity
    ▼
Internal agent session runtime
    │ Deep Agents deployed / Copilot local portability check
    ▼
Shared Engagement core ── Cosmos (actors and Engagements)
                       └── Blob (durable Engagement artifacts)
```

The frontend, orchestrator, and runtime are separate deployment boundaries. The six basic
Engagement operations—create, list, get, update, set status, and share/change membership—use one
application core behind REST and agent-tool adapters. Member removal, tasks, conventions, and
artifacts remain manual application paths. Agent sessions, chat history, uploads, and local traces
are ephemeral in the MVP; durable Engagement records and artifacts remain outside compute.

## Run the current implementation locally

Prerequisites: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), Node.js/npm, an Azure OpenAI model
deployment, and Cosmos DB (the local design uses the Cosmos emulator; an AAD-accessible development
account also works where network policy permits).

```bash
cp .env.example .env
# Set AZURE_ENDPOINT, AZURE_DEPLOYMENT, COSMOS_ENDPOINT,
# COSMOS_DATABASE, and COSMOS_CONTAINER. Set COSMOS_KEY only for the emulator.
# Keep IDENTITY_MODE=demo for local development and set DEMO_PASSWORD to a
# local/test secret. Do not put that password in source control.

az login
uv sync
(cd session-container && uv sync)
(cd frontend && npm ci)
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

Local storage and optional-service boundaries are described in
[development.md](docs/development.md). Search and document conversion remain off in the MVP profile
and are not required for Engagement work or direct artifact access.

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
| [Context](docs/capabilities/context.md) | Prompt hints, live grounding, trust boundaries, precedence, and inspector |
| [Navigation](docs/capabilities/navigation.md) | Typed navigation tools, destination validation, and route effects |
| [CRUD](docs/capabilities/crud.md) | Engagement commands, roles, validation, outcomes, and current persistence semantics |
| [Documents and retrieval](docs/capabilities/documents-retrieval.md) | Durable Engagement artifacts, ephemeral session files, and optional retrieval boundaries |
| [Session and state](docs/capabilities/session-state.md) | Ephemeral conversations, durable product state, and compute boundaries |
| [Agent harness](docs/capabilities/agent-harness.md) | Harness seam, typed tools/events, workload binding, cancellation, and ephemeral traces |
| [Identity and access](docs/capabilities/identity-access.md) | Actors, sign-in, authorization policy and roles, privacy, and service identity |
| [Infrastructure](docs/capabilities/infrastructure.md) | Verified local/Azure topology, private data paths, deployment, and cost boundary |
| [Testing and evals](docs/capabilities/testing-evals.md) | Behavioral evidence, test layers, eval datasets, and release profiles |

### Runbooks

| Document | Purpose |
|---|---|
| [Development](docs/development.md) | Operate and verify the current repository locally |
| [Deployment](docs/deployment.md) | Guarded dry run, apply workflow, verified profile, and post-deployment checks |

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
