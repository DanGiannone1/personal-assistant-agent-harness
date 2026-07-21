# CLI coding-agent setup

This guide is for a human collaborator using a CLI coding agent. It does not replace [AGENTS.md](../AGENTS.md), the [documentation index](README.md), or [governance](governance/README.md); read those first.

## Local work

1. Inspect the current source and worktree before relying on a claim. Preserve other work.
2. Install repository dependencies with `uv sync`, `(cd session-container && uv sync)`, and `(cd frontend && npm ci)`.
3. Use the isolated run contract in [development.md](development.md), not a shared process or data target.
4. Ask a human to provide secrets, Azure subscription/tenant choices, model inputs, or Cosmos-emulator inputs. Do not print, commit, or echo them.
5. Run nonsecret local verification, normally `npm run verify`, and report what it does and does not prove.

## Azure boundary

An agent may help a human prepare an Azure **plan** only after the human supplies the target inputs. It must summarize the target resource group, the plan identifier, expected cost-bearing/public surfaces, identities, any deletion/recovery targets, and what the plan cannot preview. A plan performs Azure reads and what-if; it does not mutate Azure.

The agent must then stop. The human must provide the exact confirmation printed by the current plan and personally run apply. There is no unattended apply: an agent must never run apply with a copied confirmation, even if it produced the plan. See [deployment.md](deployment.md).
