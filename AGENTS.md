# Repository agent entry point

Before working in this repository, read [docs/README.md](docs/README.md) and
[docs/governance/README.md](docs/governance/README.md). Follow the documents named there:

- read the Master SDLC and Engineering Operating Standards before investigating or changing the
  repository;
- read the Testing Charter before designing, changing, or running checks; and
- read Agentic Design before changing agents, skills, prompts, or handoffs.

Read the product, architecture, development, and deployment documents related to the requested
change. Stop and ask the user when required guidance is missing or contradictory.

Codex workflows live in `.codex/skills/`. The optional local PPEL profile is selected with
`codex --profile PPEL`; it does not replace repository guidance. Preserve existing worktree changes
and do not switch the primary branch unless the user explicitly asks.
