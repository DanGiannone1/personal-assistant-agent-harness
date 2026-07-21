# Azure deployment runbook

> **Purpose:** Human-owned plan/apply procedure for an isolated CSA Workbench instance. It is not a claim that any deployment currently exists or is verified.

Read the current [`infra/deploy.sh`](../infra/deploy.sh) before use. The script requires a clean worktree and explicit model selection; it does not silently choose a model.

## Required inputs

Use placeholders until the human owner supplies target-specific values:

```bash
export INSTANCE_SLUG='your-instance-slug'
export MODEL_DEPLOYMENT_NAME='your-model-deployment-name'
export MODEL_NAME='your-model-name'
export MODEL_VERSION='your-model-version'
export MODEL_SKU_NAME='your-model-sku-name'
export MODEL_CAPACITY='your-model-capacity'
```

The resource group is always `csa-wb-<instance-slug>-rg`. The script defaults to `plan`:

```bash
./infra/deploy.sh plan
```

Plan authenticates and reads Azure state, checks guarded recovery conditions, and runs foundation what-if when applicable. It makes no Azure mutation. Its fresh-instance what-if cannot preview later Entra registration creation, image builds, or app deployment.

Record and review the printed `PLAN_ID` and the exact confirmation form:

```text
apply:<plan-id>:<resource-group>
```

Before any apply, the responsible human reviews the target, public surfaces, managed identities, cost-bearing resources, and any reported recovery deletion targets. Source checks and a plan do not prove a live deployment, browser journey, Entra sign-in, Azure behavior, or model response.

## Apply is human-owned

Only the responsible human may apply, using the exact confirmation emitted by the immediately preceding plan:

```bash
./infra/deploy.sh apply --confirm 'apply:<plan-id>:<resource-group>'
```

There is no `APPLY=true` path. Do not use unattended apply, and do not let a coding agent apply with a copied confirmation. Apply re-computes and rechecks the plan before mutation. Depending on the guarded recovery state, it may delete only explicitly approved recovery targets before foundation deployment, then creates Entra registrations, builds images, deploys applications, and verifies the declared Azure inventory.

Any legacy resource names, model revisions, URLs, or prior run results are historical observations only and are not portable proof for this instance.

## Reminder email delivery (not yet provisioned)

Reminder email needs an Azure Communication Services (ACS) resource with a verified sender address, reachable by the deployed app's managed identity through `DefaultAzureCredential`, plus `ACS_EMAIL_ENDPOINT`/`ACS_SENDER_ADDRESS` app configuration. **UNVERIFIED / not-yet-provisioned:** `infra/` currently has no Bicep for an ACS resource, role assignment, or this app configuration — provisioning it is a separate, human-owned infrastructure change, not something this runbook or `deploy.sh` does today.

Once provisioned, dispatch behavior depends on deployment shape: an always-on API app replica runs the in-process dispatch loop (`REMINDER_DISPATCH=auto` ticks it whenever ACS is configured); a scale-to-zero deployment instead needs an external scheduler — e.g. an ACA Job on a cron trigger — invoking `scripts/dispatch_reminders.py` for one due-reminder pass, since a scaled-to-zero replica cannot run its own loop. No such job is defined in `infra/` yet either.
