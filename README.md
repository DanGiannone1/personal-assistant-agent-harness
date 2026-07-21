# CSA Workbench

CSA Workbench is an internal MVP vertical-slice POC for solution-architect Engagement work. Its supported user surfaces are **Engagements** (the default landing surface), a private **My work** group (**Home**, **Tasks**, **Calendar**, **Reminders**), **Assistant**, and **Settings**. The product is deliberately small: it is not a Library, Search, quick-links, or generic workbench product.

## Choose a route

### Understand or demo the MVP

Start with the [MVP design](docs/design.md), then the [release and acceptance intent](docs/requirements.md). The [reference eval architecture](docs/evals-reference-architecture.md) defines the demo slice and evidence boundaries. For a manual demo, create or open an Engagement, then use the Assistant for the versioned meeting-prep, status-update, and open workflow.

### Contribute or run it with a CLI coding agent

Read [CONTRIBUTING.md](CONTRIBUTING.md), [coding-agent setup](docs/coding-agent-setup.md), and the [local development runbook](docs/development.md). They route you to repository governance, safe local verification, and the human-owned Azure deployment path.

## MVP shape

The web frontend, FastAPI API, and session runtime are separate processes. Engagement data is durable application state. Durable Engagement artifact metadata lives with the Engagement record and its bytes use the configured durable artifact backend; local development may use the isolated local artifact directory. Session files instead belong to an ephemeral assistant session and uploads are Markdown (`.md`) only.

Deep Agents is the product lane. Copilot is retained only as a local portability and evaluation lane; it is not a release claim. The product skills are `engagement-meeting-prep`, `tasks`, `calendar`, and `weekly-review`.

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

The compatibility pointers in `docs/` are historical routes, not competing product or release requirements. Source and deterministic checks establish only what they actually inspect. They do not prove a live browser, Entra, Azure, or model interaction.

## Useful links

- [Local development](docs/development.md)
- [Azure deployment runbook](docs/deployment.md)
- [Reference eval architecture](docs/evals-reference-architecture.md)
- [Coding-agent setup](docs/coding-agent-setup.md)
- [Governance](docs/governance/README.md)

External distribution, security policy, and sharing approval are human-owned decisions; this repository is documented for internal colleague sharing.
