# Repository Claude entry point

Before working in this repository, read [docs/README.md](docs/README.md) and
[docs/governance/README.md](docs/governance/README.md). Follow the documents named there:

- read the Master SDLC and Engineering Operating Standards before investigating or changing the
  repository;
- read the Testing Charter before designing, changing, or running checks; and
- read Agentic Design before changing agents, skills, prompts, or handoffs.

Read the product, architecture, development, and deployment documents related to the requested
change. Stop and ask the user when required guidance is missing or contradictory.

Claude agents and skills live in `.claude/agents/` and `.claude/skills/`. Start the local PPEL with
`claude --agent ppel`. Preserve existing worktree changes and do not switch the primary branch
unless the user explicitly asks.
