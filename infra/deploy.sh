#!/usr/bin/env bash
# Manual, guarded deployment for the CSA Workbench MVP.  This script is the
# imperative edge only: Bicep owns the Azure topology and Entra is configured
# through the narrow helper beside it.  Mutations require APPLY=true.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY="${APPLY:-false}"
LOCATION="${LOCATION:-eastus}"
RESOURCE_GROUP="${RESOURCE_GROUP:-csa-workbench-rg}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-csa-workbench-env}"
FRONTEND_APP_NAME="${FRONTEND_APP_NAME:-csa-workbench-frontend}"
API_APP_NAME="${API_APP_NAME:-csa-workbench-api}"
RUNTIME_APP_NAME="${RUNTIME_APP_NAME:-csa-workbench-runtime}"
COSMOS_ACCOUNT_NAME="${COSMOS_ACCOUNT_NAME:-csaworkbench9fc05183}"
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-csaworkbench9fc05183}"
ACR_NAME="${ACR_NAME:-djgsharedacr}"
ACR_RESOURCE_GROUP="${ACR_RESOURCE_GROUP:-shared-services-rg}"
AOAI_NAME="${AOAI_NAME:-rfpagent-ai}"
AOAI_RESOURCE_GROUP="${AOAI_RESOURCE_GROUP:-flow-dev-rg}"
AZURE_DEPLOYMENT="${AZURE_DEPLOYMENT:-gpt-4.1}"

truthy() { [[ "${1,,}" == "true" || "${1,,}" == "1" || "${1,,}" == "yes" ]]; }
fail() { echo "ERROR: $*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"; }

require az
require git
require python3
az account show --only-show-errors >/dev/null || fail "sign in with az login before continuing"
TENANT_ID="$(az account show --query tenantId -o tsv)"
[[ -n "$TENANT_ID" ]] || fail "the current Azure account has no tenant id"
az bicep version >/dev/null || fail "Azure CLI Bicep support is required"

SHA="$(git rev-parse HEAD)"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "deployment requires a full 40-character Git SHA"
if [[ -n "$(git status --porcelain)" ]]; then
  fail "deployment requires a clean worktree so images and SHA agree"
fi
[[ "$COSMOS_ACCOUNT_NAME" =~ ^[a-z0-9]{3,44}$ ]] || fail "invalid Cosmos account name: $COSMOS_ACCOUNT_NAME"
[[ "$STORAGE_ACCOUNT_NAME" =~ ^[a-z0-9]{3,24}$ ]] || fail "invalid Storage account name: $STORAGE_ACCOUNT_NAME"

echo "CSA Workbench Azure MVP ($SHA)"
echo "Target: $RESOURCE_GROUP in $LOCATION; APPLY=$APPLY"

az bicep build --file infra/foundation.bicep --outfile /tmp/csa-workbench-foundation.json
az bicep build --file infra/apps.bicep --outfile /tmp/csa-workbench-apps.json

FOUNDATION_DEPLOYMENT_NAME="csa-foundation-${SHA:0:12}"
FOUNDATION=(az deployment sub create --name "$FOUNDATION_DEPLOYMENT_NAME" --location "$LOCATION"
  --template-file infra/foundation.bicep
  --parameters location="$LOCATION" resourceGroupName="$RESOURCE_GROUP" environmentName="$ENVIRONMENT_NAME"
  cosmosAccountName="$COSMOS_ACCOUNT_NAME" storageAccountName="$STORAGE_ACCOUNT_NAME"
  sharedAcrName="$ACR_NAME" sharedAcrResourceGroup="$ACR_RESOURCE_GROUP"
  azureOpenAiName="$AOAI_NAME" azureOpenAiResourceGroup="$AOAI_RESOURCE_GROUP")

echo "Running subscription what-if (no Azure or Entra mutation)..."
"${FOUNDATION[@]/create/what-if}" --result-format ResourceIdOnly --only-show-errors

if ! truthy "$APPLY"; then
  echo "Dry run complete. Set APPLY=true to build images and create/update Azure or Entra resources."
  exit 0
fi

"${FOUNDATION[@]}" --only-show-errors >/dev/null
ENVIRONMENT_DOMAIN="$(az deployment sub show --name "$FOUNDATION_DEPLOYMENT_NAME" --query properties.outputs.environmentDefaultDomain.value -o tsv)"
[[ -n "$ENVIRONMENT_DOMAIN" ]] || fail "foundation deployment did not return the Container Apps default domain"
FRONTEND_URL="https://${FRONTEND_APP_NAME}.${ENVIRONMENT_DOMAIN}"
API_URL="https://${API_APP_NAME}.${ENVIRONMENT_DOMAIN}"
RUNTIME_FQDN="${RUNTIME_APP_NAME}.${ENVIRONMENT_DOMAIN}"

ENTRA_JSON="$(python3 infra/entra.py --tenant-id "$TENANT_ID" --frontend-redirect-uri "$FRONTEND_URL" --api-uami-principal-id "$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-api-identity --query principalId -o tsv)")"
API_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["api_client_id"])' <<<"$ENTRA_JSON")"
WEB_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["web_client_id"])' <<<"$ENTRA_JSON")"
RUNTIME_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runtime_client_id"])' <<<"$ENTRA_JSON")"

ACR_SERVER="${ACR_NAME}.azurecr.io"
AOAI_ENDPOINT="$(az cognitiveservices account show -g "$AOAI_RESOURCE_GROUP" -n "$AOAI_NAME" --query properties.endpoint -o tsv)"
[[ -n "$AOAI_ENDPOINT" ]] || fail "Azure OpenAI account endpoint was not found"
AOAI_ENDPOINT="${AOAI_ENDPOINT%/}/openai/v1/"
az acr build -r "$ACR_NAME" -g "$ACR_RESOURCE_GROUP" -t "csa-workbench-api:$SHA" -f Dockerfile . --only-show-errors
az acr build -r "$ACR_NAME" -g "$ACR_RESOURCE_GROUP" -t "csa-workbench-runtime:$SHA" -f session-container/Dockerfile . --only-show-errors
az acr build -r "$ACR_NAME" -g "$ACR_RESOURCE_GROUP" -t "csa-workbench-frontend:$SHA" -f frontend/Dockerfile frontend \
  --build-arg "NEXT_PUBLIC_API_URL=$API_URL" \
  --build-arg NEXT_PUBLIC_IDENTITY_MODE=entra \
  --build-arg "NEXT_PUBLIC_ENTRA_TENANT_ID=$TENANT_ID" \
  --build-arg "NEXT_PUBLIC_ENTRA_CLIENT_ID=$WEB_CLIENT_ID" \
  --build-arg "NEXT_PUBLIC_ENTRA_API_CLIENT_ID=$API_CLIENT_ID" \
  --build-arg "NEXT_PUBLIC_ENTRA_API_SCOPES=api://$API_CLIENT_ID/access_as_user" \
  --build-arg "NEXT_PUBLIC_ENTRA_REDIRECT_URI=$FRONTEND_URL" --only-show-errors

APPS=(az deployment group create -g "$RESOURCE_GROUP" --name "csa-workbench-apps-${SHA:0:12}"
  --template-file infra/apps.bicep --parameters environmentName="$ENVIRONMENT_NAME" acrServer="$ACR_SERVER" imageTag="$SHA" \
  frontendAppName="$FRONTEND_APP_NAME" apiAppName="$API_APP_NAME" runtimeAppName="$RUNTIME_APP_NAME" \
  tenantId="$TENANT_ID" apiClientId="$API_CLIENT_ID" runtimeClientId="$RUNTIME_CLIENT_ID" \
  frontendUrl="$FRONTEND_URL" runtimeFqdn="$RUNTIME_FQDN" cosmosAccountName="$COSMOS_ACCOUNT_NAME" storageAccountName="$STORAGE_ACCOUNT_NAME" \
  azureOpenAiEndpoint="$AOAI_ENDPOINT" azureOpenAiDeployment="$AZURE_DEPLOYMENT")
echo "Running resource-group what-if before app deployment..."
"${APPS[@]/create/what-if}" --result-format ResourceIdOnly --only-show-errors
"${APPS[@]}" --only-show-errors >/dev/null

verify_inventory() {
  local apps resources assignments cosmos cosmos_sql_assignments storage frontend_principal api_principal runtime_principal subscription_id
  apps="$(az containerapp list -g "$RESOURCE_GROUP" -o json)"
  resources="$(az resource list -g "$RESOURCE_GROUP" -o json)"
  frontend_principal="$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-frontend-identity --query principalId -o tsv)"
  api_principal="$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-api-identity --query principalId -o tsv)"
  runtime_principal="$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-runtime-identity --query principalId -o tsv)"
  assignments="[$(az role assignment list --assignee "$frontend_principal" --all -o json),$(az role assignment list --assignee "$api_principal" --all -o json),$(az role assignment list --assignee "$runtime_principal" --all -o json)]"
  cosmos="$(az cosmosdb show -g "$RESOURCE_GROUP" -n "$COSMOS_ACCOUNT_NAME" -o json)"
  cosmos_sql_assignments="$(az cosmosdb sql role assignment list -g "$RESOURCE_GROUP" -a "$COSMOS_ACCOUNT_NAME" -o json)"
  storage="$(az storage account show -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT_NAME" -o json)"
  subscription_id="$(az account show --query id -o tsv)"
  APPS="$apps" RESOURCES="$resources" ASSIGNMENTS="$assignments" COSMOS="$cosmos" COSMOS_SQL_ASSIGNMENTS="$cosmos_sql_assignments" STORAGE="$storage" \
  RESOURCE_GROUP="$RESOURCE_GROUP" ACR_RESOURCE_GROUP="$ACR_RESOURCE_GROUP" AOAI_RESOURCE_GROUP="$AOAI_RESOURCE_GROUP" \
  ACR_NAME="$ACR_NAME" AOAI_NAME="$AOAI_NAME" COSMOS_ACCOUNT_NAME="$COSMOS_ACCOUNT_NAME" STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT_NAME" \
  FRONTEND_APP_NAME="$FRONTEND_APP_NAME" API_APP_NAME="$API_APP_NAME" RUNTIME_APP_NAME="$RUNTIME_APP_NAME" SHA="$SHA" SUBSCRIPTION_ID="$subscription_id" \
  FRONTEND_PRINCIPAL="$frontend_principal" API_PRINCIPAL="$api_principal" RUNTIME_PRINCIPAL="$runtime_principal" python3 - <<'PY'
import json
import os

apps = json.loads(os.environ['APPS'])
resources = json.loads(os.environ['RESOURCES'])
assignments = [assignment for principal_assignments in json.loads(os.environ['ASSIGNMENTS']) for assignment in principal_assignments]
cosmos = json.loads(os.environ['COSMOS'])
cosmos_sql_assignments = json.loads(os.environ['COSMOS_SQL_ASSIGNMENTS'])
storage = json.loads(os.environ['STORAGE'])
names = {os.environ['FRONTEND_APP_NAME'], os.environ['API_APP_NAME'], os.environ['RUNTIME_APP_NAME']}
if {app['name'] for app in apps} != names:
    raise SystemExit('unexpected Container App inventory')
expected = {
    os.environ['FRONTEND_APP_NAME']: (True, 'csa-workbench-frontend', 0.25, '0.5Gi'),
    os.environ['API_APP_NAME']: (True, 'csa-workbench-api', 0.5, '1Gi'),
    os.environ['RUNTIME_APP_NAME']: (False, 'csa-workbench-runtime', 1.0, '2Gi'),
}
for app in apps:
    external, image_name, cpu, memory = expected[app['name']]
    properties = app['properties']
    container = properties['template']['containers'][0]
    scale = properties['template']['scale']
    if properties['configuration']['ingress']['external'] != external or scale.get('minReplicas') != 0 or scale.get('maxReplicas') != 1:
        raise SystemExit(f"invalid ingress or scale: {app['name']}")
    container_resources = container['resources']
    if container['image'] != f"{os.environ['ACR_NAME']}.azurecr.io/{image_name}:{os.environ['SHA']}" or container_resources.get('cpu') != cpu or container_resources.get('memory') != memory:
        raise SystemExit(f"invalid immutable image or resource size: {app['name']}")
excluded = ('Microsoft.Search/', 'Microsoft.App/sessionPools', 'Microsoft.CognitiveServices/accounts/projects', 'Microsoft.Communication/', 'Microsoft.ApiManagement/', 'Microsoft.Cdn/', 'Microsoft.Network/natGateways', 'Microsoft.Insights/', 'Microsoft.OperationalInsights/')
if any(resource['type'].startswith(excluded) for resource in resources):
    raise SystemExit('excluded resource present in MVP resource group')
if cosmos['properties'].get('disableLocalAuth') is not True or cosmos['properties'].get('publicNetworkAccess') != 'Enabled':
    raise SystemExit('Cosmos authentication/network profile drifted')
if storage['properties'].get('allowSharedKeyAccess') is not False or storage['properties'].get('allowBlobPublicAccess') is not False:
    raise SystemExit('Storage authentication/public-blob profile drifted')
subscription_scope = f"/subscriptions/{os.environ['SUBSCRIPTION_ID']}".lower()
if any(item.get('scope', '').lower() == subscription_scope for item in assignments):
    raise SystemExit('subscription-scoped role assignment found')
subscription = os.environ['SUBSCRIPTION_ID']
expected_roles = {
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["ACR_RESOURCE_GROUP"]}/providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}', 'AcrPull', os.environ['FRONTEND_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["ACR_RESOURCE_GROUP"]}/providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}', 'AcrPull', os.environ['API_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["ACR_RESOURCE_GROUP"]}/providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}', 'AcrPull', os.environ['RUNTIME_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Storage/storageAccounts/{os.environ["STORAGE_ACCOUNT_NAME"]}', 'Storage Blob Data Contributor', os.environ['API_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["AOAI_RESOURCE_GROUP"]}/providers/Microsoft.CognitiveServices/accounts/{os.environ["AOAI_NAME"]}', 'Cognitive Services OpenAI User', os.environ['RUNTIME_PRINCIPAL']),
}
actual_roles = {(item.get('scope', ''), item.get('roleDefinitionName', ''), item.get('principalId', '')) for item in assignments}
if not expected_roles <= actual_roles:
    raise SystemExit('required resource-scoped managed-identity roles are missing')
cosmos_scope = f'/subscriptions/{subscription}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.DocumentDB/databaseAccounts/{os.environ["COSMOS_ACCOUNT_NAME"]}'
cosmos_role_definition = f'{cosmos_scope}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
expected_cosmos_roles = {
    (cosmos_role_definition, cosmos_scope, os.environ['API_PRINCIPAL']),
    (cosmos_role_definition, cosmos_scope, os.environ['RUNTIME_PRINCIPAL']),
}
actual_cosmos_roles = {(item.get('roleDefinitionId', ''), item.get('scope', ''), item.get('principalId', '')) for item in cosmos_sql_assignments}
if not expected_cosmos_roles <= actual_cosmos_roles:
    raise SystemExit('required Cosmos SQL data-plane role assignments are missing')
PY
}

verify_inventory
echo "Deployed immutable images: $ACR_SERVER/csa-workbench-{frontend,api,runtime}:$SHA"
for app in "$FRONTEND_APP_NAME" "$API_APP_NAME" "$RUNTIME_APP_NAME"; do
  az containerapp show -g "$RESOURCE_GROUP" -n "$app" --query '{name:name,image:properties.template.containers[0].image,ingress:properties.configuration.ingress.external,min:properties.template.scale.minReplicas,max:properties.template.scale.maxReplicas}' -o json
done
echo "Frontend: $FRONTEND_URL"
echo "API:      $API_URL"
echo "Runtime:  https://$RUNTIME_FQDN (internal ingress only)"
