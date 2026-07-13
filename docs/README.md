# Personal Assistant Documentation

Start with the [top-level README](../README.md) for the overview and quick start. These docs go
deeper:

- **[manifesto.md](manifesto.md)** — why this exists: the work lives here, claims never outrun
  reality, and the engagement is the unit of the job.
- **[engagements.md](engagements.md)** — the first-class entity: one doc per engagement, membership
  as authorization, the delivery record (stage, health-with-a-why, milestones/risks/actions).
- **[mvp-requirements.md](mvp-requirements.md)** — the v1 bar: multi-user on Azure, deepagents-first,
  a slim engagement (G/Y/R + artifacts), the MVP context layer — requirements and success criteria only.
- **[use-cases.md](use-cases.md)** — the core use cases with concrete, runnable examples (manual +
  assistant path for each capability). Start here to see what it does.
- **[spec.md](spec.md)** — the product: capabilities, surfaces, data model, agent tools, skills, theme.
- **[roadmap.md](roadmap.md)** — where this goes next: the context layer, the competitive bar
  against general assistants, and the phased path from demo to product.
- **[projects-spec.md](projects-spec.md)** — the aligned build spec: accounts, shared projects as
  the context scope, the navigation upgrade, preview-card CRUD, and the personal context layer —
  each feature specified app-first, then harness-enabled.
- **[architecture.md](architecture.md)** — the system: tiers, the AG-UI/SSE event flow, session
  lifecycle, state & storage, auth forwarding, the scheduler.
- **[navigation-reference-architecture.md](navigation-reference-architecture.md)** — navigation as a
  trust boundary: one intent call, a deterministic resolver, three explicit outcomes, and the
  event-driven follow rule.
- **[crud-reference-architecture.md](crud-reference-architecture.md)** — CRUD as one state model with
  two callers (agent tools + manual REST) over one ETag-safe mutation path, the outcome contract, and
  the validation-parity gap.
- **[personalized-navigation-via-user-context.md](personalized-navigation-via-user-context.md)** —
  design direction (not built): user context ranks destinations for quick-nav and disambiguation,
  without ever changing what's reachable.
- **[harnesses.md](harnesses.md)** — the two interchangeable agent harnesses (Copilot SDK and Deep
  Agents), the `AgentSession` seam they share, and the reusable MCP-tools/skills direction.
- **[retrieval.md](retrieval.md)** — the two-tier document model (session files + indexed Library),
  RAG via Azure AI Search, and the upload/conversion pipeline.
- **[development.md](development.md)** — local setup, configuration, running, switching harnesses,
  and the testing discipline.
- **[deployment.md](deployment.md)** — Azure Container Apps deployment, RBAC, and the deploy-time
  gotchas.

For the Deep Agents harness build-out and its A/B comparison against the Copilot SDK, see
[`review/2026-06-24-deepagents-poc/FINDINGS.md`](../review/2026-06-24-deepagents-poc/FINDINGS.md).
