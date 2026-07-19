#!/usr/bin/env bash
# Manual, guarded deployment for the CSA Workbench MVP.  This script is the
# imperative edge only: Bicep owns the Azure topology and Entra is configured
# through the narrow helper beside it.  Mutations require APPLY=true.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY="${APPLY:-false}"
LOCATION="${LOCATION:-eastus2}"
RESOURCE_GROUP="${RESOURCE_GROUP:-csa-workbench-rg}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-csa-workbench-env}"
FRONTEND_APP_NAME="${FRONTEND_APP_NAME:-csa-workbench-frontend}"
API_APP_NAME="${API_APP_NAME:-csa-workbench-api}"
RUNTIME_APP_NAME="${RUNTIME_APP_NAME:-csa-workbench-runtime}"
COSMOS_ACCOUNT_NAME="${COSMOS_ACCOUNT_NAME:-csaworkbench9fc05183}"
STORAGE_ACCOUNT_NAME="${STORAGE_ACCOUNT_NAME:-csaworkbench9fc05183}"
ACR_NAME="${ACR_NAME:-djgsharedacr}"
ACR_LOCATION="${ACR_LOCATION:-eastus}"
AOAI_NAME="${AOAI_NAME:-csa-workbench-ai}"
AZURE_DEPLOYMENT="${AZURE_DEPLOYMENT:-gpt-4.1}"
IDENTITY_MODE="${IDENTITY_MODE:-entra}"
DEMO_PASSWORD="${DEMO_PASSWORD:-}"
VNET_NAME='csa-workbench-vnet'
ACA_INFRASTRUCTURE_SUBNET_NAME='aca-infrastructure'
PRIVATE_ENDPOINT_SUBNET_NAME='private-endpoints'
COSMOS_PRIVATE_ENDPOINT_NAME='csa-workbench-cosmos-pe'
STORAGE_PRIVATE_ENDPOINT_NAME='csa-workbench-storage-pe'
COSMOS_PRIVATE_DNS_ZONE='privatelink.documents.azure.com'
STORAGE_PRIVATE_DNS_ZONE='privatelink.blob.core.windows.net'

truthy() { [[ "${1,,}" == "true" || "${1,,}" == "1" || "${1,,}" == "yes" ]]; }
fail() { echo "ERROR: $*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"; }

require az
require git
require python3
az account show --only-show-errors >/dev/null || fail "sign in with az login before continuing"
TENANT_ID="$(az account show --query tenantId -o tsv)"
[[ -n "$TENANT_ID" ]] || fail "the current Azure account has no tenant id"
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
[[ -n "$SUBSCRIPTION_ID" ]] || fail "the current Azure account has no subscription id"
az bicep version >/dev/null || fail "Azure CLI Bicep support is required"

SHA="$(git rev-parse HEAD)"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "deployment requires a full 40-character Git SHA"
if [[ -n "$(git status --porcelain)" ]]; then
  fail "deployment requires a clean worktree so images and SHA agree"
fi
[[ "$COSMOS_ACCOUNT_NAME" =~ ^[a-z0-9]{3,44}$ ]] || fail "invalid Cosmos account name: $COSMOS_ACCOUNT_NAME"
[[ "$STORAGE_ACCOUNT_NAME" =~ ^[a-z0-9]{3,24}$ ]] || fail "invalid Storage account name: $STORAGE_ACCOUNT_NAME"
[[ "$ACR_NAME" =~ ^[a-zA-Z0-9]{5,50}$ ]] || fail "invalid Container Registry name: $ACR_NAME"
[[ "$AOAI_NAME" =~ ^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$ ]] || fail "invalid Azure OpenAI account name: $AOAI_NAME"
[[ "$IDENTITY_MODE" == "entra" || "$IDENTITY_MODE" == "demo" ]] || fail "IDENTITY_MODE must be 'entra' or 'demo'"
[[ "$IDENTITY_MODE" != "demo" || -n "$DEMO_PASSWORD" ]] || fail "DEMO_PASSWORD is required when IDENTITY_MODE=demo"

echo "CSA Workbench Azure MVP ($SHA)"
echo "Target: $RESOURCE_GROUP in $LOCATION; APPLY=$APPLY"

GROUP_EXISTS="$(az group exists -n "$RESOURCE_GROUP" -o tsv)" || fail "cannot determine whether resource group $RESOURCE_GROUP exists"
case "$GROUP_EXISTS" in
  true) GOVERNANCE_NSG_INVENTORY="$(az network nsg list -g "$RESOURCE_GROUP" -o json)" || fail "cannot list tenant-governance NSGs" ;;
  false) GOVERNANCE_NSG_INVENTORY='[]' ;;
  *) fail "resource group existence check returned an invalid value" ;;
esac
GOVERNANCE_NSGS="$(python3 infra/governance_nsg.py --subscription-id "$SUBSCRIPTION_ID" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" <<<"$GOVERNANCE_NSG_INVENTORY")" || fail "tenant-governance NSG preflight failed"
ACA_INFRASTRUCTURE_NSG_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["aca_nsg_id"])' <<<"$GOVERNANCE_NSGS")"
PRIVATE_ENDPOINT_NSG_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["private_endpoint_nsg_id"])' <<<"$GOVERNANCE_NSGS")"

az bicep build --file infra/foundation.bicep --outfile /tmp/csa-workbench-foundation.json
az bicep build --file infra/apps.bicep --outfile /tmp/csa-workbench-apps.json

FOUNDATION_DEPLOYMENT_NAME="csa-foundation-${SHA:0:12}"
FOUNDATION=(az deployment sub create --name "$FOUNDATION_DEPLOYMENT_NAME" --location "$LOCATION"
  --template-file infra/foundation.bicep
  --parameters location="$LOCATION" resourceGroupName="$RESOURCE_GROUP" environmentName="$ENVIRONMENT_NAME"
  cosmosAccountName="$COSMOS_ACCOUNT_NAME" storageAccountName="$STORAGE_ACCOUNT_NAME"
  acrName="$ACR_NAME" acrLocation="$ACR_LOCATION"
  azureOpenAiName="$AOAI_NAME" azureOpenAiDeploymentName="$AZURE_DEPLOYMENT"
  acaInfrastructureNsgId="$ACA_INFRASTRUCTURE_NSG_ID" privateEndpointNsgId="$PRIVATE_ENDPOINT_NSG_ID")

RECOVERY_STATE=''
RECOVERY_ENVIRONMENT_ID=''

recovery_preflight() {
  local group_exists environments environment_json apps_json subscription_id expected_subnet_id recovery_result
  group_exists="$(az group exists -n "$RESOURCE_GROUP" -o tsv)" || fail "cannot determine whether resource group $RESOURCE_GROUP exists"
  case "$group_exists" in
    true) ;;
    false) RECOVERY_STATE='absent'; return ;;
    *) fail "resource group existence check returned an invalid value" ;;
  esac
  environments="$(az containerapp env list -g "$RESOURCE_GROUP" -o json)" || fail "cannot list Container Apps environments in $RESOURCE_GROUP"
  recovery_result="$(ENVIRONMENT_NAME="$ENVIRONMENT_NAME" python3 -c 'import json,os,sys; values=json.load(sys.stdin); matches=[value for value in values if isinstance(value,dict) and value.get("name")==os.environ["ENVIRONMENT_NAME"]]; sys.exit("malformed Container Apps environment inventory" if not isinstance(values,list) or len(matches)>1 or (matches and not isinstance(matches[0].get("id"),str)) else 0); print("present" if matches else "absent")' <<<"$environments")" || fail "Container Apps environment inventory validation failed"
  if [[ "$recovery_result" == 'absent' ]]; then
    RECOVERY_STATE='absent'
    return
  fi
  environment_json="$(az containerapp env show -g "$RESOURCE_GROUP" -n "$ENVIRONMENT_NAME" -o json)" || fail "cannot fetch existing Container Apps environment $ENVIRONMENT_NAME"
  apps_json="$(az containerapp list -g "$RESOURCE_GROUP" -o json)" || fail "cannot list Container Apps in $RESOURCE_GROUP"
  subscription_id="$(az account show --query id -o tsv)" || fail "cannot determine subscription id for recovery preflight"
  [[ -n "$subscription_id" ]] || fail "subscription id is required for recovery preflight"
  expected_subnet_id="/subscriptions/${subscription_id}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Network/virtualNetworks/${VNET_NAME}/subnets/${ACA_INFRASTRUCTURE_SUBNET_NAME}"
  recovery_result="$(ENVIRONMENT_NAME="$ENVIRONMENT_NAME" EXPECTED_SUBNET_ID="$expected_subnet_id" FRONTEND_APP_NAME="$FRONTEND_APP_NAME" API_APP_NAME="$API_APP_NAME" RUNTIME_APP_NAME="$RUNTIME_APP_NAME" ENVIRONMENT_JSON="$environment_json" APPS_JSON="$apps_json" python3 -c 'import json,os; fail=lambda message: (_ for _ in ()).throw(SystemExit(message)); e=json.loads(os.environ["ENVIRONMENT_JSON"]); apps=json.loads(os.environ["APPS_JSON"]); (isinstance(e,dict) and e.get("name")==os.environ["ENVIRONMENT_NAME"] and isinstance(e.get("id"),str) and e["id"]) or fail("environment name/id mismatch"); isinstance(apps,list) or fail("malformed app inventory"); all(isinstance(a,dict) and isinstance(a.get("name"),str) and a["name"] and isinstance(a.get("properties",{}).get("managedEnvironmentId"),str) and a["properties"]["managedEnvironmentId"] for a in apps) or fail("app name/managedEnvironmentId missing"); len({a["name"] for a in apps})==len(apps) or fail("duplicate app name"); p=e.get("properties",{}); profiles=p.get("workloadProfiles") if isinstance(p,dict) else None; subnet=p.get("vnetConfiguration",{}).get("infrastructureSubnetId") if isinstance(p.get("vnetConfiguration",{}),dict) else None; compatible=isinstance(subnet,str) and subnet.lower()==os.environ["EXPECTED_SUBNET_ID"].lower() and isinstance(profiles,list) and len(profiles)==1 and profiles[0].get("name")=="Consumption" and profiles[0].get("workloadProfileType")=="Consumption"; attached={a["name"] for a in apps if a["properties"]["managedEnvironmentId"].lower()==e["id"].lower()}; expected={os.environ["FRONTEND_APP_NAME"],os.environ["API_APP_NAME"],os.environ["RUNTIME_APP_NAME"]}; (compatible or attached==expected) or fail("incompatible environment app inventory is unsafe"); print(("compatible" if compatible else "incompatible")+"|"+e["id"])')" || fail "recovery preflight validation failed"
  IFS='|' read -r RECOVERY_STATE RECOVERY_ENVIRONMENT_ID <<<"$recovery_result"
  [[ "$RECOVERY_STATE" == 'compatible' || "$RECOVERY_STATE" == 'incompatible' ]] || fail "recovery preflight returned an invalid state"
  [[ -n "$RECOVERY_ENVIRONMENT_ID" ]] || fail "recovery preflight did not return environment id"
}

remove_incompatible_environment() {
  local app_name
  [[ "$RECOVERY_STATE" == 'incompatible' ]] || return
  echo "Removing approved Container Apps environment $ENVIRONMENT_NAME before private-network foundation recovery."
  for app_name in "$FRONTEND_APP_NAME" "$API_APP_NAME" "$RUNTIME_APP_NAME"; do
    az containerapp delete -g "$RESOURCE_GROUP" -n "$app_name" --yes --only-show-errors
  done
  az containerapp env delete -g "$RESOURCE_GROUP" -n "$ENVIRONMENT_NAME" --yes --only-show-errors
}

recovery_preflight
if [[ "$RECOVERY_STATE" == 'incompatible' ]]; then
  if ! truthy "$APPLY"; then
    echo "Dry run requires deletion of the approved incompatible Container Apps environment and its three apps; set APPLY=true. No foundation what-if was run."
    exit 0
  fi
  remove_incompatible_environment
fi

echo "Running subscription what-if (no Azure or Entra mutation)..."
"${FOUNDATION[@]/create/what-if}" --result-format ResourceIdOnly --only-show-errors

if ! truthy "$APPLY"; then
  echo "Dry run complete. Set APPLY=true to build images and create/update Azure or Entra resources."
  exit 0
fi

"${FOUNDATION[@]}" --only-show-errors >/dev/null
ENVIRONMENT_DOMAIN="$(az deployment sub show --name "$FOUNDATION_DEPLOYMENT_NAME" --query properties.outputs.environmentDefaultDomain.value -o tsv)"
[[ -n "$ENVIRONMENT_DOMAIN" ]] || fail "foundation deployment did not return the Container Apps default domain"
ACR_SERVER="$(az deployment sub show --name "$FOUNDATION_DEPLOYMENT_NAME" --query properties.outputs.acrLoginServer.value -o tsv)"
[[ -n "$ACR_SERVER" ]] || fail "foundation deployment did not return the Container Registry login server"
AOAI_ENDPOINT="$(az deployment sub show --name "$FOUNDATION_DEPLOYMENT_NAME" --query properties.outputs.azureOpenAiEndpoint.value -o tsv)"
[[ -n "$AOAI_ENDPOINT" ]] || fail "foundation deployment did not return the Azure OpenAI endpoint"
FRONTEND_URL="https://${FRONTEND_APP_NAME}.${ENVIRONMENT_DOMAIN}"
API_URL="https://${API_APP_NAME}.${ENVIRONMENT_DOMAIN}"
RUNTIME_FQDN="${RUNTIME_APP_NAME}.internal.${ENVIRONMENT_DOMAIN}"

ENTRA_JSON="$(python3 infra/entra.py --tenant-id "$TENANT_ID" --frontend-redirect-uri "$FRONTEND_URL" --api-uami-principal-id "$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-api-identity --query principalId -o tsv)")"
API_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["api_client_id"])' <<<"$ENTRA_JSON")"
WEB_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["web_client_id"])' <<<"$ENTRA_JSON")"
RUNTIME_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runtime_client_id"])' <<<"$ENTRA_JSON")"

AOAI_ENDPOINT="${AOAI_ENDPOINT%/}/openai/v1/"
az acr build -r "$ACR_NAME" -g "$RESOURCE_GROUP" -t "csa-workbench-api:$SHA" -f Dockerfile . --only-show-errors
az acr build -r "$ACR_NAME" -g "$RESOURCE_GROUP" -t "csa-workbench-runtime:$SHA" -f session-container/Dockerfile . --only-show-errors
az acr build -r "$ACR_NAME" -g "$RESOURCE_GROUP" -t "csa-workbench-frontend:$SHA" -f frontend/Dockerfile frontend \
  --build-arg "NEXT_PUBLIC_API_URL=$API_URL" \
  --build-arg "NEXT_PUBLIC_IDENTITY_MODE=$IDENTITY_MODE" \
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
  azureOpenAiEndpoint="$AOAI_ENDPOINT" azureOpenAiDeployment="$AZURE_DEPLOYMENT" \
  identityMode="$IDENTITY_MODE" demoPassword="$DEMO_PASSWORD")
echo "Running resource-group what-if before app deployment..."
"${APPS[@]/create/what-if}" --result-format ResourceIdOnly --only-show-errors
"${APPS[@]}" --only-show-errors >/dev/null

verify_inventory() {
  local apps resources network_security_groups assignments acr azure_open_ai azure_open_ai_deployments cosmos cosmos_sql_assignments storage managed_environment vnet private_endpoints private_dns_zones cosmos_dns_links storage_dns_links cosmos_dns_groups storage_dns_groups cosmos_dns_records storage_dns_records event_topics event_topic_name event_subscriptions frontend_principal api_principal runtime_principal subscription_id
  apps="$(az containerapp list -g "$RESOURCE_GROUP" -o json)"
  resources="$(az resource list -g "$RESOURCE_GROUP" -o json)"
  network_security_groups="$(az network nsg list -g "$RESOURCE_GROUP" -o json)"
  frontend_principal="$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-frontend-identity --query principalId -o tsv)"
  api_principal="$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-api-identity --query principalId -o tsv)"
  runtime_principal="$(az identity show -g "$RESOURCE_GROUP" -n csa-workbench-runtime-identity --query principalId -o tsv)"
  assignments="[$(az role assignment list --assignee "$frontend_principal" --all -o json),$(az role assignment list --assignee "$api_principal" --all -o json),$(az role assignment list --assignee "$runtime_principal" --all -o json)]"
  acr="$(az acr show -g "$RESOURCE_GROUP" -n "$ACR_NAME" -o json)"
  azure_open_ai="$(az cognitiveservices account show -g "$RESOURCE_GROUP" -n "$AOAI_NAME" -o json)"
  azure_open_ai_deployments="$(az cognitiveservices account deployment list -g "$RESOURCE_GROUP" -n "$AOAI_NAME" -o json)"
  cosmos="$(az cosmosdb show -g "$RESOURCE_GROUP" -n "$COSMOS_ACCOUNT_NAME" -o json)"
  cosmos_sql_assignments="$(az cosmosdb sql role assignment list -g "$RESOURCE_GROUP" -a "$COSMOS_ACCOUNT_NAME" -o json)"
  storage="$(az storage account show -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT_NAME" -o json)"
  managed_environment="$(az containerapp env show -g "$RESOURCE_GROUP" -n "$ENVIRONMENT_NAME" -o json)"
  vnet="$(az network vnet show -g "$RESOURCE_GROUP" -n "$VNET_NAME" -o json)"
  private_endpoints="$(az network private-endpoint list -g "$RESOURCE_GROUP" -o json)"
  private_dns_zones="$(az network private-dns zone list -g "$RESOURCE_GROUP" -o json)"
  cosmos_dns_links="$(az network private-dns link vnet list -g "$RESOURCE_GROUP" --zone-name "$COSMOS_PRIVATE_DNS_ZONE" -o json)"
  storage_dns_links="$(az network private-dns link vnet list -g "$RESOURCE_GROUP" --zone-name "$STORAGE_PRIVATE_DNS_ZONE" -o json)"
  cosmos_dns_groups="$(az network private-endpoint dns-zone-group list -g "$RESOURCE_GROUP" --endpoint-name "$COSMOS_PRIVATE_ENDPOINT_NAME" -o json)"
  storage_dns_groups="$(az network private-endpoint dns-zone-group list -g "$RESOURCE_GROUP" --endpoint-name "$STORAGE_PRIVATE_ENDPOINT_NAME" -o json)"
  cosmos_dns_records="$(az network private-dns record-set a list -g "$RESOURCE_GROUP" -z "$COSMOS_PRIVATE_DNS_ZONE" -o json)"
  storage_dns_records="$(az network private-dns record-set a list -g "$RESOURCE_GROUP" -z "$STORAGE_PRIVATE_DNS_ZONE" -o json)"
  subscription_id="$(az account show --query id -o tsv)"
  event_topics="$(az eventgrid system-topic list -g "$RESOURCE_GROUP" -o json)"
  event_topic_name="$(python3 -c 'import json,sys; topics=json.load(sys.stdin); print(topics[0]["name"] if isinstance(topics,list) and len(topics)==1 and isinstance(topics[0],dict) and isinstance(topics[0].get("name"),str) else "")' <<<"$event_topics")"
  if [[ -n "$event_topic_name" ]]; then
    event_subscriptions="$(az eventgrid system-topic event-subscription list -g "$RESOURCE_GROUP" --system-topic-name "$event_topic_name" -o json)"
  else
    event_subscriptions='[]'
  fi
  APPS="$apps" RESOURCES="$resources" NETWORK_SECURITY_GROUPS="$network_security_groups" ASSIGNMENTS="$assignments" ACR="$acr" AZURE_OPEN_AI="$azure_open_ai" AZURE_OPEN_AI_DEPLOYMENTS="$azure_open_ai_deployments" COSMOS="$cosmos" COSMOS_SQL_ASSIGNMENTS="$cosmos_sql_assignments" STORAGE="$storage" MANAGED_ENVIRONMENT="$managed_environment" VNET="$vnet" PRIVATE_ENDPOINTS="$private_endpoints" PRIVATE_DNS_ZONES="$private_dns_zones" COSMOS_DNS_LINKS="$cosmos_dns_links" STORAGE_DNS_LINKS="$storage_dns_links" COSMOS_DNS_GROUPS="$cosmos_dns_groups" STORAGE_DNS_GROUPS="$storage_dns_groups" COSMOS_DNS_RECORDS="$cosmos_dns_records" STORAGE_DNS_RECORDS="$storage_dns_records" EVENT_TOPICS="$event_topics" EVENT_SUBSCRIPTIONS="$event_subscriptions" \
  RESOURCE_GROUP="$RESOURCE_GROUP" ACR_NAME="$ACR_NAME" ACR_LOCATION="$ACR_LOCATION" AOAI_NAME="$AOAI_NAME" AZURE_DEPLOYMENT="$AZURE_DEPLOYMENT" COSMOS_ACCOUNT_NAME="$COSMOS_ACCOUNT_NAME" STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT_NAME" \
  FRONTEND_APP_NAME="$FRONTEND_APP_NAME" API_APP_NAME="$API_APP_NAME" RUNTIME_APP_NAME="$RUNTIME_APP_NAME" SHA="$SHA" SUBSCRIPTION_ID="$subscription_id" \
  FRONTEND_PRINCIPAL="$frontend_principal" API_PRINCIPAL="$api_principal" RUNTIME_PRINCIPAL="$runtime_principal" LOCATION="$LOCATION" ENVIRONMENT_NAME="$ENVIRONMENT_NAME" VNET_NAME="$VNET_NAME" ACA_INFRASTRUCTURE_SUBNET_NAME="$ACA_INFRASTRUCTURE_SUBNET_NAME" PRIVATE_ENDPOINT_SUBNET_NAME="$PRIVATE_ENDPOINT_SUBNET_NAME" COSMOS_PRIVATE_ENDPOINT_NAME="$COSMOS_PRIVATE_ENDPOINT_NAME" STORAGE_PRIVATE_ENDPOINT_NAME="$STORAGE_PRIVATE_ENDPOINT_NAME" COSMOS_PRIVATE_DNS_ZONE="$COSMOS_PRIVATE_DNS_ZONE" STORAGE_PRIVATE_DNS_ZONE="$STORAGE_PRIVATE_DNS_ZONE" python3 - <<'PY'
import json
import os
import ipaddress

apps = json.loads(os.environ['APPS'])
resources = json.loads(os.environ['RESOURCES'])
network_security_groups = json.loads(os.environ['NETWORK_SECURITY_GROUPS'])
assignments = [assignment for principal_assignments in json.loads(os.environ['ASSIGNMENTS']) for assignment in principal_assignments]
acr = json.loads(os.environ['ACR'])
azure_open_ai = json.loads(os.environ['AZURE_OPEN_AI'])
azure_open_ai_deployments = json.loads(os.environ['AZURE_OPEN_AI_DEPLOYMENTS'])
cosmos = json.loads(os.environ['COSMOS'])
cosmos_sql_assignments = json.loads(os.environ['COSMOS_SQL_ASSIGNMENTS'])
storage = json.loads(os.environ['STORAGE'])
managed_environment = json.loads(os.environ['MANAGED_ENVIRONMENT'])
vnet = json.loads(os.environ['VNET'])
private_endpoints = json.loads(os.environ['PRIVATE_ENDPOINTS'])
private_dns_zones = json.loads(os.environ['PRIVATE_DNS_ZONES'])
cosmos_dns_links = json.loads(os.environ['COSMOS_DNS_LINKS'])
storage_dns_links = json.loads(os.environ['STORAGE_DNS_LINKS'])
cosmos_dns_groups = json.loads(os.environ['COSMOS_DNS_GROUPS'])
storage_dns_groups = json.loads(os.environ['STORAGE_DNS_GROUPS'])
cosmos_dns_records = json.loads(os.environ['COSMOS_DNS_RECORDS'])
storage_dns_records = json.loads(os.environ['STORAGE_DNS_RECORDS'])
event_topics = json.loads(os.environ['EVENT_TOPICS'])
event_subscriptions = json.loads(os.environ['EVENT_SUBSCRIPTIONS'])
names = {os.environ['FRONTEND_APP_NAME'], os.environ['API_APP_NAME'], os.environ['RUNTIME_APP_NAME']}
if {app['name'] for app in apps} != names:
    raise SystemExit('unexpected Container App inventory')
expected = {
    os.environ['FRONTEND_APP_NAME']: (True, 'csa-workbench-frontend', 0.25, '0.5Gi', 3000),
    os.environ['API_APP_NAME']: (True, 'csa-workbench-api', 0.5, '1Gi', 8000),
    os.environ['RUNTIME_APP_NAME']: (False, 'csa-workbench-runtime', 1.0, '2Gi', 8080),
}
for app in apps:
    external, image_name, cpu, memory, target_port = expected[app['name']]
    properties = app['properties']
    container = properties['template']['containers'][0]
    scale = properties['template']['scale']
    ingress = properties['configuration']['ingress']
    if properties.get('provisioningState') != 'Succeeded' or properties.get('workloadProfileName') != 'Consumption' or ingress['external'] != external or ingress.get('targetPort') != target_port or ingress.get('transport', '').lower() != 'auto' or scale.get('minReplicas') != 0 or scale.get('maxReplicas') != 1:
        raise SystemExit(f"invalid ingress or scale: {app['name']}")
    container_resources = container['resources']
    if container['image'] != f"{os.environ['ACR_NAME']}.azurecr.io/{image_name}:{os.environ['SHA']}" or container_resources.get('cpu') != cpu or container_resources.get('memory') != memory:
        raise SystemExit(f"invalid immutable image or resource size: {app['name']}")
    registries = properties.get('configuration', {}).get('registries')
    if not isinstance(registries, list) or len(registries) != 1 or registries[0].get('server') != f"{os.environ['ACR_NAME']}.azurecr.io":
        raise SystemExit(f"invalid Container Registry binding: {app['name']}")
    if app['name'] == os.environ['RUNTIME_APP_NAME']:
        runtime_env = {item.get('name'): item.get('value') for item in container.get('env', []) if isinstance(item, dict)}
        account_endpoint = azure_open_ai.get('properties', {}).get('endpoint')
        expected_endpoint = f"{account_endpoint.rstrip('/')}/openai/v1/" if isinstance(account_endpoint, str) and account_endpoint else ''
        if runtime_env.get('AZURE_ENDPOINT') != expected_endpoint or runtime_env.get('AZURE_DEPLOYMENT') != os.environ['AZURE_DEPLOYMENT']:
            raise SystemExit('runtime Azure OpenAI binding drifted')
excluded = ('Microsoft.Search/', 'Microsoft.App/sessionPools', 'Microsoft.CognitiveServices/accounts/projects', 'Microsoft.Communication/', 'Microsoft.ApiManagement/', 'Microsoft.Cdn/', 'Microsoft.Network/natGateways', 'Microsoft.Insights/', 'Microsoft.OperationalInsights/')
if any(resource['type'].startswith(excluded) for resource in resources):
    raise SystemExit('excluded resource present in MVP resource group')
forbidden_network_types = ('Microsoft.Network/azureFirewalls', 'Microsoft.Network/virtualNetworkGateways', 'Microsoft.Network/routeTables', 'Microsoft.Network/natGateways')
if any(resource.get('type') in forbidden_network_types for resource in resources):
    raise SystemExit('forbidden network resource present in MVP resource group')
if acr.get('name') != os.environ['ACR_NAME'] or acr.get('location', '').lower() != os.environ['ACR_LOCATION'].lower() or acr.get('provisioningState') != 'Succeeded' or acr.get('sku', {}).get('name') != 'Basic' or acr.get('adminUserEnabled') is not False or acr.get('publicNetworkAccess') != 'Enabled':
    raise SystemExit('Container Registry profile drifted')
if azure_open_ai.get('name') != os.environ['AOAI_NAME'] or azure_open_ai.get('location', '').lower() != os.environ['LOCATION'].lower() or azure_open_ai.get('kind') != 'OpenAI' or azure_open_ai.get('sku', {}).get('name') != 'S0' or azure_open_ai.get('properties', {}).get('provisioningState') != 'Succeeded' or azure_open_ai.get('properties', {}).get('disableLocalAuth') is not True or azure_open_ai.get('properties', {}).get('publicNetworkAccess') != 'Enabled' or azure_open_ai.get('properties', {}).get('customSubDomainName') != os.environ['AOAI_NAME']:
    raise SystemExit('Azure OpenAI account profile drifted')
if not isinstance(azure_open_ai_deployments, list) or len(azure_open_ai_deployments) != 1:
    raise SystemExit('Azure OpenAI deployment inventory drifted')
azure_open_ai_deployment = azure_open_ai_deployments[0]
azure_open_ai_model = azure_open_ai_deployment.get('properties', {}).get('model', {})
if azure_open_ai_deployment.get('name') != os.environ['AZURE_DEPLOYMENT'] or azure_open_ai_deployment.get('properties', {}).get('provisioningState') != 'Succeeded' or azure_open_ai_model.get('format') != 'OpenAI' or azure_open_ai_model.get('name') != 'gpt-4.1' or azure_open_ai_model.get('version') != '2025-04-14' or azure_open_ai_deployment.get('sku', {}).get('name') != 'Standard' or azure_open_ai_deployment.get('sku', {}).get('capacity') != 10:
    raise SystemExit('Azure OpenAI deployment profile drifted')
if cosmos.get('disableLocalAuth') is not True or cosmos.get('publicNetworkAccess') != 'Disabled':
    raise SystemExit('Cosmos authentication/network profile drifted')
if storage.get('publicNetworkAccess') != 'Disabled' or storage.get('allowSharedKeyAccess') is not False or storage.get('allowBlobPublicAccess') is not False:
    raise SystemExit('Storage authentication/public-blob profile drifted')
if vnet.get('name') != os.environ['VNET_NAME'] or vnet.get('provisioningState') != 'Succeeded' or vnet.get('addressSpace', {}).get('addressPrefixes') != ['10.42.0.0/24']:
    raise SystemExit('virtual network profile drifted')
subnets = {subnet.get('name'): subnet for subnet in vnet.get('subnets', [])}
if set(subnets) != {os.environ['ACA_INFRASTRUCTURE_SUBNET_NAME'], os.environ['PRIVATE_ENDPOINT_SUBNET_NAME']}:
    raise SystemExit('unexpected subnet inventory')
aca_subnet = subnets[os.environ['ACA_INFRASTRUCTURE_SUBNET_NAME']]
if aca_subnet.get('provisioningState') != 'Succeeded' or aca_subnet.get('addressPrefix') != '10.42.0.0/27' or [delegation.get('serviceName') for delegation in aca_subnet.get('delegations', [])] != ['Microsoft.App/environments']:
    raise SystemExit('ACA infrastructure subnet profile drifted')
private_endpoint_subnet = subnets[os.environ['PRIVATE_ENDPOINT_SUBNET_NAME']]
if private_endpoint_subnet.get('provisioningState') != 'Succeeded' or private_endpoint_subnet.get('addressPrefix') != '10.42.0.32/27' or private_endpoint_subnet.get('privateEndpointNetworkPolicies') != 'Disabled':
    raise SystemExit('private endpoint subnet profile drifted')
environment_id = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.App/managedEnvironments/{os.environ["ENVIRONMENT_NAME"]}'.lower()
if any(app.get('properties', {}).get('managedEnvironmentId', '').lower() != environment_id for app in apps):
    raise SystemExit('Container App environment profile drifted')
vnet_id = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Network/virtualNetworks/{os.environ["VNET_NAME"]}'.lower()
aca_infrastructure_subnet_id = f'{vnet_id}/subnets/{os.environ["ACA_INFRASTRUCTURE_SUBNET_NAME"]}'
environment_properties = managed_environment.get('properties', {})
environment_profiles = environment_properties.get('workloadProfiles')
if managed_environment.get('name') != os.environ['ENVIRONMENT_NAME'] or managed_environment.get('properties', {}).get('provisioningState') != 'Succeeded' or environment_properties.get('vnetConfiguration', {}).get('infrastructureSubnetId', '').lower() != aca_infrastructure_subnet_id or not isinstance(environment_profiles, list) or len(environment_profiles) != 1 or environment_profiles[0].get('name') != 'Consumption' or environment_profiles[0].get('workloadProfileType') != 'Consumption':
    raise SystemExit('Container Apps environment private-network profile drifted')
private_endpoint_subnet_id = f'{vnet_id}/subnets/{os.environ["PRIVATE_ENDPOINT_SUBNET_NAME"]}'
governance_nsgs = {
    'csa-workbench-vnet-aca-infrastructure-nsg-eastus2': (aca_infrastructure_subnet_id, True),
    'csa-workbench-vnet-private-endpoints-nsg-eastus2': (private_endpoint_subnet_id, False),
}
governance_nsg_location = 'eastus2'
if not isinstance(network_security_groups, list):
    raise SystemExit('tenant-governance NSG inventory is malformed')
if network_security_groups:
    if len(network_security_groups) != len(governance_nsgs):
        raise SystemExit('tenant-governance NSG inventory drifted')
    nsgs_by_name = {}
    for nsg in network_security_groups:
        name = nsg.get('name') if isinstance(nsg, dict) else None
        if not isinstance(name, str) or not name:
            raise SystemExit('tenant-governance NSG inventory is malformed')
        normalized_name = name.lower()
        if normalized_name in nsgs_by_name:
            raise SystemExit('tenant-governance NSG inventory drifted')
        nsgs_by_name[normalized_name] = nsg
    if set(nsgs_by_name) != set(governance_nsgs):
        raise SystemExit('tenant-governance NSG inventory drifted')
    for name, (expected_subnet_id, aca_attachment_is_optional) in governance_nsgs.items():
        nsg = nsgs_by_name[name]
        location = nsg.get('location')
        if not isinstance(location, str) or location.lower() != governance_nsg_location or nsg.get('provisioningState') != 'Succeeded' or nsg.get('securityRules') != []:
            raise SystemExit(f'tenant-governance NSG profile drifted: {name}')
        network_interfaces = nsg.get('networkInterfaces')
        if network_interfaces is not None and not isinstance(network_interfaces, list):
            raise SystemExit(f'tenant-governance NSG network-interface associations are malformed: {name}')
        if isinstance(network_interfaces, list) and network_interfaces:
            raise SystemExit(f'tenant-governance NSG network-interface associations drifted: {name}')
        associations = nsg.get('subnets')
        if associations is None:
            associations = []
        elif not isinstance(associations, list):
            raise SystemExit(f'tenant-governance NSG subnet associations are malformed: {name}')
        subnet_ids = []
        for association in associations:
            subnet_id = association.get('id') if isinstance(association, dict) else None
            if not isinstance(subnet_id, str) or not subnet_id:
                raise SystemExit(f'tenant-governance NSG subnet associations are malformed: {name}')
            subnet_ids.append(subnet_id.rstrip('/').lower())
        if aca_attachment_is_optional and subnet_ids not in ([], [expected_subnet_id]):
            raise SystemExit(f'tenant-governance NSG subnet associations drifted: {name}')
        if not aca_attachment_is_optional and subnet_ids != [expected_subnet_id]:
            raise SystemExit(f'tenant-governance NSG subnet associations drifted: {name}')
expected_private_endpoints = {
    os.environ['COSMOS_PRIVATE_ENDPOINT_NAME']: (f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.DocumentDB/databaseAccounts/{os.environ["COSMOS_ACCOUNT_NAME"]}'.lower(), 'Sql'),
    os.environ['STORAGE_PRIVATE_ENDPOINT_NAME']: (f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Storage/storageAccounts/{os.environ["STORAGE_ACCOUNT_NAME"]}'.lower(), 'blob'),
}
if {endpoint.get('name') for endpoint in private_endpoints} != set(expected_private_endpoints):
    raise SystemExit('unexpected private endpoint inventory')
for endpoint in private_endpoints:
    target_id, group_id = expected_private_endpoints[endpoint['name']]
    connections = endpoint.get('privateLinkServiceConnections', [])
    if endpoint.get('provisioningState') != 'Succeeded' or endpoint.get('subnet', {}).get('id', '').lower() != private_endpoint_subnet_id or len(connections) != 1 or connections[0].get('provisioningState') != 'Succeeded' or connections[0].get('privateLinkServiceId', '').lower() != target_id or connections[0].get('groupIds') != [group_id] or connections[0].get('privateLinkServiceConnectionState', {}).get('status', '').lower() != 'approved':
        raise SystemExit(f'private endpoint profile drifted: {endpoint["name"]}')
expected_zones = {os.environ['COSMOS_PRIVATE_DNS_ZONE'], os.environ['STORAGE_PRIVATE_DNS_ZONE']}
if {zone.get('name') for zone in private_dns_zones} != expected_zones:
    raise SystemExit('unexpected private DNS zone inventory')
def verify_dns_link(links, zone_name):
    if len(links) != 1 or links[0].get('name') != 'csa-workbench-vnet-link':
        raise SystemExit(f'private DNS VNet link inventory drifted: {zone_name}')
    if links[0].get('provisioningState') != 'Succeeded' or links[0].get('virtualNetworkLinkState') != 'Completed' or links[0].get('registrationEnabled') is not False or links[0].get('virtualNetwork', {}).get('id', '').lower() != vnet_id:
        raise SystemExit(f'private DNS VNet link profile drifted: {zone_name}')
verify_dns_link(cosmos_dns_links, os.environ['COSMOS_PRIVATE_DNS_ZONE'])
verify_dns_link(storage_dns_links, os.environ['STORAGE_PRIVATE_DNS_ZONE'])
def verify_dns_group(groups, zone_name, expected_records):
    if len(groups) != 1 or groups[0].get('name') != 'default':
        raise SystemExit(f'private DNS zone group inventory drifted: {zone_name}')
    configs = groups[0].get('privateDnsZoneConfigs', [])
    expected_zone_id = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Network/privateDnsZones/{zone_name}'.lower()
    if groups[0].get('provisioningState') != 'Succeeded' or len(configs) != 1 or configs[0].get('privateDnsZoneId', '').lower() != expected_zone_id:
        raise SystemExit(f'private DNS zone group profile drifted: {zone_name}')
    record_sets = configs[0].get('recordSets')
    if not isinstance(record_sets, list) or {record.get('recordSetName') for record in record_sets} != expected_records:
        raise SystemExit(f'private DNS zone group record-set inventory drifted: {zone_name}')
    result = {}
    for record in record_sets:
        addresses = record.get('ipAddresses')
        if record.get('provisioningState') != 'Succeeded' or not isinstance(addresses, list) or len(addresses) != 1:
            raise SystemExit(f'private DNS zone group record-set profile drifted: {zone_name}')
        result[record['recordSetName']] = addresses[0]
    return result
cosmos_group_records = verify_dns_group(cosmos_dns_groups, os.environ['COSMOS_PRIVATE_DNS_ZONE'], {os.environ['COSMOS_ACCOUNT_NAME'], f'{os.environ["COSMOS_ACCOUNT_NAME"]}-{os.environ["LOCATION"]}'})
storage_group_records = verify_dns_group(storage_dns_groups, os.environ['STORAGE_PRIVATE_DNS_ZONE'], {os.environ['STORAGE_ACCOUNT_NAME']})
private_network = ipaddress.ip_network('10.42.0.32/27')
def verify_records(records, required_names, zone_name):
    by_name = {record.get('name'): record for record in records}
    if set(by_name) != required_names:
        raise SystemExit(f'private DNS A-record inventory drifted: {zone_name}')
    result = {}
    for record in by_name.values():
        addresses = record.get('aRecords')
        if not isinstance(addresses, list) or len(addresses) != 1:
            raise SystemExit(f'private DNS A-record profile drifted: {zone_name}')
        try:
            if ipaddress.ip_address(addresses[0].get('ipv4Address')) not in private_network:
                raise ValueError
        except (ValueError, TypeError):
            raise SystemExit(f'private DNS A-record address drifted: {zone_name}')
        result[record['name']] = addresses[0].get('ipv4Address')
    return result
storage_records = verify_records(storage_dns_records, {os.environ['STORAGE_ACCOUNT_NAME']}, os.environ['STORAGE_PRIVATE_DNS_ZONE'])
cosmos_records = verify_records(cosmos_dns_records, {os.environ['COSMOS_ACCOUNT_NAME'], f'{os.environ["COSMOS_ACCOUNT_NAME"]}-{os.environ["LOCATION"]}'}, os.environ['COSMOS_PRIVATE_DNS_ZONE'])
if storage_records != storage_group_records or cosmos_records != cosmos_group_records:
    raise SystemExit('private DNS zone group records do not match A-record inventory')
storage_id = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Storage/storageAccounts/{os.environ["STORAGE_ACCOUNT_NAME"]}'.lower()
if len(event_topics) > 1 or (event_topics and (event_topics[0].get('source', '').lower() != storage_id or event_topics[0].get('topicType', '').lower() != 'microsoft.storage.storageaccounts' or event_topics[0].get('provisioningState') != 'Succeeded')):
    raise SystemExit('Defender Storage Event Grid system topic drifted')
if (not event_topics and event_subscriptions) or (event_topics and (len(event_subscriptions) != 1 or event_subscriptions[0].get('name') != 'StorageAntimalwareSubscription' or event_subscriptions[0].get('provisioningState') != 'Succeeded')):
    raise SystemExit('Defender Storage Event Grid subscription drifted')
def normalized_resource(resource):
    resource_type, name = resource.get('type'), resource.get('name')
    if not isinstance(resource_type, str) or not isinstance(name, str):
        raise SystemExit('resource inventory has malformed type or name')
    return resource_type.lower(), name.lower()
nic_names = set()
for endpoint in private_endpoints:
    interfaces = endpoint.get('networkInterfaces')
    if not isinstance(interfaces, list) or len(interfaces) != 1 or not isinstance(interfaces[0].get('id'), str):
        raise SystemExit(f'private endpoint NIC inventory drifted: {endpoint["name"]}')
    nic_names.add(interfaces[0]['id'].rstrip('/').split('/')[-1].lower())
if len(nic_names) != 2:
    raise SystemExit('private endpoint NIC inventory drifted')
expected_direct_resources = {
    ('microsoft.managedidentity/userassignedidentities', 'csa-workbench-frontend-identity'),
    ('microsoft.managedidentity/userassignedidentities', 'csa-workbench-api-identity'),
    ('microsoft.managedidentity/userassignedidentities', 'csa-workbench-runtime-identity'),
    ('microsoft.app/managedenvironments', os.environ['ENVIRONMENT_NAME'].lower()),
    ('microsoft.app/containerapps', os.environ['FRONTEND_APP_NAME'].lower()),
    ('microsoft.app/containerapps', os.environ['API_APP_NAME'].lower()),
    ('microsoft.app/containerapps', os.environ['RUNTIME_APP_NAME'].lower()),
    ('microsoft.containerregistry/registries', os.environ['ACR_NAME'].lower()),
    ('microsoft.cognitiveservices/accounts', os.environ['AOAI_NAME'].lower()),
    ('microsoft.documentdb/databaseaccounts', os.environ['COSMOS_ACCOUNT_NAME'].lower()),
    ('microsoft.storage/storageaccounts', os.environ['STORAGE_ACCOUNT_NAME'].lower()),
    ('microsoft.network/virtualnetworks', os.environ['VNET_NAME'].lower()),
    ('microsoft.network/privateendpoints', os.environ['COSMOS_PRIVATE_ENDPOINT_NAME'].lower()),
    ('microsoft.network/privateendpoints', os.environ['STORAGE_PRIVATE_ENDPOINT_NAME'].lower()),
    ('microsoft.network/privatednszones', os.environ['COSMOS_PRIVATE_DNS_ZONE'].lower()),
    ('microsoft.network/privatednszones', os.environ['STORAGE_PRIVATE_DNS_ZONE'].lower()),
}
expected_direct_resources |= {('microsoft.network/networkinterfaces', nic_name) for nic_name in nic_names}
if network_security_groups:
    expected_direct_resources |= {('microsoft.network/networksecuritygroups', name) for name in governance_nsgs}
if event_topics:
    expected_direct_resources.add(('microsoft.eventgrid/systemtopics', event_topics[0]['name'].lower()))
expected_direct_resources |= {
    ('microsoft.network/privatednszones/virtualnetworklinks', f'{os.environ["COSMOS_PRIVATE_DNS_ZONE"]}/csa-workbench-vnet-link'.lower()),
    ('microsoft.network/privatednszones/virtualnetworklinks', f'{os.environ["STORAGE_PRIVATE_DNS_ZONE"]}/csa-workbench-vnet-link'.lower()),
}
allowed_child_resources = {
    ('microsoft.network/privateendpoints/privatednszonegroups', f'{os.environ["COSMOS_PRIVATE_ENDPOINT_NAME"]}/default'.lower()),
    ('microsoft.network/privateendpoints/privatednszonegroups', f'{os.environ["STORAGE_PRIVATE_ENDPOINT_NAME"]}/default'.lower()),
    ('microsoft.documentdb/databaseaccounts/sqldatabases', f'{os.environ["COSMOS_ACCOUNT_NAME"]}/csa-workbench-entra'.lower()),
    ('microsoft.documentdb/databaseaccounts/sqldatabases/containers', f'{os.environ["COSMOS_ACCOUNT_NAME"]}/csa-workbench-entra/appstate'.lower()),
    ('microsoft.storage/storageaccounts/blobservices', f'{os.environ["STORAGE_ACCOUNT_NAME"]}/default'.lower()),
    ('microsoft.storage/storageaccounts/blobservices/containers', f'{os.environ["STORAGE_ACCOUNT_NAME"]}/default/engagement-artifacts'.lower()),
    ('microsoft.cognitiveservices/accounts/deployments', f'{os.environ["AOAI_NAME"]}/{os.environ["AZURE_DEPLOYMENT"]}'.lower()),
}
if event_topics:
    allowed_child_resources.add(('microsoft.eventgrid/systemtopics/eventsubscriptions', f'{event_topics[0]["name"]}/storageantimalwaresubscription'.lower()))
actual_resources = {normalized_resource(resource) for resource in resources}
if not expected_direct_resources <= actual_resources or any(resource not in expected_direct_resources | allowed_child_resources for resource in actual_resources):
    raise SystemExit('unexpected resource inventory')
subscription_scope = f"/subscriptions/{os.environ['SUBSCRIPTION_ID']}".lower()
if any(item.get('scope', '').lower() == subscription_scope for item in assignments):
    raise SystemExit('subscription-scoped role assignment found')
resource_group_scope = f"/subscriptions/{os.environ['SUBSCRIPTION_ID']}/resourceGroups/{os.environ['RESOURCE_GROUP']}/".lower()
if any(not item.get('scope', '').lower().startswith(resource_group_scope) for item in assignments):
    raise SystemExit('managed identity role assignment escapes the CSA resource group')
subscription = os.environ['SUBSCRIPTION_ID']
expected_roles = {
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}', 'AcrPull', os.environ['FRONTEND_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}', 'AcrPull', os.environ['API_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}', 'AcrPull', os.environ['RUNTIME_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Storage/storageAccounts/{os.environ["STORAGE_ACCOUNT_NAME"]}', 'Storage Blob Data Contributor', os.environ['API_PRINCIPAL']),
    (f'/subscriptions/{subscription}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.CognitiveServices/accounts/{os.environ["AOAI_NAME"]}', 'Cognitive Services OpenAI User', os.environ['RUNTIME_PRINCIPAL']),
}
expected_roles = {(scope.lower(), role.lower(), principal.lower()) for scope, role, principal in expected_roles}
actual_roles = {(item.get('scope', '').lower(), item.get('roleDefinitionName', '').lower(), item.get('principalId', '').lower()) for item in assignments}
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
