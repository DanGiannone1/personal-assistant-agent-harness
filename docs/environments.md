# Azure environments and access

> **Purpose:** What is running in Azure right now, how to reach it, and what testing is safe where.
> Facts below come from live Azure reads on **2026-07-21**; re-read before relying on them.
> [deployment.md](deployment.md) owns how instances are created; this runbook owns what exists.

## Current environments

| Environment | Resource group | Identity mode | Deployed revision | Status (2026-07-21) |
|---|---|---|---|---|
| Showcase | `csa-workbench-rg` | `entra` | `ce251fbb` | Healthy; API `/health` 200 |
| Dev | `csa-workbench-dev-rg` | `demo` | `9be072f8` | Healthy; API `/health` 200 |
| Eval evidence | `csa-workbench-eval-dev-rg` | n/a (no apps) | n/a | Blob Storage, Log Analytics, and Application Insights for eval traces (issue #21) |

URLs (from the live Container App ingress):

- Showcase frontend: <https://csa-workbench-frontend.bluedesert-4d686b6f.eastus2.azurecontainerapps.io>
- Showcase API: <https://csa-workbench-api.bluedesert-4d686b6f.eastus2.azurecontainerapps.io>
- Dev frontend: <https://csa-workbench-dev-frontend.kindmeadow-f9d14a0b.eastus2.azurecontainerapps.io>
- Dev API: <https://csa-workbench-dev-api.kindmeadow-f9d14a0b.eastus2.azurecontainerapps.io>
- Session runtimes are internal-ingress only in both environments; they have no public URL.

The `ME_...` resource groups alongside each environment are Azure-managed Container Apps
infrastructure; do not modify them.

## Both environments predate the recovery

**No environment runs the current code.** The showcase's `ce251fbb` and dev's `9be072f8` were built
before the 2026-07-21 recovery (issue #18), so the deployed apps contain the pre-redesign personal
surface — including the legacy reminder scheduler that the current code deliberately replaced. Two
practical consequences:

- do not demo the restored personal workspace, safe reminder email, or the SSE fix from Azure until
  a redeploy at a recovery-or-later revision; and
- the legacy scheduler in the deployed revisions cannot actually send email — no Azure Communication
  Services resource exists in the subscription — so its unsafe global-recipient path is inert, but
  retiring it is another reason to redeploy.

## Finding and checking an environment

```bash
# What exists
az group list --query "[?contains(name, 'csa-workbench')].name" -o tsv
az containerapp list --query "[].{name:name, rg:resourceGroup, fqdn:properties.configuration.ingress.fqdn}" -o table

# Deployed revision and identity mode (image tags are full Git SHAs — never `latest`)
az containerapp show -n csa-workbench-api -g csa-workbench-rg \
  --query "{image: properties.template.containers[0].image, mode: properties.template.containers[0].env[?name=='IDENTITY_MODE'].value | [0]}"

# Health — apps scale to zero; the first request may take a cold-start pause before answering
curl --max-time 100 https://<api-fqdn>/health
```

A healthy endpoint and a matching SHA prove reachability and identity of the deployed code — not
application behavior. Behavioral claims about a deployed environment need the live checks in
[Testing and evals](capabilities/testing-evals.md), recorded as a dated entry in the
[evidence record](evidence.md).

## What testing is safe where

| Environment | Safe | Not safe |
|---|---|---|
| Local isolated stack (`dev.py`) | Everything, including destructive resets | — |
| Dev (`demo` mode) | Read/write testing with the deterministic demo actors; browser smoke | Treating its data as durable; concurrent tests without coordinating (single shared demo fixture) |
| Showcase (`entra` mode) | Read-only smoke (health, sign-in page); coordinated demos | Test writes — it holds real-tenant actor data; any fixture reset |
| Eval evidence RG | Writing eval traces per issue #21 | Repurposing its storage for app data |

Destructive fixture resets (`scripts/reset_demo_state.py`) are loopback-guarded and refuse remote
targets by design; do not work around that guard against any Azure environment.

## Recording Azure evidence

Azure browser/Entra observations follow the same rule as everything else: name the date, revision
(image SHA), environment, and exactly what was exercised, then add the entry to the
[evidence record](evidence.md). An observation from one environment or revision is never proof for
another.
