# CLI coding-agent setup

This guide is for a human collaborator using a CLI coding agent. It does not replace [AGENTS.md](../AGENTS.md), the [documentation index](README.md), or [governance](governance/README.md); read those first.

## Local work

1. Inspect the current source and worktree before relying on a claim. Preserve other work.
2. Install repository dependencies with `uv sync`, `(cd session-container && uv sync)`, and `(cd frontend && npm ci)`.
3. Use the isolated run contract in [development.md](development.md), not a shared process or data target.
4. Ask the human collaborator to provide or select secrets, Azure subscription/tenant choices, model inputs, or Cosmos-emulator inputs. Do not print, commit, or echo them.
5. Run nonsecret local verification, normally `npm run verify`, and report what it does and does not prove.

## Azure boundary

The preferred workflow is for the human collaborator to sign in with Azure CLI, select the intended
tenant/subscription, and explicitly ask the CLI coding agent to deploy the named environment or
environments under an approved tracking issue. The agent must confirm `az account show`, use the
supplied identity/model inputs, prepare the repository's read-only plan, and summarize the target
resource group, plan identifier, cost-bearing/public surfaces, identities, recovery deletions, and
what the plan cannot preview.

If the user asked only for a plan, the agent must not apply. If the user explicitly asked the agent
to deploy, the plan matches the tracked authorization, and it introduces no new recovery deletion
or material security/cost decision, the agent may run `apply` with the exact target-bound
confirmation printed by the current plan. It then validates live inventory, identity/RBAC, network
and data security settings, application health, and the strongest safe user journey available. See
[deployment.md](deployment.md) for the canonical procedure and stop conditions.
