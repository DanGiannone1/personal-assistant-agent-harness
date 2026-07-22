# Contributing to CSA Workbench

Start with [AGENTS.md](AGENTS.md) when using Codex or [CLAUDE.md](CLAUDE.md) when using Claude. Then
read the [documentation guide](docs/README.md) and the [governance guide](docs/governance/README.md).

Before making a change:

1. Confirm the requested outcome and the parts of the repository it affects.
2. Inspect the current source and preserve unrelated worktree changes.
3. Follow the approval and review process in the [Master SDLC](docs/governance/master-sdlc.md).
4. Use an isolated local instance when running the application.
5. Run the checks appropriate to the change and report what happened.

The main repository check is:

```bash
npm run verify
```

Some browser, model, and Azure commands call external services or change stored data. Run them only
when the user has approved that exact work. See the [local development guide](docs/guides/local-development.md),
[deployment guide](docs/guides/deployment.md), and [coding-agent guide](docs/guides/coding-agents.md).

Do not create an external-sharing, license, security-contact, or release policy without a human
decision.
