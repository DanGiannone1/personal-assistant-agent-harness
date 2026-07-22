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

The intended handoff is simple: the human signs in with Azure CLI, selects the tenant and
subscription, and tells the coding agent to deploy per the [deployment guide](deployment.md). The
human names the instance, identity mode, and model configuration and explicitly authorizes apply.
The agent creates or updates the work record and handles the repository procedure, exact plan
confirmation, deployment, and verification.

```bash
az login --tenant '<tenant-id-or-domain>'
az account set --subscription '<subscription-id-or-name>'
az account show --query '{subscription:name,subscriptionId:id,tenantId:tenantId,user:user.name}' -o json
```

The agent may inspect Azure and run the repository's plan after confirming the selected account.
A plan-only request never permits deployment.

When the user explicitly requests deployment and the current plan matches the approved target, the
agent may use the exact confirmation printed by that plan.

Any new deletion, security decision, cost decision, or target change requires fresh approval. See
the [deployment guide](deployment.md) for the complete procedure.
