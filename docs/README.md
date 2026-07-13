# Personal Assistant Documentation

Start with the [top-level README](../README.md) for the overview and quick start.

- **[manifesto.md](manifesto.md)** — why this exists: the work lives here, claims never outrun
  reality, and the engagement is the unit of the job.
- **[engagements.md](engagements.md)** — the first-class entity: one doc per engagement, membership
  as authorization, status-with-a-why, tasks, artifacts.
- **[mvp-requirements.md](mvp-requirements.md)** — the v1 bar: multi-user on Azure, deepagents-first,
  a slim engagement (G/Y/R + artifacts), the MVP context layer — requirements and success criteria only.

## Core reference architectures

These three documents describe the product from the highest-level user behavior down to contracts,
implementation boundaries, and migration from the current repo. They are designed to be read as one
set:

- **[context-reference-architecture.md](context-reference-architecture.md)** - the foundation:
  authenticated per-turn context, its prompt/tool/UI/inspector projections, precedence, memory, and
  LangGraph Deep Agents integration.
- **[navigation-reference-architecture.md](navigation-reference-architecture.md)** - personalized
  quick links, immediate known-destination navigation, and the grounded embed -> search -> pick tool
  for natural-language navigation.
- **[crud-reference-architecture.md](crud-reference-architecture.md)** - context-aware changes from
  any screen through one backend service behind REST/MCP, with authorization, approvals, structured
  outcomes, and post-commit navigation.

## Product, system, and operations

- **[use-cases.md](use-cases.md)** - the core use cases with concrete, runnable examples (manual +
  assistant path for each capability). Start here to see what it does.
- **[spec.md](spec.md)** - the product: capabilities, surfaces, data model, agent tools, skills, theme.
- **[roadmap.md](roadmap.md)** - where this goes next: the context layer, competitive bar, and phased
  path from demo to product.
- **[projects-spec.md](projects-spec.md)** - the existing Projects build spec. The target reference
  architectures use **Engagement** as the chosen shared-scope term while retaining the stronger
  account, role, context, and approval foundations from this design.
- **[architecture.md](architecture.md)** - the current system: tiers, AG-UI/SSE flow, session
  lifecycle, state and storage, auth forwarding, and scheduler.
- **[personalized-navigation-via-user-context.md](personalized-navigation-via-user-context.md)** -
  earlier design reasoning now incorporated into the core context and navigation references.
- **[harnesses.md](harnesses.md)** - the Copilot and Deep Agents harnesses, their `AgentSession` seam,
  and the reusable MCP-tools/skills direction.
- **[retrieval.md](retrieval.md)** - the session-file and indexed-Library model, RAG, and upload
  conversion pipeline.
- **[development.md](development.md)** - local setup, configuration, harness switching, and testing.
- **[deployment.md](deployment.md)** - Azure Container Apps deployment, RBAC, and operational
  gotchas.

For the Deep Agents harness build-out and its A/B comparison against the Copilot SDK, see
[`review/2026-06-24-deepagents-poc/FINDINGS.md`](../review/2026-06-24-deepagents-poc/FINDINGS.md).
