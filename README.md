# CSA Workbench

CSA Workbench is an internal workspace for Cloud Solution Architects. It brings shared customer
Engagements, private tasks and calendar work, and an assistant into one application.

The product is designed to be useful without AI. People can create and update Engagements, manage
their own work, and share Engagements through the web application. The assistant provides another
way to perform supported actions through the same application services.

## What you can do

- Create and share customer Engagements with owner, editor, and viewer roles.
- Track Engagement status, dates, tasks, conventions, and artifacts.
- Manage private Tasks, Calendar events, and Reminders.
- Ask the assistant to read or update supported records and open supported pages.
- Prepare an Engagement meeting brief or run a personal weekly review.

## Main workflow

A CSA creates or opens a customer Engagement, reviews its current status and delivery information,
and shares it with the right team members. They can then ask the assistant to prepare a meeting
brief, make a supported status change, and open the updated Engagement. Private Tasks, Calendar
events, and Reminders remain available only to the signed-in user throughout that work.

## Run it locally

Install Python 3.12 or later, `uv`, Node.js and npm, Azure CLI, and a local Cosmos DB emulator. Then:

```bash
cp .env.example .env
npm ci
uv sync
(cd session-container && uv sync)
(cd frontend && npm ci)
uv run dev.py
```

Set the local identity, model, and Cosmos values in `.env` before starting. The
[local development guide](docs/guides/local-development.md) lists the required settings and shows
how to run an isolated copy.

## How it works

```text
Browser -> Next.js frontend -> FastAPI API -> assistant runtime -> Azure OpenAI
                              |
                              +-- Cosmos DB
                              +-- Engagement artifact storage
```

The API and assistant runtime use shared application services for Engagements and personal work.
This keeps authorization, validation, and saved results consistent whether an action starts in the
web application or through the assistant.

## Where to go next

- [Understand the product](docs/product/overview.md)
- [Read the current architecture](docs/architecture/README.md)
- [Run it locally](docs/guides/local-development.md)
- [Demonstrate the main workflow](docs/guides/demo.md)
- [Contribute](CONTRIBUTING.md)
- [Deploy an isolated Azure instance](docs/guides/deployment.md)
- [Browse all documentation](docs/README.md)

CSA Workbench is an internal MVP. It does not claim production readiness, external distribution,
or a complete project-management and enterprise-search feature set.
