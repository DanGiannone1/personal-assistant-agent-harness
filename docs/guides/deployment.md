# Azure deployment

This guide creates one isolated CSA Workbench instance with `infra/deploy.sh`. Planning is read-only.
Deployment changes Azure resources and requires the user's explicit approval.

## Before starting

1. Read the current `infra/deploy.sh`.
2. Confirm the approved work record required by the [Master SDLC](../governance/master-sdlc.md).
3. Use a clean worktree.
4. Sign in to the intended Azure tenant and subscription.
5. Obtain the exact instance and model values from the user.

```bash
az login --tenant '<tenant-id-or-domain>'
az account set --subscription '<subscription-id-or-name>'
az account show --query '{subscription:name,subscriptionId:id,tenantId:tenantId,user:user.name}' -o json
```

## Required values

```bash
export INSTANCE_SLUG='your-instance-slug'
export MODEL_DEPLOYMENT_NAME='your-model-deployment-name'
export MODEL_NAME='your-model-name'
export MODEL_VERSION='your-model-version'
export MODEL_SKU_NAME='your-model-sku-name'
export MODEL_CAPACITY='your-model-capacity'
export IDENTITY_MODE='entra'
```

Use `IDENTITY_MODE=demo` only for an isolated demo deployment. Demo mode also requires
`DEMO_PASSWORD` to be present in the environment without printing or committing it.

The resource group is `csa-wb-<instance-slug>-rg`.

## Plan

```bash
./infra/deploy.sh plan
```

Planning authenticates to Azure, inspects the selected target, checks whether recovery is needed,
and runs the available Bicep what-if operation. It prints a `PLAN_ID` and a confirmation in this
format:

```text
apply:<plan-id>:<resource-group>
```

Before deployment, review:

- tenant, subscription, instance name, and resource group;
- identity mode and model values;
- public frontend and API access;
- managed identities and their roles;
- resources that can incur cost; and
- any recovery deletion reported by the plan.

Ask the user again before continuing if the plan introduces a new deletion, target, security choice,
or cost choice that was not already approved.

## Apply

Run apply only when the user requested deployment and the current plan matches that request:

```bash
./infra/deploy.sh apply --confirm 'apply:<plan-id>:<resource-group>'
```

Apply recomputes and checks the plan before changing Azure. A stale confirmation fails. When
recovery is needed, the script removes only the exact Container Apps and environment named in the
current plan before creating the approved resources.

The script creates Entra registrations, builds Git-SHA-tagged images, deploys the Azure components,
and inspects the resulting resource group, network, identities, and application settings.

The final inspection requires exactly the three expected Container Apps with the configured access,
ports, replica limits, and Git-SHA image tag. It also checks the private network, Cosmos and Blob
settings, managed-identity roles, and expected resource list. An unexpected application-owned
resource causes the deployment check to fail.

## Check application health

After apply, resolve the public endpoints and call them:

```bash
export RESOURCE_GROUP="csa-wb-${INSTANCE_SLUG}-rg"
export FRONTEND_FQDN="$(az containerapp show -g "$RESOURCE_GROUP" -n "csa-wb-${INSTANCE_SLUG}-frontend" --query properties.configuration.ingress.fqdn -o tsv)"
export API_FQDN="$(az containerapp show -g "$RESOURCE_GROUP" -n "csa-wb-${INSTANCE_SLUG}-api" --query properties.configuration.ingress.fqdn -o tsv)"
curl --fail --retry 12 --retry-all-errors --max-time 30 "https://${FRONTEND_FQDN}/"
curl --fail --retry 12 --retry-all-errors --max-time 30 "https://${API_FQDN}/health"
```

## Demo-mode browser check

Use only a new or dedicated demo instance. This command changes demo records and must not target an
Entra or shared environment.

```bash
export MVP_ALLOW_REMOTE=1
export MVP_APP_URL="https://${FRONTEND_FQDN}"
export MVP_API_URL="https://${API_FQDN}"
export IDENTITY_MODE=demo
export AZURE_DEPLOYMENT='<deployed-model-name>'
npm run playwright:mvp
```

`DEMO_PASSWORD` must already be available without printing it.

## Entra API check

```bash
export API_CLIENT_ID="$(az ad app list --display-name "CSA Workbench [${INSTANCE_SLUG}] API" --query '[0].appId' -o tsv)"
test -n "$API_CLIENT_ID"
ACCESS_TOKEN="$(az account get-access-token --scope "api://${API_CLIENT_ID}/access_as_user" --query accessToken -o tsv)"
ENTRA_ME="$(curl --fail --retry 6 --retry-all-errors --max-time 30 -H "Authorization: Bearer ${ACCESS_TOKEN}" "https://${API_FQDN}/auth/me")"
unset ACCESS_TOKEN
ENTRA_ME="$ENTRA_ME" python3 -c 'import json,os; value=json.loads(os.environ["ENTRA_ME"]); assert value.get("identity") == "entra" and value.get("id", "").startswith("u-")'
unset ENTRA_ME
```

## Reminder email

The current Azure templates do not create Azure Communication Services resources or a scheduled
Reminder job. Adding either requires separate approval and infrastructure work. Scale-to-zero
deployments need an external schedule because an inactive API cannot run its in-process Reminder
loop.

## GitHub Actions

`.github/workflows/deploy.yml` runs repository checks and Bicep compilation. It has no Azure
credential and does not deploy. The guarded local script is the deployment path.
