# CSA Workbench

CSA Workbench is an internal MVP vertical-slice POC for solution-architect Engagement work. Its
supported user surfaces are **Engagements** (the default landing surface), a private **My work**
group (**Home**, **Tasks**, **Calendar**, **Reminders**), **Assistant**, and **Settings**. The
product is deliberately small: it is not a Library, Search, quick-links, or generic workbench
product.

An embedded assistant can read and change the same records the UI renders, through typed tools and
structured outcomes rather than parsed chat text — so a claim cannot outrun the state that was
actually read or changed. The application is useful without it: every Engagement and personal-work
operation has a complete manual path.

## Choose a route

### Understand or demo the MVP

Start with the [MVP design](docs/design.md), then the [release and acceptance intent](docs/requirements.md).
The [reference eval architecture](docs/evals-reference-architecture.md) defines the demo slice and
evidence boundaries. For a manual demo, create or open an Engagement, then use the Assistant for the
versioned meeting-prep, status-update, and open workflow; the personal Tasks/Calendar/Reminders
surfaces have their own typed tools and skills (`tasks`, `calendar`, `weekly-review`).

### Contribute or run it with a CLI coding agent

Read [CONTRIBUTING.md](CONTRIBUTING.md), [coding-agent setup](docs/coding-agent-setup.md), and the
[local development runbook](docs/development.md). They route you to repository governance, safe
local verification, and the human-owned Azure deployment path.

## Run it locally

```bash
cp .env.example .env
uv sync
(cd session-container && uv sync)
(cd frontend && npm ci)
uv run dev.py
```

Set `IDENTITY_MODE=demo`, a local `DEMO_PASSWORD`, and Azure OpenAI/Cosmos-emulator values in
`.env` first — see [local development](docs/development.md) for the exact variables and for an
isolated multi-instance run. The launcher starts a frontend, FastAPI API, and session runtime as
three separate processes.

## MVP shape

The web frontend, FastAPI API, and session runtime are separate processes. Engagement data is
durable application state: durable Engagement artifact metadata lives with the Engagement record in
Cosmos DB and its bytes use the configured durable artifact backend (a local isolated directory in
development, Azure Blob for an Entra release). Personal Tasks, Calendar events, and Reminders are
durable, actor-owned records held on their own `personal-{uid}` Cosmos aggregate — never scoped to
or shared through an Engagement. Session files instead belong to an ephemeral assistant session, and
uploads to a session are Markdown (`.md`) only.

Deep Agents is the product lane. Copilot is retained only as a local portability and evaluation
lane; it is not a release claim. The product skills are `engagement-meeting-prep`, `tasks`,
`calendar`, and `weekly-review`, layered over thirteen typed personal tools and the Engagement/
navigation tools.

## Architecture at a glance

```text
Browser -> Next.js frontend -> FastAPI API -> session runtime -> Azure OpenAI
                              |                 |
                              +-- Cosmos DB: actors, Engagements, personal aggregates
                              +-- durable Engagement artifact bytes (local dir / Blob)
```

`workbench_core` is a dependency-light package shared by the API and the session runtime for
Engagement rules, the personal-workspace service, product-tool result types, and the navigation
destination catalog — so the manual UI and the assistant enforce the same authorization and
validation rules rather than two parallel implementations.

## Documentation authority

| Authority | Use it for |
|---|---|
| This README | Colleague-facing entry point and routing |
| [Design](docs/design.md) | High-level MVP product and system boundary |
| [Requirements](docs/requirements.md) | Release and acceptance intent |
| [Capability notes](docs/capabilities/) | Current focused boundaries |
| [Development](docs/development.md) and [deployment](docs/deployment.md) | Operating runbooks |
| [Evals reference architecture](docs/evals-reference-architecture.md) | Canonical demo/evidence architecture |
| [Governance](docs/governance/README.md) | Governing lifecycle, engineering, test, and agent rules |

The compatibility pointers in `docs/` (`architecture.md`, `spec.md`, `use-cases.md`,
`projects-spec.md`, `mvp-requirements.md`, `navigation-reference-architecture.md`) are historical
routes, not competing product or release requirements. Source and deterministic checks establish
only what they actually inspect. They do not by themselves prove a live browser, Entra, Azure, or
model interaction — see the evidence status below.

## Repository layout

There is no separate `orchestrator/` directory; the API lives at the repository root.

| Area | Important paths |
|---|---|
| API and shared application state | `app.py`, `session_manager.py`, `api_auth.py`, `auth_users.py`, `identity_config.py`, `artifact_store.py` |
| Shared Engagement/personal-workspace rules | `workbench_core/` (`engagements.py`, `personal_workspace.py`, `tool_protocol.py`, `acs_email.py`, `reminder_dispatch.py`) |
| Session runtime and harnesses | `session-container/server.py`, `session-container/agent_deepagents.py`, `session-container/agent.py`, `session-container/appdb.py` |
| Product skills | `session-container/product-skills/` |
| Frontend | `frontend/src/components/`, `frontend/src/hooks/`, `frontend/src/lib/` |
| Infrastructure | `infra/`, `.github/workflows/` |
| Tests and check scripts | `scripts/`, `tests/` |

## Evidence honesty

A local browser journey passed 41/41 checks at the current revision, including the page inventory
and a live agent turn, and `npm run verify` is green. Live-model spot checks cover the personal
tools. **Not verified from this repository:** a deployed Azure instance, a real Entra sign-in
against this code, a real Azure Communication Services email send, or a live-model eval run of the
`MVP-E8`/`MVP-E9` personal-work cases. Do not infer any of those from source inspection or a passing
deterministic check alone; see [requirements](docs/requirements.md) and
[evals reference architecture](docs/evals-reference-architecture.md) for the exact evidence
boundary.

## Useful links

- [Local development](docs/development.md)
- [Azure deployment runbook](docs/deployment.md)
- [Reference eval architecture](docs/evals-reference-architecture.md)
- [Coding-agent setup](docs/coding-agent-setup.md)
- [Governance](docs/governance/README.md)

External distribution, security policy, and sharing approval are human-owned decisions; this
repository is documented for internal colleague sharing.
