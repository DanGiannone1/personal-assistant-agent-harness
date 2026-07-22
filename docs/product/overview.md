# Product overview

## The problem

Cloud Solution Architects often reconstruct customer work from status documents, meeting notes,
messages, and personal memory. Their private tasks and calendar also live separately from the shared
customer record.

CSA Workbench brings that work together. Each customer Engagement is a durable shared record for its
members. Each user also has a private area for Tasks, Calendar events, and Reminders.

## The product

CSA Workbench includes:

- **Engagements** for shared customer work;
- **My work** for private Home, Tasks, Calendar, and Reminders pages;
- **Assistant** as another way to read and change supported records; and
- **Settings** for personal preferences used by the assistant.

Home is the default landing page. It leads with the user's Engagement portfolio and then shows the
private agenda, tasks, calendar events, and Reminders that need attention. Each Engagement has
Overview, Tasks, Artifacts, and Team & conventions sections. A user can create an Engagement and
becomes its first owner.

## How the assistant fits

The assistant is part of the product, but it is not the product's database or permission system.
It calls typed tools that use the same application services as the web interface. The server decides
which user is acting, checks current permissions, validates the request, saves the result, and returns
a structured outcome to the application.

The assistant supports twenty product tools: one navigation tool, six Engagement tools, and thirteen
private Tasks, Calendar, and Reminders tools. Four product skills guide common work:

- `engagement-meeting-prep`
- `tasks`
- `calendar`
- `weekly-review`

## Users and access

Private work belongs only to the signed-in user. Engagements use three roles:

| Role | What the member can do |
|---|---|
| Owner | Edit the Engagement, manage artifacts, and manage members |
| Editor | Edit delivery information, tasks, conventions, and artifacts |
| Viewer | Read the Engagement and download artifacts |

The server checks current access for every operation. A person who is not a member receives the same
not-found response as an unknown Engagement.

## Stored and temporary information

Cosmos DB stores users, Engagements, and private work. Engagement artifact files use a local
directory during development and Azure Blob Storage in an Entra deployment. Assistant conversations,
session uploads, and generated files are temporary and can disappear when the runtime restarts.

## Product limits

The MVP does not include global search, a shared document library, arbitrary file understanding,
multi-agent work, or broad project-management features. Session uploads accept Markdown files only.
The Copilot adapter is retained for local comparison; Deep Agents is the product runtime.

The product is intended for internal demonstration and development. Decisions about production use,
external distribution, security policy, and accessibility certification remain outside the MVP.
