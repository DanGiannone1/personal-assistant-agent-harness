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

## Document organization

Each reference architecture contains:

1. a plain-language explanation of the intended experience;
2. design rules and technical details;
3. how it connects to the assistant runtime and shared application services;
4. a description of the current implementation.

The larger system designs end with an implementation checklist. Agent evaluation uses a phased
roadmap instead. Document AI and RAG end after describing the gap between the proposal and the
current product because their next implementation steps depend on later product decisions.

The current-implementation section is a bridge to today's architecture. The rest of each document
describes the proposed design in depth.
