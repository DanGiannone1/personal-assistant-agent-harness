# Working with coding agents

This guide is for a human collaborator using a CLI coding agent in the repository.

## Local work

1. Start with [AGENTS.md](../../AGENTS.md) for Codex or [CLAUDE.md](../../CLAUDE.md) for Claude.
2. Confirm the requested goal, boundaries, success criteria, and approval before editing.
3. Inspect the current source and worktree. Preserve other people's changes.
4. Use the isolated run instructions in [local development](local-development.md).
5. Supply or select secrets, Azure account choices, model values, and Cosmos settings yourself.
6. Run the relevant repository and browser checks and inspect the resulting behavior.

Do not paste, print, or commit secrets.

## Azure work

The human collaborator signs in with Azure CLI, selects the tenant and subscription, names the
instance, and supplies the model configuration. Deployment also needs an approved work record under
the [Master SDLC](../governance/master-sdlc.md).

The agent may inspect Azure and run the repository's plan after confirming the selected account.
A plan-only request never permits deployment.

When the user explicitly requests deployment and the current plan matches the approved target, the
agent may use the exact confirmation printed by that plan.

Any new deletion, security decision, cost decision, or target change requires fresh approval. See
the [deployment guide](deployment.md) for the complete procedure.
