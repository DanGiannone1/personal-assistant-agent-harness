# Reference architectures

These documents explore how CSA Workbench could grow beyond the current MVP. They preserve detailed
design reasoning, data formats, processing steps, failure handling, security rules, and implementation
guidance. They do not set delivery dates or replace the current product documentation.

For current behavior, start with the [product overview](../product/overview.md) and
[architecture overview](../architecture/README.md).

Use these documents to understand or discuss a proposed design. Use the current architecture for
questions about what the application does today, the guides for running or deploying it, and the
product requirements for the MVP commitment. When part of a proposal is implemented, document that
behavior in the current architecture rather than treating the proposal as the operating guide.

## Shared foundations

Every design keeps the same foundations:

- The server binds the signed-in user, session, and role outside model-controlled arguments.
- The web application and assistant use the same application services.
- Tools accept typed input and return structured results.
- Every read or change checks current access and current stored data.
- The application refreshes saved data after a completed action instead of trusting assistant text.

## Designs

| Design | Focus |
|---|---|
| [Context](context.md) | One composed set of relevant information for the prompt, application tools, interface ranking, and a user explanation |
| [Navigation](navigation.md) | Personalized links and natural-language destination selection over one permission-filtered catalog |
| [CRUD](crud.md) | Create, update, and delete from any page, with scope and target selected from context |
| [Document AI](document-ai.md) | Broad file intake, conversion to normalized Markdown, extraction, and summarization |
| [RAG question answering](rag-qa.md) | Citation-based answers over per-user and per-Engagement document collections |
| [Agent evaluation](agent-evaluation.md) | Repeatable assessment of capability, safety, consistency, performance, and change impact |

Context supports the other designs. Navigation and CRUD use it to rank or default permitted choices.
Document intake and retrieval use its user and Engagement scope. Context never grants access; each
application service still checks current permissions.

## High-level design decisions

This is the shortest statement of what matters and what a good outcome looks like. The linked
documents own the detailed contracts and current-versus-target evidence.

| Design | What matters most | A good outcome |
|---|---|---|
| Context | Compose one small, explainable snapshot; use it to reduce repetition, never to grant access or replace a live read | The user can say “this” or “where I was,” the app can explain what it used, and every action still reauthorizes |
| Navigation | Use deterministic routes for known destinations; use semantic selection only for unresolved natural-language intent | No invented URL, no AI delay for a click or known record, and every selected destination is live and authorized |
| CRUD | Put REST and assistant tools over one application service; resolve only within authorized scope; commit before claiming success | Create/update/delete works from any page, ambiguity and destructive actions stop safely, and the UI reloads the committed record |
| Document AI | Preserve the original, create one complete normalized rendition, and expose document work through scoped typed tools | Supported files become ready or fail explicitly; conversion never loses the original or leaks content across scopes |
| RAG/QA | Search exactly one authorized logical scope, post-validate every passage, and answer only from current cited evidence | Every factual claim maps to an authenticated application citation; empty, partial, stale, or failed retrieval never becomes a guess |

The first three designs extend capabilities that exist in narrower form today. Document AI and
RAG/QA are not implemented. Their stored-data, security, Azure-cost, and rollout choices remain
pending explicit owner approval in [issue #28](https://github.com/DanGiannone1/csa-workbench/issues/28).

## Document organization

Each reference architecture contains:

1. a plain-language explanation of the intended experience;
2. design rules and technical details;
3. how it connects to the assistant runtime and shared application services;
4. a description of the current implementation.

The larger system designs end with an implementation checklist. Agent evaluation uses a phased
roadmap instead. Document AI and RAG include outcome criteria but remain proposals because their
implementation depends on the approval recorded in issue #28.

The current-implementation section is a bridge to today's architecture. The rest of each document
describes the proposed design in depth.
