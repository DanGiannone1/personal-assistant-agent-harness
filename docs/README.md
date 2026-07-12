# Personal Assistant Documentation

Start with the [top-level README](../README.md) for the overview and quick start. These docs go
deeper:

- **[manifesto.md](manifesto.md)** — why this exists and where it's going: the engagement
  workspace we run our own work in, and the principles we won't trade. Read this first.
- **[use-cases.md](use-cases.md)** — the core use cases with concrete, runnable examples (manual +
  assistant path for each capability). Start here to see what it does.
- **[spec.md](spec.md)** — the product: capabilities, surfaces, data model, agent tools, skills, theme.
- **[architecture.md](architecture.md)** — the system: tiers, the AG-UI/SSE event flow, session
  lifecycle, state & storage, auth forwarding, the scheduler.
- **[navigation-reference-architecture.md](navigation-reference-architecture.md)** — navigation as a
  trust boundary: one intent call, a deterministic resolver, three explicit outcomes, and the
  event-driven follow rule.
- **[crud-reference-architecture.md](crud-reference-architecture.md)** — CRUD as one state model with
  two callers (agent tools + manual REST) over one ETag-safe mutation path, the outcome contract, and
  the validation-parity gap.
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
