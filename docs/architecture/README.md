# Architecture overview

CSA Workbench has three running application components and two main storage systems.

```text
Browser -> Next.js frontend -> FastAPI API -> assistant runtime -> Azure OpenAI
                              |
                              +-- Cosmos DB
                              +-- Engagement artifact storage
```

## Components

### Frontend

The Next.js application renders Engagements, private work, Assistant, and Settings. It calls the
FastAPI API for application data and receives assistant events as a server-sent event stream.

### API

The FastAPI application authenticates users, serves product records, owns assistant-session IDs,
and calls the internal assistant runtime. It uses the shared `workbench_core` package for Engagement
and private-work rules.

### Assistant runtime

The runtime hosts one temporary assistant session at a time for each session ID. Deep Agents is the
main runtime. A Copilot adapter remains available for local comparison. Both adapters expose the
same twenty product tools.

### Storage

Cosmos DB stores users, Engagements, and each user's private Tasks, Calendar events, and Reminders.
Engagement artifact bytes use a local directory during development and Azure Blob Storage when
configured for an Entra deployment.

Assistant conversations, session uploads, and generated files are temporary. They are not stored as
Engagement or private-work records.

## Shared application rules

The API and assistant tools both call `workbench_core.EngagementService` and
`workbench_core.PersonalWorkspaceService`. These services check permissions, validate input, save
changes, and return structured results. This avoids separate business rules for the web application
and assistant.

## Identity modes

Each running environment selects one identity mode:

- `demo` uses the local users `dan`, `ava`, and `sam` with a configured password.
- `entra` accepts users from one configured Microsoft Entra tenant.

The server binds the authenticated user to every request and assistant session. User IDs and roles
are not assistant tool arguments.

## Read more

- [Experience](capabilities/experience.md)
- [Data](capabilities/data.md)
- [Assistant](capabilities/assistant.md)
- [Identity and access](capabilities/identity-and-access.md)
- [Infrastructure](capabilities/infrastructure.md)
- [Product requirements](../product/requirements.md)
- [Reference architectures](../reference-architectures/README.md)
