# Repository Claude Entrypoint

Before meaningful repository work, read [docs/README.md](docs/README.md) and
[docs/governance/README.md](docs/governance/README.md). Follow the canonical
documents named there:

- read the Master SDLC and Engineering Operating Standards before changing the
  repository;
- read the Testing Charter before designing, changing, or running tests; and
- read Agentic Design before changing agents, skills, prompts, or handoffs.

Use the product, architecture, development, and deployment sources linked from
the documentation index for affected behavior. If required guidance is missing
or conflicts, stop and report the conflict instead of inventing a rule.

Claude-specific agents and skills live in `.claude/agents/` and
`.claude/skills/`. Start the local PPEL with `claude --agent ppel`. Preserve
existing worktree changes and do not switch the primary branch unless the user
explicitly asks.
