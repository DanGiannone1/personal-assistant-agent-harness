# Azure deployment runbook

> **Purpose:** User-authorized, agent-operated plan/apply procedure for an isolated CSA Workbench instance. It is not a claim that any deployment currently exists or is verified.

Read the current [`infra/deploy.sh`](../infra/deploy.sh) before use. The script requires a clean worktree and explicit model selection; it does not silently choose a model. Environment-specific inventory (resource groups, URLs, deployed revisions) is operator knowledge recorded with the tracking issue, not in this repository.

## What this creates

Each `INSTANCE_SLUG` deploys its own isolated resource group `csa-wb-<slug>-rg` containing a public
frontend Container App, a public API Container App, an internal-only session-runtime Container App
(each scaled `0-1`), a VNet with private endpoints and private DNS for Cosmos DB and Blob Storage, a
Basic Azure Container Registry, and an Azure OpenAI account/deployment sized by the `MODEL_*`
inputs. Every workload uses its own user-assigned managed identity; there is no shared-key or
anonymous data path. See [Infrastructure](capabilities/infrastructure.md) for the exact resource,
identity, and cost contract.

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

## Preferred CLI-agent workflow

The human collaborator owns the Azure account and the decision to deploy. Sign in, select the exact
tenant and subscription, and verify the active target before asking a CLI coding agent to deploy:

```bash
az login --tenant '<tenant-id-or-domain>'
az account set --subscription '<subscription-id-or-name>'
az account show --query '{subscription:name,subscriptionId:id,tenantId:tenantId,user:user.name}' -o json
```

Then tell the agent which instance slug or slugs to deploy, the identity mode for each instance,
and the model profile. Secrets such as `DEMO_PASSWORD` stay in the local environment or an ignored
secret file; do not paste, print, or commit them. Tracked delivery and external-system work also
requires a current issue containing the objective, target, owner, risk, acceptance criteria, and
approval required by the [Master SDLC](governance/master-sdlc.md). The agent must confirm that work
record before apply. A request such as the following supplies the execution approval for the
selected account and named instances when it matches the approved work record:

```text
Deploy dev in demo mode and prod in Entra mode to the Azure tenant/subscription I selected,
using these exact model inputs: deployment <deployment>, model <model>, version <version>,
SKU <sku>, capacity <capacity>. Plan, apply, and validate both environments.
```

The agent must re-read `az account show`, compare the live tenant/subscription and requested inputs,
and summarize the plan before mutation. When the user asked the agent to **deploy** (not merely
plan), the agent may run the exact `apply --confirm ...` command emitted by that plan. A plan that
introduces recovery deletions, changes the requested target or identity/model profile, or reveals a
new material security/cost decision requires fresh user approval before apply.

Record and review the printed `PLAN_ID` and the exact confirmation form:

```text
apply:<plan-id>:<resource-group>
```

Before any apply, the responsible operator reviews the target, public surfaces, managed identities,
cost-bearing resources, and any reported recovery deletion targets. For an agent-operated deploy,
the agent performs and reports this review under the user's explicit deployment authorization.
Source checks and a plan do not prove a live deployment, browser journey, Entra sign-in, Azure
behavior, or model response.

## Apply is target-bound and user-authorized

Apply uses the exact confirmation emitted by the immediately preceding plan:

```bash
./infra/deploy.sh apply --confirm 'apply:<plan-id>:<resource-group>'
```

There is no `APPLY=true` path and a plan-only request never authorizes apply. An explicitly
authorized CLI coding agent may pass the current plan's confirmation; a human operator may also run
the command directly. Apply re-computes and rechecks the plan before mutation, so a stale
confirmation or changed target/input fails closed. Depending on the guarded recovery state, it may
delete only explicitly approved recovery targets before foundation deployment, then creates Entra
registrations, builds images, deploys applications, and verifies the declared Azure inventory.

Any legacy resource names, model revisions, URLs, or prior run results are historical observations only and are not portable proof for this instance.

## Recovery is fail-closed

Before planning or applying, the script inspects any existing Container Apps environment named for
the target slug. An absent or already-compatible environment needs no recovery. An incompatible one
(wrong network shape, or an app inventory that doesn't exactly match the three expected app names) is
reported as a deletion target only for exactly those three named apps and their environment — never
adopted, never partially deleted, and never silently worked around. Apply deletes only the approved
targets from the immediately preceding plan before foundation deployment runs.

## What the post-apply verifier checks

After `apply`, the script re-reads live Azure JSON rather than trusting the deployment command's own
success. It requires exactly the three named Container Apps with their declared ingress, ports,
`0-1` scale, and the same immutable Git-SHA image tag; the exact VNet/subnet/private-endpoint/
private-DNS shape for Cosmos and Blob; disabled Cosmos local/public access and disabled Storage
public/shared-key/public-blob access; the exact managed-identity role assignments contained within
the resource group; and the full expected resource inventory with nothing extra. A tenant-governance
NSG pair may legitimately exist outside the application's own Bicep; the verifier tolerates its
absence and validates its exact shape only when present. Any other unexpected resource fails the
inventory check.

## Live post-apply validation

The script's successful verifier proves the declared infrastructure inventory; it does not prove
that a scaled-to-zero app can start, a user can authenticate, or a browser journey works. After each
apply, resolve the public endpoints and exercise their health surfaces:

```bash
export RESOURCE_GROUP="csa-wb-${INSTANCE_SLUG}-rg"
export FRONTEND_FQDN="$(az containerapp show -g "$RESOURCE_GROUP" -n "csa-wb-${INSTANCE_SLUG}-frontend" --query properties.configuration.ingress.fqdn -o tsv)"
export API_FQDN="$(az containerapp show -g "$RESOURCE_GROUP" -n "csa-wb-${INSTANCE_SLUG}-api" --query properties.configuration.ingress.fqdn -o tsv)"
curl --fail --retry 12 --retry-all-errors --max-time 30 "https://${FRONTEND_FQDN}/"
curl --fail --retry 12 --retry-all-errors --max-time 30 "https://${API_FQDN}/health"
```

On a new or otherwise dedicated `demo` instance, the real-browser suite can validate login,
authorization boundaries, CRUD, agent behavior, responsive layout, and screenshots against Azure.
It mutates the demo fixture and skips the local destructive reset, so do not aim it at an Entra or
shared environment:

```bash
export MVP_ALLOW_REMOTE=1
export MVP_APP_URL="https://${FRONTEND_FQDN}"
export MVP_API_URL="https://${API_FQDN}"
export IDENTITY_MODE=demo
export AZURE_DEPLOYMENT='<deployed-model-name>'
# DEMO_PASSWORD must already be present without printing it.
npm run playwright:mvp
```

Remote screenshots and results are written under ignored `evidence/mvp/azure-demo/`. Inspect the
result JSON and screenshots rather than relying on the command's exit code alone. The run observes
the expected demo portfolio/data contract but labels the deployed fixture version `UNVERIFIED`
because the application does not expose a fixture-version attestation.

For an `entra` instance, the Azure CLI registration is pre-authorized for the API's delegated
`access_as_user` scope. Use the signed-in real tenant identity for a nonsecret token smoke test:

```bash
export API_CLIENT_ID="$(az ad app list --display-name "CSA Workbench [${INSTANCE_SLUG}] API" --query '[0].appId' -o tsv)"
test -n "$API_CLIENT_ID"
ACCESS_TOKEN="$(az account get-access-token --scope "api://${API_CLIENT_ID}/access_as_user" --query accessToken -o tsv)"
ENTRA_ME="$(curl --fail --retry 6 --retry-all-errors --max-time 30 -H "Authorization: Bearer ${ACCESS_TOKEN}" "https://${API_FQDN}/auth/me")"
unset ACCESS_TOKEN
ENTRA_ME="$ENTRA_ME" python3 -c 'import json,os; value=json.loads(os.environ["ENTRA_ME"]); assert value.get("identity") == "entra" and value.get("id", "").startswith("u-")'
unset ENTRA_ME
```

Success is an HTTP 200 actor document with `identity: entra` and a canonical `u-<oid>` ID. This
proves tenant/audience/signature/scope validation and first-use actor provisioning; it does not
prove the frontend's interactive redirect, which must be recorded separately when that browser
journey is required. The demo browser harness is not Entra evidence. Mark any journey that cannot
be performed `UNVERIFIED` rather than inferring it from infrastructure health.

## Workflow boundary

`.github/workflows/deploy.yml` is validation-only: on push, pull request, or manual dispatch it runs
`npm run verify:ci` and compiles both Bicep entrypoints. It has no deployment credential, OIDC
permission, image publication, or Azure mutation. The guarded manual script above is the only
deployment path.

## Reminder email delivery (not yet provisioned)

Reminder email needs an Azure Communication Services (ACS) resource with a verified sender address, reachable by the deployed app's managed identity through `DefaultAzureCredential`, plus `ACS_EMAIL_ENDPOINT`/`ACS_SENDER_ADDRESS` app configuration. **UNVERIFIED / not-yet-provisioned:** `infra/` currently has no Bicep for an ACS resource, role assignment, or this app configuration — provisioning it is a separate, human-owned infrastructure change, not something this runbook or `deploy.sh` does today.

Once provisioned, dispatch behavior depends on deployment shape: an always-on API app replica runs the in-process dispatch loop (`REMINDER_DISPATCH=auto` ticks it whenever ACS is configured); a scale-to-zero deployment instead needs an external scheduler — e.g. an ACA Job on a cron trigger — invoking `scripts/dispatch_reminders.py` for one due-reminder pass, since a scaled-to-zero replica cannot run its own loop. No such job is defined in `infra/` yet either.
