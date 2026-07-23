# Azure deployment

This guide creates one isolated CSA Workbench instance with `infra/deploy.sh`. Planning is read-only.
Deployment changes Azure resources and requires the user's explicit approval.

## Human-to-agent quick start

The human selects the Azure account. The coding agent performs the documented planning, deployment,
and verification work.

```bash
az login --tenant '<tenant-id-or-domain>'
az account set --subscription '<subscription-id-or-name>'
az account show --query '{subscription:name,subscriptionId:id,tenantId:tenantId,user:user.name}' -o json
```

Then give the agent a request such as:

```text
Deploy CSA Workbench instance <instance> to the Azure tenant and subscription currently selected in
Azure CLI, following docs/guides/deployment.md. Use identity mode <entra|demo> and these model values:
<values>. I authorize the matching plan and apply. Stop for any unapproved deletion, target change,
security choice, or material cost choice. Verify the deployed application end to end.
```

The agent owns the repository procedure, work record, exact plan confirmation, deployment commands,
and evidence. The human does not need to translate the guide into individual shell commands. A
request to inspect or plan is not authorization to apply.

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

For a VNet-integrated Container Apps environment, some subscriptions must first register
`Microsoft.Network/AllowBringYourOwnPublicIpAddress` and then re-register the `Microsoft.Network`
provider. `infra/deploy.sh` does not perform that subscription-level registration. The agent may
inspect its state, but must stop and obtain explicit approval before registering it, or ask the human
to complete the prerequisite in the selected subscription. Authorization to apply the instance plan
does not implicitly authorize provider or feature registration. After the human-approved prerequisite
completes, rerun `az account show` and `./infra/deploy.sh plan`; never reuse an earlier confirmation.

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

A first deployment can take tens of minutes. Container Apps environment creation or recovery and
private-endpoint provisioning are long-running Azure control-plane operations; lack of terminal
output during those operations is not evidence that the deployment is stuck. Do not start a second
apply while the first is still active.

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
ENTRA_ME="$ENTRA_ME" python3 -c 'import json,os; value=json.loads(os.environ["ENTRA_ME"]); assert value.get("identity") == "entra" and value.get("id", "").startswith("u-")'
unset ENTRA_ME

SESSION_JSON="$(curl --fail --retry 6 --retry-all-errors --max-time 30 -X POST -H "Authorization: Bearer ${ACCESS_TOKEN}" -H 'Content-Type: application/json' -d '{}' "https://${API_FQDN}/sessions")"
SESSION_ID="$(SESSION_JSON="$SESSION_JSON" python3 -c 'import json,os; value=json.loads(os.environ["SESSION_JSON"]); assert value.get("status") == "active"; print(value["session_id"])')"
curl --fail --retry 6 --retry-all-errors --max-time 30 -X DELETE -H "Authorization: Bearer ${ACCESS_TOKEN}" "https://${API_FQDN}/sessions/${SESSION_ID}"
unset ACCESS_TOKEN SESSION_JSON SESSION_ID
```

The session round trip proves the API can call the private runtime with its managed identity. This
CLI check validates the API's delegated Entra path; it does not replace an interactive browser
redirect/MFA check when that experience is release-critical.

For Entra v2 workload tokens, request the runtime scope as
`api://<runtime-client-id>/.default`, but validate the token `aud` claim as the bare runtime client
ID. Treat the scope URI and emitted audience as distinct values.

## Acceptance evidence

A deployment is complete only after all of the following pass:

- the post-deployment inventory and private-network checks in `infra/deploy.sh`;
- public frontend and API health checks, with the runtime remaining private;
- immutable image tags matching the deployed Git SHA;
- an authenticated API-to-runtime session round trip;
- the remote browser suite for a dedicated demo instance; and
- for Entra, delegated API authentication plus an interactive browser sign-in when required for the
  release claim.

Do not describe the MVP as production-ready solely because it is deployed to an instance named
`prod`. Release readiness also requires current dependency-vulnerability review, observability,
operational ownership, and the remaining production controls identified in the architecture docs.

## Reminder email

The current Azure templates do not create Azure Communication Services resources or a scheduled
Reminder job. Adding either requires separate approval and infrastructure work. Scale-to-zero
deployments need an external schedule because an inactive API cannot run its in-process Reminder
loop.

## GitHub Actions

`.github/workflows/deploy.yml` runs repository checks and Bicep compilation. It has no Azure
credential and does not deploy. The guarded local script is the deployment path.
