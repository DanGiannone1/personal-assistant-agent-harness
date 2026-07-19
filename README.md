# CSA Workbench — Solution Architect Engagement Workspace

Run the engagement. Shape the solution. Keep the record.

The agent-powered engagement workspace for solution architects.

CSA Workbench gives solution architects a personal place to organize their work and a shared place
to run customer engagements. An embedded assistant can navigate and operate the same records the UI
renders, so a claim cannot outrun the state that was actually read or changed.

The application is the product; chat is one way to use it. The repository also works as an
example of solid agent-system design: every action is tied to a verified user, the AI runtime can
be swapped out, results are structured data rather than prose, durable data lives in the database
rather than in the running services, and behavior is proven with real tests — without depending on
IDA or becoming a generic agent platform.

## Start here

- [Design](docs/design.md) — what the product is, what it includes and excludes, how the system is
  built, what has been verified, and what hasn't.
- [v1 requirements](docs/requirements.md) — what must be true to ship, the user journeys that prove
  it, and how each is verified.
- [Development](docs/development.md) — local prerequisites, configuration, and commands.

The design separates what is built, what is proven, and what is deliberately postponed. The
deployed version has been verified as recorded there, and the remaining gaps are listed by name
instead of being hidden behind a vague disclaimer.

## Product shape

- **Personal CSA space** — see the Engagements that belong to the signed-in user.
- **Shared Engagement workspace** — create, open, edit, and share role-gated Engagement records.
- **Embedded assistant** — the same conversation in a dock or full artifact workbench.
- **Truthful operations** — the same rules apply whether a person or the assistant makes a change,
  every result is structured data, and the UI re-reads the confirmed state afterward instead of
  trusting what was said.
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
do not survive a restart in the MVP; Engagement records and artifacts do, because they live in
Cosmos and Blob rather than in the running services.

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

### Core documents

| Document | Covers |
|---|---|
| [Design](docs/design.md) | High-level product and system architecture; what each capability may decide |
| [Requirements](docs/requirements.md) | What must be true to ship v1, and how it's accepted |

### Capability designs

| Capability | Covers |
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
| [Deployment](docs/deployment.md) | Safety-checked dry run, the apply workflow, and post-deployment checks |

This README is the starting point for the repository and its docs. Capability documents fill in
detail under the high-level design and can't contradict it. Runbooks explain how to do things; they
don't change what the product or architecture is.

## Repository layout

The orchestrator is at the repository root; there is no separate `orchestrator/` directory.

| Area | Important paths |
|---|---|
| Orchestrator and application API | `app.py`, `session_manager.py`, `api_auth.py`, `artifact_store.py` |
| Session runtime and harnesses | `session-container/server.py`, `agent_deepagents.py`, `agent.py`, `appdb.py` |
| Frontend | `frontend/src/components/`, `frontend/src/hooks/useAgentSession.ts`, `frontend/src/lib/` |
| Infrastructure | `infra/`, `.github/workflows/` |
| Tests and check scripts | `scripts/`, `tests/` where present |

## Reference relationship to IDA

Local IDA material is comparative input only. It creates no CSA Workbench requirement and is not needed to
build, run, or understand the application. The useful bridge is architectural: an IDA team may reuse
CSA Workbench's context, tool, state, outcome, trace, and harness patterns through a future authenticated
adapter without receiving a bypass around the product's identity or authorization rules.
