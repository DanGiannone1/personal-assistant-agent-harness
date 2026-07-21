#!/usr/bin/env bash
# Guarded clean-break deployment for an isolated CSA Workbench MVP instance.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { echo "ERROR: $*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"; }
required_input() { [[ -n "${!1:-}" ]] || fail "$1 is required"; }
validate_model_input() {
  local variable="$1" value="${!1}" maximum="$2"
  [[ "$value" =~ ^[^[:space:][:cntrl:]]+$ ]] || fail "$variable must not contain whitespace or control characters"
  ((${#value} <= maximum)) || fail "$variable exceeds maximum length $maximum"
}

ACTION="${1:-plan}"
CONFIRMATION=''
case "$ACTION" in
  plan) [[ $# -eq 0 || $# -eq 1 ]] || fail 'usage: ./infra/deploy.sh [plan] | ./infra/deploy.sh apply --confirm apply:<PLAN_ID>:<RESOURCE_GROUP>' ;;
  apply)
    [[ $# -eq 3 && "$2" == '--confirm' ]] || fail 'usage: ./infra/deploy.sh apply --confirm apply:<PLAN_ID>:<RESOURCE_GROUP>'
    CONFIRMATION="$3"
    ;;
  *) fail 'action must be plan or apply' ;;
esac

required_input INSTANCE_SLUG
required_input MODEL_DEPLOYMENT_NAME
required_input MODEL_NAME
required_input MODEL_VERSION
required_input MODEL_SKU_NAME
required_input MODEL_CAPACITY

INSTANCE_SLUG="$INSTANCE_SLUG"
MODEL_DEPLOYMENT_NAME="$MODEL_DEPLOYMENT_NAME"
MODEL_NAME="$MODEL_NAME"
MODEL_VERSION="$MODEL_VERSION"
MODEL_SKU_NAME="$MODEL_SKU_NAME"
MODEL_CAPACITY="$MODEL_CAPACITY"
LOCATION="${LOCATION:-eastus2}"
ACR_LOCATION="${ACR_LOCATION:-$LOCATION}"
IDENTITY_MODE="${IDENTITY_MODE:-entra}"
DEMO_PASSWORD="${DEMO_PASSWORD:-}"

[[ "$INSTANCE_SLUG" =~ ^[a-z][a-z0-9]{2,9}$ ]] || fail 'INSTANCE_SLUG must match ^[a-z][a-z0-9]{2,9}$'
validate_model_input MODEL_DEPLOYMENT_NAME 64
validate_model_input MODEL_NAME 128
validate_model_input MODEL_VERSION 128
validate_model_input MODEL_SKU_NAME 64
[[ "$MODEL_CAPACITY" =~ ^[1-9][0-9]*$ ]] || fail 'MODEL_CAPACITY must be a positive integer'
(( MODEL_CAPACITY <= 1000000 )) || fail 'MODEL_CAPACITY exceeds maximum 1000000'
[[ "$IDENTITY_MODE" == 'entra' || "$IDENTITY_MODE" == 'demo' ]] || fail "IDENTITY_MODE must be 'entra' or 'demo'"
[[ "$IDENTITY_MODE" != 'demo' || -n "$DEMO_PASSWORD" ]] || fail 'DEMO_PASSWORD is required when IDENTITY_MODE=demo'

BASE_NAME="csa-wb-${INSTANCE_SLUG}"
RESOURCE_GROUP="${BASE_NAME}-rg"
ENVIRONMENT_NAME="${BASE_NAME}-env"
FRONTEND_APP_NAME="${BASE_NAME}-frontend"
API_APP_NAME="${BASE_NAME}-api"
RUNTIME_APP_NAME="${BASE_NAME}-runtime"
FRONTEND_IDENTITY_NAME="${BASE_NAME}-frontend-identity"
API_IDENTITY_NAME="${BASE_NAME}-api-identity"
RUNTIME_IDENTITY_NAME="${BASE_NAME}-runtime-identity"
VNET_NAME="${BASE_NAME}-vnet"
COSMOS_PRIVATE_ENDPOINT_NAME="${BASE_NAME}-cosmos-pe"
STORAGE_PRIVATE_ENDPOINT_NAME="${BASE_NAME}-storage-pe"
PRIVATE_DNS_VNET_LINK_NAME="${BASE_NAME}-vnet-link"
DATABASE_NAME="${BASE_NAME}-entra"
ACA_INFRASTRUCTURE_SUBNET_NAME='aca-infrastructure'
PRIVATE_ENDPOINT_SUBNET_NAME='private-endpoints'
COSMOS_PRIVATE_DNS_ZONE='privatelink.documents.azure.com'
STORAGE_PRIVATE_DNS_ZONE='privatelink.blob.core.windows.net'

require az
require git
require python3

TENANT_ID=''
SUBSCRIPTION_ID=''
SHA=''
RECOVERY_STATE=''
RECOVERY_ENVIRONMENT_ID=''
RECOVERY_DELETION_TARGETS='[]'
ACA_INFRASTRUCTURE_NSG_ID=''
PRIVATE_ENDPOINT_NSG_ID=''
PLAN_PAYLOAD=''
PLAN_ID=''

validate_account_and_revision() {
  az account show --only-show-errors >/dev/null || fail 'sign in with az login before continuing'
  TENANT_ID="$(az account show --query tenantId -o tsv)"
  SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
  [[ -n "$TENANT_ID" && -n "$SUBSCRIPTION_ID" ]] || fail 'current Azure account must provide tenant and subscription IDs'
  SHA="$(git rev-parse HEAD)"
  [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'deployment requires a full 40-character Git SHA'
  [[ -z "$(git status --porcelain)" ]] || fail 'deployment requires a clean worktree so images and SHA agree'
  az bicep version >/dev/null || fail 'Azure CLI Bicep support is required'
}

governance_preflight() {
  local group_exists inventory selected
  group_exists="$(az group exists -n "$RESOURCE_GROUP" -o tsv)" || fail "cannot determine whether resource group $RESOURCE_GROUP exists"
  case "$group_exists" in
    true) inventory="$(az network nsg list -g "$RESOURCE_GROUP" -o json)" || fail 'cannot list tenant-governance NSGs' ;;
    false) inventory='[]' ;;
    *) fail 'resource group existence check returned an invalid value' ;;
  esac
  selected="$(python3 infra/governance_nsg.py --subscription-id "$SUBSCRIPTION_ID" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --instance-slug "$INSTANCE_SLUG" <<<"$inventory")" || fail 'tenant-governance NSG preflight failed'
  ACA_INFRASTRUCTURE_NSG_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["aca_nsg_id"])' <<<"$selected")"
  PRIVATE_ENDPOINT_NSG_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["private_endpoint_nsg_id"])' <<<"$selected")"
}

recovery_preflight() {
  local group_exists environments environment_json apps_json expected_subnet_id result
  group_exists="$(az group exists -n "$RESOURCE_GROUP" -o tsv)" || fail "cannot determine whether resource group $RESOURCE_GROUP exists"
  case "$group_exists" in
    false) RECOVERY_STATE='absent'; RECOVERY_DELETION_TARGETS='[]'; return ;;
    true) ;;
    *) fail 'resource group existence check returned an invalid value' ;;
  esac
  environments="$(az containerapp env list -g "$RESOURCE_GROUP" -o json)" || fail 'cannot list Container Apps environments'
  environment_json="$(ENVIRONMENT_NAME="$ENVIRONMENT_NAME" python3 -c 'import json,os,sys; values=json.load(sys.stdin); isinstance(values,list) or sys.exit("environment inventory drifted"); matches=[v for v in values if isinstance(v,dict) and v.get("name")==os.environ["ENVIRONMENT_NAME"]]; len(matches)<=1 or sys.exit("environment inventory drifted"); (not matches or isinstance(matches[0].get("id"),str) and matches[0]["id"]) or sys.exit("environment id is missing"); print("" if not matches else matches[0]["id"])' <<<"$environments")" || fail 'Container Apps environment inventory validation failed'
  if [[ -z "$environment_json" ]]; then RECOVERY_STATE='absent'; RECOVERY_DELETION_TARGETS='[]'; return; fi
  RECOVERY_ENVIRONMENT_ID="$environment_json"
  environment_json="$(az containerapp env show -g "$RESOURCE_GROUP" -n "$ENVIRONMENT_NAME" -o json)" || fail 'cannot fetch existing Container Apps environment'
  apps_json="$(az containerapp list -g "$RESOURCE_GROUP" -o json)" || fail 'cannot list Container Apps'
  expected_subnet_id="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Network/virtualNetworks/${VNET_NAME}/subnets/${ACA_INFRASTRUCTURE_SUBNET_NAME}"
  result="$(ENVIRONMENT_NAME="$ENVIRONMENT_NAME" ENVIRONMENT_ID="$RECOVERY_ENVIRONMENT_ID" EXPECTED_SUBNET_ID="$expected_subnet_id" FRONTEND_APP_NAME="$FRONTEND_APP_NAME" API_APP_NAME="$API_APP_NAME" RUNTIME_APP_NAME="$RUNTIME_APP_NAME" ENVIRONMENT_JSON="$environment_json" APPS_JSON="$apps_json" python3 - <<'PY'
import json, os, sys
environment = json.loads(os.environ['ENVIRONMENT_JSON'])
apps = json.loads(os.environ['APPS_JSON'])
expected = [os.environ['FRONTEND_APP_NAME'], os.environ['API_APP_NAME'], os.environ['RUNTIME_APP_NAME']]
if not isinstance(environment, dict) or environment.get('name') != os.environ['ENVIRONMENT_NAME'] or not isinstance(apps, list):
    raise SystemExit('recovery inventory is malformed')
if any(not isinstance(app, dict) or not isinstance(app.get('name'), str) or not isinstance(app.get('properties', {}).get('managedEnvironmentId'), str) for app in apps):
    raise SystemExit('recovery app inventory is malformed')
attached = [app['name'] for app in apps if app['properties']['managedEnvironmentId'].rstrip('/').lower() == os.environ['ENVIRONMENT_ID'].rstrip('/').lower()]
if len(attached) != len(set(attached)):
    raise SystemExit('recovery app inventory has duplicate names')
properties = environment.get('properties', {})
profiles = properties.get('workloadProfiles') if isinstance(properties, dict) else None
subnet = properties.get('vnetConfiguration', {}).get('infrastructureSubnetId') if isinstance(properties.get('vnetConfiguration', {}), dict) else None
compatible = (isinstance(subnet, str) and subnet.lower() == os.environ['EXPECTED_SUBNET_ID'].lower() and profiles == [{'name': 'Consumption', 'workloadProfileType': 'Consumption'}])
if compatible:
    print('compatible|[]')
elif set(attached) == set(expected):
    print('incompatible|' + json.dumps(['containerapp/' + name for name in expected] + ['managedEnvironment/' + os.environ['ENVIRONMENT_NAME']], separators=(',', ':')))
else:
    raise SystemExit('incompatible environment app inventory is unsafe')
PY
)" || fail 'recovery preflight validation failed'
  IFS='|' read -r RECOVERY_STATE RECOVERY_DELETION_TARGETS <<<"$result"
  [[ "$RECOVERY_STATE" == 'compatible' || "$RECOVERY_STATE" == 'incompatible' ]] || fail 'invalid recovery state'
}

make_plan() {
  validate_account_and_revision
  governance_preflight
  recovery_preflight
  PLAN_PAYLOAD="$(SCHEMA='csa-workbench-portable-plan-v1' TENANT_ID="$TENANT_ID" SUBSCRIPTION_ID="$SUBSCRIPTION_ID" INSTANCE_SLUG="$INSTANCE_SLUG" RESOURCE_GROUP="$RESOURCE_GROUP" LOCATION="$LOCATION" ACR_LOCATION="$ACR_LOCATION" IDENTITY_MODE="$IDENTITY_MODE" DEMO_PASSWORD_SHA256="$(printf %s "$DEMO_PASSWORD" | sha256sum | awk '{print $1}')" SHA="$SHA" MODEL_DEPLOYMENT_NAME="$MODEL_DEPLOYMENT_NAME" MODEL_NAME="$MODEL_NAME" MODEL_VERSION="$MODEL_VERSION" MODEL_SKU_NAME="$MODEL_SKU_NAME" MODEL_CAPACITY="$MODEL_CAPACITY" RECOVERY_STATE="$RECOVERY_STATE" RECOVERY_DELETION_TARGETS="$RECOVERY_DELETION_TARGETS" python3 - <<'PY'
import json, os
slug = os.environ['INSTANCE_SLUG']
payload = {
  'schema': os.environ['SCHEMA'], 'tenant_id': os.environ['TENANT_ID'], 'subscription_id': os.environ['SUBSCRIPTION_ID'],
  'instance_slug': slug, 'resource_group': os.environ['RESOURCE_GROUP'], 'location': os.environ['LOCATION'], 'git_sha': os.environ['SHA'],
  'acr_location': os.environ['ACR_LOCATION'], 'identity_mode': os.environ['IDENTITY_MODE'], 'demo_password_sha256': os.environ['DEMO_PASSWORD_SHA256'],
  'model_deployment_name': os.environ['MODEL_DEPLOYMENT_NAME'], 'model_name': os.environ['MODEL_NAME'], 'model_version': os.environ['MODEL_VERSION'],
  'model_sku_name': os.environ['MODEL_SKU_NAME'], 'model_capacity': int(os.environ['MODEL_CAPACITY']),
  'entra_display_names': [f'CSA Workbench [{slug}] Web', f'CSA Workbench [{slug}] API', f'CSA Workbench [{slug}] Runtime'],
  'recovery_state': os.environ['RECOVERY_STATE'], 'recovery_deletion_targets': json.loads(os.environ['RECOVERY_DELETION_TARGETS']),
}
print(json.dumps(payload, sort_keys=True, separators=(',', ':')))
PY
)"
  PLAN_ID="$(PLAN_PAYLOAD="$PLAN_PAYLOAD" python3 - <<'PY'
import hashlib, os
print(hashlib.sha256(os.environ['PLAN_PAYLOAD'].encode()).hexdigest())
PY
)"
}

foundation_command() {
  FOUNDATION_DEPLOYMENT_NAME="${BASE_NAME}-foundation-${SHA:0:12}"
  FOUNDATION=(az deployment sub create --name "$FOUNDATION_DEPLOYMENT_NAME" --location "$LOCATION" --template-file infra/foundation.bicep
    --parameters instanceSlug="$INSTANCE_SLUG" location="$LOCATION" acrLocation="$ACR_LOCATION"
    azureOpenAiDeploymentName="$MODEL_DEPLOYMENT_NAME" azureOpenAiModelName="$MODEL_NAME" azureOpenAiModelVersion="$MODEL_VERSION"
    azureOpenAiModelSkuName="$MODEL_SKU_NAME" azureOpenAiModelCapacity="$MODEL_CAPACITY"
    acaInfrastructureNsgId="$ACA_INFRASTRUCTURE_NSG_ID" privateEndpointNsgId="$PRIVATE_ENDPOINT_NSG_ID")
}

deployment_what_if() {
  local -a command=("$@")
  [[ ${#command[@]} -ge 4 && "${command[0]}" == 'az' && "${command[1]}" == 'deployment' ]] || fail 'invalid Azure deployment command for what-if'
  case "${command[2]}" in
    sub|group) ;;
    *) fail 'invalid Azure deployment scope for what-if' ;;
  esac
  [[ "${command[3]}" == 'create' ]] || fail 'Azure deployment what-if requires a create command'
  command[3]='what-if'
  "${command[@]}" --result-format FullResourcePayloads --only-show-errors
}

delete_approved_recovery_targets() {
  [[ "$RECOVERY_STATE" == 'incompatible' ]] || return
  for app_name in "$FRONTEND_APP_NAME" "$API_APP_NAME" "$RUNTIME_APP_NAME"; do
    az containerapp delete -g "$RESOURCE_GROUP" -n "$app_name" --yes --only-show-errors
  done
  az containerapp env delete -g "$RESOURCE_GROUP" -n "$ENVIRONMENT_NAME" --yes --only-show-errors
}

foundation_output() {
  az deployment sub show --name "$FOUNDATION_DEPLOYMENT_NAME" --query "properties.outputs.$1.value" -o tsv
}

verify_inventory() {
  local apps deployments identities resources acr azure_open_ai cosmos storage vnet private_endpoints private_dns_zones managed_environment network_security_groups cosmos_dns_links storage_dns_links cosmos_dns_groups storage_dns_groups cosmos_dns_records storage_dns_records frontend_principal api_principal runtime_principal assignments cosmos_sql_assignments
  apps="$(az containerapp list -g "$RESOURCE_GROUP" -o json)"
  deployments="$(az cognitiveservices account deployment list -g "$RESOURCE_GROUP" -n "$AOAI_NAME" -o json)"
  identities="$(az identity list -g "$RESOURCE_GROUP" -o json)"
  resources="$(az resource list -g "$RESOURCE_GROUP" -o json)"
  acr="$(az acr show -g "$RESOURCE_GROUP" -n "$ACR_NAME" -o json)"
  azure_open_ai="$(az cognitiveservices account show -g "$RESOURCE_GROUP" -n "$AOAI_NAME" -o json)"
  cosmos="$(az cosmosdb show -g "$RESOURCE_GROUP" -n "$COSMOS_ACCOUNT_NAME" -o json)"
  storage="$(az storage account show -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT_NAME" -o json)"
  vnet="$(az network vnet show -g "$RESOURCE_GROUP" -n "$VNET_NAME" -o json)"
  private_endpoints="$(az network private-endpoint list -g "$RESOURCE_GROUP" -o json)"
  private_dns_zones="$(az network private-dns zone list -g "$RESOURCE_GROUP" -o json)"
  managed_environment="$(az containerapp env show -g "$RESOURCE_GROUP" -n "$ENVIRONMENT_NAME" -o json)"
  network_security_groups="$(az network nsg list -g "$RESOURCE_GROUP" -o json)"
  cosmos_dns_links="$(az network private-dns link vnet list -g "$RESOURCE_GROUP" --zone-name "$COSMOS_PRIVATE_DNS_ZONE" -o json)"
  storage_dns_links="$(az network private-dns link vnet list -g "$RESOURCE_GROUP" --zone-name "$STORAGE_PRIVATE_DNS_ZONE" -o json)"
  cosmos_dns_groups="$(az network private-endpoint dns-zone-group list -g "$RESOURCE_GROUP" --endpoint-name "$COSMOS_PRIVATE_ENDPOINT_NAME" -o json)"
  storage_dns_groups="$(az network private-endpoint dns-zone-group list -g "$RESOURCE_GROUP" --endpoint-name "$STORAGE_PRIVATE_ENDPOINT_NAME" -o json)"
  cosmos_dns_records="$(az network private-dns record-set a list -g "$RESOURCE_GROUP" -z "$COSMOS_PRIVATE_DNS_ZONE" -o json)"
  storage_dns_records="$(az network private-dns record-set a list -g "$RESOURCE_GROUP" -z "$STORAGE_PRIVATE_DNS_ZONE" -o json)"
  frontend_principal="$(az identity show -g "$RESOURCE_GROUP" -n "$FRONTEND_IDENTITY_NAME" --query principalId -o tsv)"
  api_principal="$(az identity show -g "$RESOURCE_GROUP" -n "$API_IDENTITY_NAME" --query principalId -o tsv)"
  runtime_principal="$(az identity show -g "$RESOURCE_GROUP" -n "$RUNTIME_IDENTITY_NAME" --query principalId -o tsv)"
  assignments="[$(az role assignment list --assignee "$frontend_principal" --all -o json),$(az role assignment list --assignee "$api_principal" --all -o json),$(az role assignment list --assignee "$runtime_principal" --all -o json)]"
  cosmos_sql_assignments="$(az cosmosdb sql role assignment list -g "$RESOURCE_GROUP" -a "$COSMOS_ACCOUNT_NAME" -o json)"
  APPS="$apps" DEPLOYMENTS="$deployments" IDENTITIES="$identities" RESOURCES="$resources" ACR="$acr" AZURE_OPEN_AI="$azure_open_ai" COSMOS="$cosmos" STORAGE="$storage" VNET="$vnet" PRIVATE_ENDPOINTS="$private_endpoints" PRIVATE_DNS_ZONES="$private_dns_zones" MANAGED_ENVIRONMENT="$managed_environment" NETWORK_SECURITY_GROUPS="$network_security_groups" COSMOS_DNS_LINKS="$cosmos_dns_links" STORAGE_DNS_LINKS="$storage_dns_links" COSMOS_DNS_GROUPS="$cosmos_dns_groups" STORAGE_DNS_GROUPS="$storage_dns_groups" COSMOS_DNS_RECORDS="$cosmos_dns_records" STORAGE_DNS_RECORDS="$storage_dns_records" ASSIGNMENTS="$assignments" COSMOS_SQL_ASSIGNMENTS="$cosmos_sql_assignments" FRONTEND_APP_NAME="$FRONTEND_APP_NAME" API_APP_NAME="$API_APP_NAME" RUNTIME_APP_NAME="$RUNTIME_APP_NAME" FRONTEND_IDENTITY_NAME="$FRONTEND_IDENTITY_NAME" API_IDENTITY_NAME="$API_IDENTITY_NAME" RUNTIME_IDENTITY_NAME="$RUNTIME_IDENTITY_NAME" MODEL_DEPLOYMENT_NAME="$MODEL_DEPLOYMENT_NAME" MODEL_NAME="$MODEL_NAME" MODEL_VERSION="$MODEL_VERSION" MODEL_SKU_NAME="$MODEL_SKU_NAME" MODEL_CAPACITY="$MODEL_CAPACITY" SHA="$SHA" RESOURCE_GROUP="$RESOURCE_GROUP" SUBSCRIPTION_ID="$SUBSCRIPTION_ID" ENVIRONMENT_NAME="$ENVIRONMENT_NAME" DATABASE_NAME="$DATABASE_NAME" VNET_NAME="$VNET_NAME" COSMOS_ACCOUNT_NAME="$COSMOS_ACCOUNT_NAME" STORAGE_ACCOUNT_NAME="$STORAGE_ACCOUNT_NAME" ACR_NAME="$ACR_NAME" AOAI_NAME="$AOAI_NAME" COSMOS_PRIVATE_ENDPOINT_NAME="$COSMOS_PRIVATE_ENDPOINT_NAME" STORAGE_PRIVATE_ENDPOINT_NAME="$STORAGE_PRIVATE_ENDPOINT_NAME" COSMOS_PRIVATE_DNS_ZONE="$COSMOS_PRIVATE_DNS_ZONE" STORAGE_PRIVATE_DNS_ZONE="$STORAGE_PRIVATE_DNS_ZONE" PRIVATE_DNS_VNET_LINK_NAME="$PRIVATE_DNS_VNET_LINK_NAME" FRONTEND_PRINCIPAL="$frontend_principal" API_PRINCIPAL="$api_principal" RUNTIME_PRINCIPAL="$runtime_principal" LOCATION="$LOCATION" python3 - <<'PY'
import json, os
apps = json.loads(os.environ['APPS']); deployments = json.loads(os.environ['DEPLOYMENTS']); identities = json.loads(os.environ['IDENTITIES'])
resources = json.loads(os.environ['RESOURCES']); acr = json.loads(os.environ['ACR']); aoai = json.loads(os.environ['AZURE_OPEN_AI'])
cosmos = json.loads(os.environ['COSMOS']); storage = json.loads(os.environ['STORAGE']); vnet = json.loads(os.environ['VNET'])
private_endpoints = json.loads(os.environ['PRIVATE_ENDPOINTS']); zones = json.loads(os.environ['PRIVATE_DNS_ZONES']); environment = json.loads(os.environ['MANAGED_ENVIRONMENT'])
network_security_groups = json.loads(os.environ['NETWORK_SECURITY_GROUPS'])
cosmos_links = json.loads(os.environ['COSMOS_DNS_LINKS']); storage_links = json.loads(os.environ['STORAGE_DNS_LINKS'])
cosmos_groups = json.loads(os.environ['COSMOS_DNS_GROUPS']); storage_groups = json.loads(os.environ['STORAGE_DNS_GROUPS'])
cosmos_records = json.loads(os.environ['COSMOS_DNS_RECORDS']); storage_records = json.loads(os.environ['STORAGE_DNS_RECORDS'])
assignments = [item for group in json.loads(os.environ['ASSIGNMENTS']) for item in group]
cosmos_assignments = json.loads(os.environ['COSMOS_SQL_ASSIGNMENTS'])
expected_apps = {os.environ['FRONTEND_APP_NAME']: (True, 3000, 'csa-workbench-frontend'), os.environ['API_APP_NAME']: (True, 8000, 'csa-workbench-api'), os.environ['RUNTIME_APP_NAME']: (False, 8080, 'csa-workbench-runtime')}
if not isinstance(apps, list) or {a.get('name') for a in apps} != set(expected_apps): raise SystemExit('Container App inventory drifted')
if not isinstance(identities, list) or {i.get('name') for i in identities} != {os.environ['FRONTEND_IDENTITY_NAME'], os.environ['API_IDENTITY_NAME'], os.environ['RUNTIME_IDENTITY_NAME']}: raise SystemExit('managed identity inventory drifted')
for app in apps:
    external, port, repository = expected_apps[app['name']]; p = app.get('properties', {}); template = p.get('template', {}); containers = template.get('containers', [])
    ingress = p.get('configuration', {}).get('ingress', {})
    expected_identity = {'csa-workbench-frontend': os.environ['FRONTEND_IDENTITY_NAME'], 'csa-workbench-api': os.environ['API_IDENTITY_NAME'], 'csa-workbench-runtime': os.environ['RUNTIME_IDENTITY_NAME']}[repository]
    expected_identity_id = next(identity.get('id') for identity in identities if identity.get('name') == expected_identity)
    if p.get('provisioningState') != 'Succeeded' or p.get('workloadProfileName') != 'Consumption' or ingress.get('external') is not external or ingress.get('targetPort') != port or ingress.get('transport', '').lower() != 'auto' or template.get('scale') != {'minReplicas': 0, 'maxReplicas': 1} or len(containers) != 1 or containers[0].get('image', '').split('/')[-1] != f'{repository}:{os.environ["SHA"]}' or set(app.get('identity', {}).get('userAssignedIdentities', {})) != {expected_identity_id} or p.get('configuration', {}).get('registries') != [{'server': f'{os.environ["ACR_NAME"]}.azurecr.io', 'identity': expected_identity_id}]: raise SystemExit('Container App identity, registry, or profile drifted')
    if app['name'] == os.environ['RUNTIME_APP_NAME']:
        runtime_env = {item.get('name'): item.get('value') for item in containers[0].get('env', []) if isinstance(item, dict)}
        endpoint = aoai.get('properties', {}).get('endpoint')
        if runtime_env.get('AZURE_DEPLOYMENT') != os.environ['MODEL_DEPLOYMENT_NAME'] or runtime_env.get('AZURE_ENDPOINT') != f'{endpoint.rstrip("/")}/openai/v1/': raise SystemExit('runtime Azure OpenAI binding drifted')
if not isinstance(deployments, list) or len(deployments) != 1: raise SystemExit('Azure OpenAI deployment inventory drifted')
d = deployments[0]
model = d.get('properties', {}).get('model', {})
if d.get('name') != os.environ['MODEL_DEPLOYMENT_NAME'] or d.get('properties', {}).get('provisioningState') != 'Succeeded' or model.get('format') != 'OpenAI' or d.get('sku', {}).get('name') != os.environ['MODEL_SKU_NAME'] or d.get('sku', {}).get('capacity') != int(os.environ['MODEL_CAPACITY']) or model.get('name') != os.environ['MODEL_NAME'] or model.get('version') != os.environ['MODEL_VERSION']: raise SystemExit('Azure OpenAI model profile drifted')
if acr.get('name') != os.environ['ACR_NAME'] or acr.get('sku', {}).get('name') != 'Basic' or acr.get('adminUserEnabled') is not False: raise SystemExit('Container Registry profile drifted')
if aoai.get('name') != os.environ['AOAI_NAME'] or aoai.get('kind') != 'OpenAI' or aoai.get('sku', {}).get('name') != 'S0' or aoai.get('properties', {}).get('disableLocalAuth') is not True: raise SystemExit('Azure OpenAI account profile drifted')
if cosmos.get('disableLocalAuth') is not True or cosmos.get('publicNetworkAccess') != 'Disabled': raise SystemExit('Cosmos authentication/network profile drifted')
if storage.get('publicNetworkAccess') != 'Disabled' or storage.get('allowSharedKeyAccess') is not False or storage.get('allowBlobPublicAccess') is not False: raise SystemExit('Storage authentication/public-blob profile drifted')
subnets = {subnet.get('name'): subnet for subnet in vnet.get('subnets', [])}
if vnet.get('name') != os.environ['VNET_NAME'] or vnet.get('addressSpace', {}).get('addressPrefixes') != ['10.42.0.0/24'] or set(subnets) != {'aca-infrastructure', 'private-endpoints'} or subnets['aca-infrastructure'].get('addressPrefix') != '10.42.0.0/27' or subnets['private-endpoints'].get('addressPrefix') != '10.42.0.32/27' or subnets['private-endpoints'].get('privateEndpointNetworkPolicies') != 'Disabled': raise SystemExit('virtual network profile drifted')
expected_environment_id = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.App/managedEnvironments/{os.environ["ENVIRONMENT_NAME"]}'.lower()
expected_subnet = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Network/virtualNetworks/{os.environ["VNET_NAME"]}/subnets/aca-infrastructure'.lower()
if environment.get('name') != os.environ['ENVIRONMENT_NAME'] or environment.get('properties', {}).get('vnetConfiguration', {}).get('infrastructureSubnetId', '').lower() != expected_subnet or any(app.get('properties', {}).get('managedEnvironmentId', '').lower() != expected_environment_id for app in apps): raise SystemExit('Container Apps environment private-network profile drifted')
expected_endpoints = {os.environ['COSMOS_PRIVATE_ENDPOINT_NAME'], os.environ['STORAGE_PRIVATE_ENDPOINT_NAME']}
if not isinstance(private_endpoints, list) or {endpoint.get('name') for endpoint in private_endpoints} != expected_endpoints: raise SystemExit('private endpoint inventory drifted')
nic_names = set()
for endpoint in private_endpoints:
    interfaces = endpoint.get('networkInterfaces')
    if not isinstance(interfaces, list) or len(interfaces) != 1 or not isinstance(interfaces[0].get('id'), str): raise SystemExit('private endpoint NIC inventory drifted')
    nic_names.add(interfaces[0]['id'].rstrip('/').split('/')[-1].lower())
if len(nic_names) != 2: raise SystemExit('private endpoint NIC inventory drifted')
private_subnet = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Network/virtualNetworks/{os.environ["VNET_NAME"]}/subnets/private-endpoints'.lower()
expected_targets = {os.environ['COSMOS_PRIVATE_ENDPOINT_NAME']: (f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.DocumentDB/databaseAccounts/{os.environ["COSMOS_ACCOUNT_NAME"]}'.lower(), 'Sql'), os.environ['STORAGE_PRIVATE_ENDPOINT_NAME']: (f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Storage/storageAccounts/{os.environ["STORAGE_ACCOUNT_NAME"]}'.lower(), 'blob')}
for endpoint in private_endpoints:
    target, group = expected_targets[endpoint['name']]; connections = endpoint.get('privateLinkServiceConnections', [])
    if endpoint.get('provisioningState') != 'Succeeded' or endpoint.get('subnet', {}).get('id', '').lower() != private_subnet or len(connections) != 1 or connections[0].get('privateLinkServiceId', '').lower() != target or connections[0].get('groupIds') != [group] or connections[0].get('privateLinkServiceConnectionState', {}).get('status', '').lower() != 'approved': raise SystemExit('private endpoint wiring drifted')
if not isinstance(zones, list) or {zone.get('name') for zone in zones} != {os.environ['COSMOS_PRIVATE_DNS_ZONE'], os.environ['STORAGE_PRIVATE_DNS_ZONE']}: raise SystemExit('private DNS zone inventory drifted')
vnet_id = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Network/virtualNetworks/{os.environ["VNET_NAME"]}'.lower()
if network_security_groups:
    expected_nsgs = {f'{os.environ["VNET_NAME"]}-aca-infrastructure-nsg-{os.environ["LOCATION"]}'.lower(), f'{os.environ["VNET_NAME"]}-private-endpoints-nsg-{os.environ["LOCATION"]}'.lower()}
    if not isinstance(network_security_groups, list) or len(network_security_groups) != len(expected_nsgs) or {nsg.get('name', '').lower() for nsg in network_security_groups} != expected_nsgs or any(nsg.get('provisioningState') != 'Succeeded' or nsg.get('securityRules') != [] or nsg.get('networkInterfaces') not in (None, []) for nsg in network_security_groups): raise SystemExit('tenant-governance NSG profile drifted')
def verify_link(links, zone):
    if len(links) != 1 or links[0].get('name') != os.environ['PRIVATE_DNS_VNET_LINK_NAME'] or links[0].get('provisioningState') != 'Succeeded' or links[0].get('virtualNetworkLinkState') != 'Completed' or links[0].get('registrationEnabled') is not False or links[0].get('virtualNetwork', {}).get('id', '').lower() != vnet_id: raise SystemExit(f'private DNS VNet link drifted: {zone}')
def verify_group(groups, zone, records):
    expected_zone_id = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.Network/privateDnsZones/{zone}'.lower()
    if len(groups) != 1 or groups[0].get('name') != 'default' or groups[0].get('provisioningState') != 'Succeeded': raise SystemExit(f'private DNS zone group drifted: {zone}')
    configs = groups[0].get('privateDnsZoneConfigs', [])
    if len(configs) != 1 or configs[0].get('privateDnsZoneId', '').lower() != expected_zone_id or not isinstance(configs[0].get('recordSets'), list) or {record.get('recordSetName') for record in configs[0]['recordSets']} != records: raise SystemExit(f'private DNS zone group wiring drifted: {zone}')
    return {record['recordSetName']: record.get('ipAddresses') for record in configs[0]['recordSets']}
def verify_records(records, expected, zone):
    result = {record.get('name'): record.get('aRecords') for record in records}
    if set(result) != expected or any(not isinstance(values, list) or len(values) != 1 for values in result.values()): raise SystemExit(f'private DNS A-record inventory drifted: {zone}')
    return {name: [entry.get('ipv4Address') for entry in values] for name, values in result.items()}
verify_link(cosmos_links, os.environ['COSMOS_PRIVATE_DNS_ZONE']); verify_link(storage_links, os.environ['STORAGE_PRIVATE_DNS_ZONE'])
cosmos_names = {os.environ['COSMOS_ACCOUNT_NAME'], f'{os.environ["COSMOS_ACCOUNT_NAME"]}-{os.environ["LOCATION"]}'}
storage_names = {os.environ['STORAGE_ACCOUNT_NAME']}
cosmos_group = verify_group(cosmos_groups, os.environ['COSMOS_PRIVATE_DNS_ZONE'], cosmos_names); storage_group = verify_group(storage_groups, os.environ['STORAGE_PRIVATE_DNS_ZONE'], storage_names)
if {name: [entry.get('ipAddress') for entry in values] for name, values in cosmos_group.items()} != verify_records(cosmos_records, cosmos_names, os.environ['COSMOS_PRIVATE_DNS_ZONE']) or {name: [entry.get('ipAddress') for entry in values] for name, values in storage_group.items()} != verify_records(storage_records, storage_names, os.environ['STORAGE_PRIVATE_DNS_ZONE']): raise SystemExit('private DNS A-record wiring drifted')
expected_resources = {
  ('microsoft.app/managedenvironments', os.environ['ENVIRONMENT_NAME'].lower()), ('microsoft.app/containerapps', os.environ['FRONTEND_APP_NAME'].lower()), ('microsoft.app/containerapps', os.environ['API_APP_NAME'].lower()), ('microsoft.app/containerapps', os.environ['RUNTIME_APP_NAME'].lower()),
  ('microsoft.managedidentity/userassignedidentities', os.environ['FRONTEND_IDENTITY_NAME'].lower()), ('microsoft.managedidentity/userassignedidentities', os.environ['API_IDENTITY_NAME'].lower()), ('microsoft.managedidentity/userassignedidentities', os.environ['RUNTIME_IDENTITY_NAME'].lower()),
  ('microsoft.containerregistry/registries', os.environ['ACR_NAME'].lower()), ('microsoft.cognitiveservices/accounts', os.environ['AOAI_NAME'].lower()), ('microsoft.documentdb/databaseaccounts', os.environ['COSMOS_ACCOUNT_NAME'].lower()), ('microsoft.storage/storageaccounts', os.environ['STORAGE_ACCOUNT_NAME'].lower()), ('microsoft.network/virtualnetworks', os.environ['VNET_NAME'].lower()), ('microsoft.network/privateendpoints', os.environ['COSMOS_PRIVATE_ENDPOINT_NAME'].lower()), ('microsoft.network/privateendpoints', os.environ['STORAGE_PRIVATE_ENDPOINT_NAME'].lower()), ('microsoft.network/privatednszones', os.environ['COSMOS_PRIVATE_DNS_ZONE'].lower()), ('microsoft.network/privatednszones', os.environ['STORAGE_PRIVATE_DNS_ZONE'].lower()),
}
expected_resources |= {('microsoft.network/networkinterfaces', name) for name in nic_names}
if network_security_groups:
    expected_resources |= {('microsoft.network/networksecuritygroups', name) for name in expected_nsgs}
actual_resources = {(r.get('type', '').lower(), r.get('name', '').lower()) for r in resources if isinstance(r, dict)}
allowed_children = {('microsoft.documentdb/databaseaccounts/sqldatabases', f'{os.environ["COSMOS_ACCOUNT_NAME"]}/{os.environ["DATABASE_NAME"]}'.lower()), ('microsoft.documentdb/databaseaccounts/sqldatabases/containers', f'{os.environ["COSMOS_ACCOUNT_NAME"]}/{os.environ["DATABASE_NAME"]}/appstate'.lower()), ('microsoft.cognitiveservices/accounts/deployments', f'{os.environ["AOAI_NAME"]}/{os.environ["MODEL_DEPLOYMENT_NAME"]}'.lower()), ('microsoft.network/privatednszones/virtualnetworklinks', f'{os.environ["COSMOS_PRIVATE_DNS_ZONE"]}/{os.environ["PRIVATE_DNS_VNET_LINK_NAME"]}'.lower()), ('microsoft.network/privatednszones/virtualnetworklinks', f'{os.environ["STORAGE_PRIVATE_DNS_ZONE"]}/{os.environ["PRIVATE_DNS_VNET_LINK_NAME"]}'.lower()), ('microsoft.network/privateendpoints/privatednszonegroups', f'{os.environ["COSMOS_PRIVATE_ENDPOINT_NAME"]}/default'.lower()), ('microsoft.network/privateendpoints/privatednszonegroups', f'{os.environ["STORAGE_PRIVATE_ENDPOINT_NAME"]}/default'.lower()), ('microsoft.storage/storageaccounts/blobservices', f'{os.environ["STORAGE_ACCOUNT_NAME"]}/default'.lower()), ('microsoft.storage/storageaccounts/blobservices/containers', f'{os.environ["STORAGE_ACCOUNT_NAME"]}/default/engagement-artifacts'.lower())}
if not expected_resources <= actual_resources or any(resource not in expected_resources | allowed_children for resource in actual_resources): raise SystemExit('required resource inventory drifted')
rg_scope = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/'.lower()
if any(not item.get('scope', '').lower().startswith(rg_scope) for item in assignments): raise SystemExit('managed identity role assignment escapes the resource group')
expected_roles = {(f'{rg_scope}providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}'.lower(), 'acrpull', os.environ['FRONTEND_PRINCIPAL'].lower()), (f'{rg_scope}providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}'.lower(), 'acrpull', os.environ['API_PRINCIPAL'].lower()), (f'{rg_scope}providers/Microsoft.ContainerRegistry/registries/{os.environ["ACR_NAME"]}'.lower(), 'acrpull', os.environ['RUNTIME_PRINCIPAL'].lower()), (f'{rg_scope}providers/Microsoft.Storage/storageAccounts/{os.environ["STORAGE_ACCOUNT_NAME"]}'.lower(), 'storage blob data contributor', os.environ['API_PRINCIPAL'].lower()), (f'{rg_scope}providers/Microsoft.CognitiveServices/accounts/{os.environ["AOAI_NAME"]}'.lower(), 'cognitive services openai user', os.environ['RUNTIME_PRINCIPAL'].lower())}
actual_roles = {(item.get('scope', '').lower(), item.get('roleDefinitionName', '').lower(), item.get('principalId', '').lower()) for item in assignments}
if actual_roles != expected_roles: raise SystemExit('managed identity role assignments drifted')
cosmos_scope = f'/subscriptions/{os.environ["SUBSCRIPTION_ID"]}/resourceGroups/{os.environ["RESOURCE_GROUP"]}/providers/Microsoft.DocumentDB/databaseAccounts/{os.environ["COSMOS_ACCOUNT_NAME"]}'
expected_cosmos = {(f'{cosmos_scope}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002', cosmos_scope, os.environ['API_PRINCIPAL']), (f'{cosmos_scope}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002', cosmos_scope, os.environ['RUNTIME_PRINCIPAL'])}
actual_cosmos = {(item.get('roleDefinitionId', ''), item.get('scope', ''), item.get('principalId', '')) for item in cosmos_assignments}
if actual_cosmos != expected_cosmos: raise SystemExit('Cosmos SQL role assignments drifted')
PY
}

make_plan
foundation_command
if [[ "$ACTION" == 'plan' ]]; then
  if [[ "$RECOVERY_STATE" != 'incompatible' ]]; then
    echo 'Running foundation what-if (read-only; it cannot preview later Entra creation, ACR builds, or app deployment for a new instance).'
    deployment_what_if "${FOUNDATION[@]}"
  fi
  echo 'PLAN_PAYLOAD='
  echo "$PLAN_PAYLOAD"
  echo "PLAN_ID=$PLAN_ID"
  echo "CONFIRM=apply:$PLAN_ID:$RESOURCE_GROUP"
  exit 0
fi

EXPECTED_CONFIRMATION="apply:${PLAN_ID}:${RESOURCE_GROUP}"
[[ "$CONFIRMATION" == "$EXPECTED_CONFIRMATION" ]] || fail "confirmation does not match current plan; expected $EXPECTED_CONFIRMATION"

# Re-read every mutable precondition after intent confirmation and before mutation.
make_plan
foundation_command
[[ "$CONFIRMATION" == "apply:${PLAN_ID}:${RESOURCE_GROUP}" ]] || fail 'confirmation is stale after preflight recomputation'
delete_approved_recovery_targets
deployment_what_if "${FOUNDATION[@]}"
"${FOUNDATION[@]}" --only-show-errors >/dev/null

ENVIRONMENT_DOMAIN="$(foundation_output environmentDefaultDomain)"
ACR_SERVER="$(foundation_output acrLoginServer)"
ACR_NAME="$(foundation_output acrName)"
AOAI_NAME="$(foundation_output azureOpenAiName)"
AOAI_ENDPOINT="$(foundation_output azureOpenAiEndpoint)"
FRONTEND_IDENTITY_ID="$(foundation_output frontendIdentityId)"
API_IDENTITY_ID="$(foundation_output apiIdentityId)"
RUNTIME_IDENTITY_ID="$(foundation_output runtimeIdentityId)"
API_PRINCIPAL_ID="$(foundation_output apiIdentityPrincipalId)"
COSMOS_ACCOUNT_NAME="$(foundation_output cosmosAccountName)"
STORAGE_ACCOUNT_NAME="$(foundation_output storageAccountName)"
[[ -n "$ENVIRONMENT_DOMAIN" && -n "$ACR_SERVER" && -n "$ACR_NAME" && -n "$AOAI_NAME" && -n "$API_PRINCIPAL_ID" ]] || fail 'foundation deployment did not return required outputs'
FRONTEND_URL="https://${FRONTEND_APP_NAME}.${ENVIRONMENT_DOMAIN}"
API_URL="https://${API_APP_NAME}.${ENVIRONMENT_DOMAIN}"
RUNTIME_FQDN="${RUNTIME_APP_NAME}.internal.${ENVIRONMENT_DOMAIN}"
ENTRA_JSON="$(python3 infra/entra.py --instance-slug "$INSTANCE_SLUG" --tenant-id "$TENANT_ID" --frontend-redirect-uri "$FRONTEND_URL" --api-uami-principal-id "$API_PRINCIPAL_ID")"
API_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["api_client_id"])' <<<"$ENTRA_JSON")"
WEB_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["web_client_id"])' <<<"$ENTRA_JSON")"
RUNTIME_CLIENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runtime_client_id"])' <<<"$ENTRA_JSON")"

az acr build -r "$ACR_NAME" -g "$RESOURCE_GROUP" -t "csa-workbench-api:$SHA" -f Dockerfile . --only-show-errors
az acr build -r "$ACR_NAME" -g "$RESOURCE_GROUP" -t "csa-workbench-runtime:$SHA" -f session-container/Dockerfile . --only-show-errors
az acr build -r "$ACR_NAME" -g "$RESOURCE_GROUP" -t "csa-workbench-frontend:$SHA" -f frontend/Dockerfile frontend --build-arg "NEXT_PUBLIC_API_URL=$API_URL" --build-arg "NEXT_PUBLIC_IDENTITY_MODE=$IDENTITY_MODE" --build-arg "NEXT_PUBLIC_ENTRA_TENANT_ID=$TENANT_ID" --build-arg "NEXT_PUBLIC_ENTRA_CLIENT_ID=$WEB_CLIENT_ID" --build-arg "NEXT_PUBLIC_ENTRA_API_CLIENT_ID=$API_CLIENT_ID" --build-arg "NEXT_PUBLIC_ENTRA_API_SCOPES=api://$API_CLIENT_ID/access_as_user" --build-arg "NEXT_PUBLIC_ENTRA_REDIRECT_URI=$FRONTEND_URL" --only-show-errors
APPS=(az deployment group create -g "$RESOURCE_GROUP" --name "${BASE_NAME}-apps-${SHA:0:12}" --template-file infra/apps.bicep
  --parameters environmentName="$ENVIRONMENT_NAME" acrServer="$ACR_SERVER" imageTag="$SHA" frontendAppName="$FRONTEND_APP_NAME" apiAppName="$API_APP_NAME" runtimeAppName="$RUNTIME_APP_NAME"
  frontendIdentityId="$FRONTEND_IDENTITY_ID" apiIdentityId="$API_IDENTITY_ID" runtimeIdentityId="$RUNTIME_IDENTITY_ID" tenantId="$TENANT_ID" apiClientId="$API_CLIENT_ID" runtimeClientId="$RUNTIME_CLIENT_ID" frontendUrl="$FRONTEND_URL" runtimeFqdn="$RUNTIME_FQDN" cosmosAccountName="$COSMOS_ACCOUNT_NAME" storageAccountName="$STORAGE_ACCOUNT_NAME" databaseName="$DATABASE_NAME" azureOpenAiEndpoint="${AOAI_ENDPOINT%/}/openai/v1/" azureOpenAiDeployment="$MODEL_DEPLOYMENT_NAME" identityMode="$IDENTITY_MODE" demoPassword="$DEMO_PASSWORD")
deployment_what_if "${APPS[@]}"
"${APPS[@]}" --only-show-errors >/dev/null
verify_inventory
echo "Deployed isolated instance $INSTANCE_SLUG with immutable images tagged $SHA"
