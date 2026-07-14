#!/usr/bin/env bash
#
# Deploy the RFP Agent to Azure Container Apps with Dynamic Sessions.
#
# Prerequisites:
#   - Azure CLI (az) installed and logged in
#   - Docker (for building images)
#
# Usage:
#   ./infra/deploy.sh                          # uses defaults
#   LOCATION=westus2 ./infra/deploy.sh         # override location
#
# App-level Entra auth is wired through env vars. Create the app registrations
# manually, then pass the values below when deploying:
#
#   ENTRA_TENANT_ID=<tenant>
#   ENTRA_API_CLIENT_ID=<api-app-id>
#   ENTRA_FRONTEND_CLIENT_ID=<spa-app-id>
#   ENTRA_REDIRECT_URI=https://<frontend-url>   # auto-derived if omitted
#
set -euo pipefail

# Unique tag for this deploy — ACA only creates a new revision when the image
# string changes. Using :latest is unreliable because ACA caches the resolved
# digest; a SHA-based tag guarantees a new revision on every deploy.
SHA=$(git rev-parse --short HEAD)

# ── Configuration ─────────────────────────────────────────────────────────
# Dev environment lives in flow-dev-rg, everything in eastus2 (eastus hit hard
# AKS capacity limits in Jul 2026). Moved-in resources (rfpagent-ai OpenAI,
# djgrfpagentadls ADLS) keep their original names/regions.
PREFIX="${PREFIX:-flow-dev}"
LOCATION="${LOCATION:-eastus2}"
RG="${PREFIX}-rg"
IDENTITY_NAME="${PREFIX}-identity"
ACR_NAME="${ACR_NAME:-flowdevdjgacr}"   # ACR names: alphanumeric only, globally unique
ENV_NAME="${ENV_NAME:-${PREFIX}-env}"
SESSION_POOL_NAME="${SESSION_POOL_NAME:-flow-sessions}"
APP_NAME="${APP_NAME:-flow-app}"
FRONTEND_NAME="${FRONTEND_NAME:-flow-frontend}"
MCP_NAME="${MCP_NAME:-flow-mcp}"
IMG_PREFIX="${IMG_PREFIX:-rfp}"   # images: rfp-session / rfp-orchestrator / rfp-frontend / rfp-mcp
# Shared key for the flow-mcp app-state MCP server (required — it is the only
# path to Cosmos from outside the VNet; see docs/deployment.md).
MCP_API_KEY="${MCP_API_KEY:-}"

# ── Private networking (single VNet: ACA infra + Cosmos private endpoint) ──
VNET_NAME="${VNET_NAME:-${PREFIX}-vnet}"
COSMOS_ACCOUNT_NAME="${COSMOS_ACCOUNT_NAME:-${PREFIX}-cosmos}"

AZURE_DEPLOYMENT="${AZURE_DEPLOYMENT:-gpt-4.1}"
COSMOS_ENDPOINT="${COSMOS_ENDPOINT:-https://${COSMOS_ACCOUNT_NAME}.documents.azure.com:443/}"
COSMOS_DATABASE="${COSMOS_DATABASE:-flow}"
COSMOS_CONTAINER="${COSMOS_CONTAINER:-appstate}"
# Reminder email via ACS (scheduler.py) — optional, empty disables
ACS_EMAIL_ENDPOINT="${ACS_EMAIL_ENDPOINT:-}"
ACS_SENDER_ADDRESS="${ACS_SENDER_ADDRESS:-}"
REMINDER_EMAIL="${REMINDER_EMAIL:-}"
ADLS_ACCOUNT_NAME="${ADLS_ACCOUNT_NAME:-djgrfpagentadls}"   # moved-in account; storage names are alphanumeric-only
ADLS_FILESYSTEM="${ADLS_FILESYSTEM:-documents}"
AZURE_SEARCH_KB_NAME="${AZURE_SEARCH_KB_NAME:-rfp-knowledge}"
LOG_ANALYTICS_WORKSPACE_NAME="${LOG_ANALYTICS_WORKSPACE_NAME:-${PREFIX}-logs}"
APPINSIGHTS_NAME="${APPINSIGHTS_NAME:-${PREFIX}-insights}"
APPLICATIONINSIGHTS_CONNECTION_STRING="${APPLICATIONINSIGHTS_CONNECTION_STRING:-}"
OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-flow-session}"
OTEL_SERVICE_NAMESPACE="${OTEL_SERVICE_NAMESPACE:-flow}"
OTEL_SERVICE_VERSION="${OTEL_SERVICE_VERSION:-$SHA}"
OTEL_DEPLOYMENT_ENVIRONMENT="${OTEL_DEPLOYMENT_ENVIRONMENT:-azure}"
# ACA no longer accepts 0 ready sessions (SessionPoolInvalidReadySessionInstances,
# enforced at create AND via ARM since ~mid-2026): the platform floor is 1, so one
# warm session is always running. Old pools with 0 are grandfathered.
SESSION_READY_SESSIONS="${SESSION_READY_SESSIONS:-1}"
# MVP v1 (docs/mvp-requirements.md R17/R18): Search off by default (shared admin
# key + no Private Link on free SKU); demo login on for the deployed test path
# (flip via env, no redeploy); artifacts on Blob via managed identity.
ENABLE_SEARCH="${ENABLE_SEARCH:-false}"
DEMO_LOGIN_ENABLED="${DEMO_LOGIN_ENABLED:-true}"
NEXT_PUBLIC_DEMO_LOGIN="${NEXT_PUBLIC_DEMO_LOGIN:-$DEMO_LOGIN_ENABLED}"
ARTIFACTS_ACCOUNT="${ARTIFACTS_ACCOUNT:-$ADLS_ACCOUNT_NAME}"
ARTIFACTS_CONTAINER="${ARTIFACTS_CONTAINER:-artifacts}"
ORCHESTRATOR_MIN_REPLICAS="${ORCHESTRATOR_MIN_REPLICAS:-0}"
FRONTEND_MIN_REPLICAS="${FRONTEND_MIN_REPLICAS:-0}"
SESSION_POOL_API_VERSION="${SESSION_POOL_API_VERSION:-2024-10-02-preview}"

# Optional: restrict ingress to a specific IP (e.g. your office/home IP).
# Leave blank to allow all traffic.
ALLOWED_IP="${ALLOWED_IP:-}"
ALLOW_PUBLIC_UNAUTHENTICATED="${ALLOW_PUBLIC_UNAUTHENTICATED:-false}"

# Optional: App-level auth and ACA Easy Auth.
# ENTRA_CLIENT_SECRET comes from the backend app registration's client credentials
# and is only required for the ACA Easy Auth step below.
API_AUTH_REQUIRED="${API_AUTH_REQUIRED:-false}"
API_KEY="${API_KEY:-${LOCAL_API_KEY:-}}"
ENTRA_TENANT_ID="${ENTRA_TENANT_ID:-}"
ENTRA_API_CLIENT_ID="${ENTRA_API_CLIENT_ID:-${ENTRA_CLIENT_ID:-}}"
ENTRA_FRONTEND_CLIENT_ID="${ENTRA_FRONTEND_CLIENT_ID:-}"
ENTRA_API_SCOPES="${ENTRA_API_SCOPES:-}"
ENTRA_ALLOWED_AUDIENCES="${ENTRA_ALLOWED_AUDIENCES:-${ENTRA_API_AUDIENCES:-}}"
ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID:-$ENTRA_API_CLIENT_ID}"
ENTRA_CLIENT_SECRET="${ENTRA_CLIENT_SECRET:-}"
ENTRA_REDIRECT_URI="${ENTRA_REDIRECT_URI:-}"  # auto-derived from frontend URL if blank

is_truthy() {
    case "${1,,}" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

if ! is_truthy "$API_AUTH_REQUIRED" && [ -z "$ALLOWED_IP" ] && ! is_truthy "$ALLOW_PUBLIC_UNAUTHENTICATED"; then
    echo "ERROR: Refusing to deploy public unauthenticated ingress."
    echo "Set API_AUTH_REQUIRED=true, set ALLOWED_IP, or explicitly set ALLOW_PUBLIC_UNAUTHENTICATED=true."
    exit 1
fi

echo "=== RFP Agent Deployment ==="
echo "Resource Group:  $RG"
echo "Location:        $LOCATION"
echo "ACR:             $ACR_NAME"
echo "Session Pool:    $SESSION_POOL_NAME"
echo "App:             $APP_NAME"
echo "API Auth:        $API_AUTH_REQUIRED"
if [ -n "$APPLICATIONINSIGHTS_CONNECTION_STRING" ]; then
    echo "Tracing:         enabled"
else
    echo "Tracing:         provision App Insights"
fi
echo ""

# ── 1. Resource Group ────────────────────────────────────────────────────
echo ">>> Creating resource group..."
az group create --name "$RG" --location "$LOCATION" -o none

# ── 1a. Private networking ─────────────────────────────────────────────────
# Cosmos is reachable ONLY via private endpoint (publicNetworkAccess=Disabled;
# an MCAPS management-group policy force-disables it anyway). One VNet: the ACA
# env gets egress via aca-infra; the Cosmos PE sits in private-endpoints.
echo ">>> Ensuring VNet, DNS zone, and Cosmos (serverless, private)..."
az network vnet create -g "$RG" -n "$VNET_NAME" -l "$LOCATION" \
    --address-prefix 10.20.0.0/16 \
    --subnet-name aca-infra --subnet-prefix 10.20.0.0/23 -o none 2>/dev/null || true
az network vnet subnet update -g "$RG" --vnet-name "$VNET_NAME" -n aca-infra \
    --delegations Microsoft.App/environments -o none
az network vnet subnet create -g "$RG" --vnet-name "$VNET_NAME" -n private-endpoints \
    --address-prefixes 10.20.2.0/24 -o none 2>/dev/null || true

az network private-dns zone create -g "$RG" -n privatelink.documents.azure.com -o none 2>/dev/null || true
az network private-dns link vnet create -g "$RG" -n "${VNET_NAME}-link" \
    -z privatelink.documents.azure.com --virtual-network "$VNET_NAME" \
    --registration-enabled false -o none 2>/dev/null || true

# Serverless Cosmos (pay-per-RU — right-sized for dev), AAD-only, private-only.
if ! az cosmosdb show -n "$COSMOS_ACCOUNT_NAME" -g "$RG" -o none 2>/dev/null; then
    az cosmosdb create -n "$COSMOS_ACCOUNT_NAME" -g "$RG" \
        --locations regionName="$LOCATION" failoverPriority=0 isZoneRedundant=False \
        --capabilities EnableServerless \
        --public-network-access DISABLED \
        --default-consistency-level Session -o none
    az resource update --ids "$(az cosmosdb show -n "$COSMOS_ACCOUNT_NAME" -g "$RG" --query id -o tsv)" \
        --set properties.disableLocalAuth=true -o none
    az cosmosdb sql database create -a "$COSMOS_ACCOUNT_NAME" -g "$RG" -n "$COSMOS_DATABASE" -o none
    az cosmosdb sql container create -a "$COSMOS_ACCOUNT_NAME" -g "$RG" -d "$COSMOS_DATABASE" \
        -n "$COSMOS_CONTAINER" --partition-key-path /sessionId -o none
fi
COSMOS_ID=$(az cosmosdb show -n "$COSMOS_ACCOUNT_NAME" -g "$RG" --query id -o tsv)
if ! az network private-endpoint show -g "$RG" -n "${COSMOS_ACCOUNT_NAME}-pe" -o none 2>/dev/null; then
    az network private-endpoint create -g "$RG" -n "${COSMOS_ACCOUNT_NAME}-pe" -l "$LOCATION" \
        --vnet-name "$VNET_NAME" --subnet private-endpoints \
        --private-connection-resource-id "$COSMOS_ID" --group-id Sql \
        --connection-name "${COSMOS_ACCOUNT_NAME}-pe-conn" -o none
    az network private-endpoint dns-zone-group create -g "$RG" \
        --endpoint-name "${COSMOS_ACCOUNT_NAME}-pe" -n default \
        --private-dns-zone privatelink.documents.azure.com --zone-name cosmos -o none
fi
# NOTE: there is deliberately NO VPN gateway — laptops never reach Cosmos
# directly. Outside-the-VNet access to app-state goes through the flow-mcp
# MCP server (deployed below); backend code dev uses the Cosmos emulator.

# ── 1b. Observability (Application Insights + Log Analytics) ───────────────
echo ">>> Ensuring Log Analytics workspace..."
az monitor log-analytics workspace create \
    --resource-group "$RG" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
    --location "$LOCATION" \
    -o none

LOG_ANALYTICS_WORKSPACE_ID=$(az monitor log-analytics workspace show \
    --resource-group "$RG" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
    --query id -o tsv)

# `az containerapp env create --logs-workspace-id` wants the customer GUID,
# not the ARM resource id (which App Insights' --workspace wants).
LOG_ANALYTICS_CUSTOMER_ID=$(az monitor log-analytics workspace show \
    --resource-group "$RG" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
    --query customerId -o tsv)

LOG_ANALYTICS_SHARED_KEY=$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "$RG" \
    --workspace-name "$LOG_ANALYTICS_WORKSPACE_NAME" \
    --query primarySharedKey -o tsv)

if [ -z "$APPLICATIONINSIGHTS_CONNECTION_STRING" ]; then
    echo ">>> Ensuring Application Insights CLI extension is installed..."
    az extension add --name application-insights --upgrade -y >/dev/null

    if ! az monitor app-insights component show \
        --app "$APPINSIGHTS_NAME" \
        --resource-group "$RG" \
        -o none >/dev/null 2>&1; then
        echo ">>> Creating Application Insights resource..."
        az monitor app-insights component create \
            --app "$APPINSIGHTS_NAME" \
            --resource-group "$RG" \
            --location "$LOCATION" \
            --workspace "$LOG_ANALYTICS_WORKSPACE_ID" \
            -o none
    else
        echo ">>> Reusing existing Application Insights resource..."
    fi

    APPLICATIONINSIGHTS_CONNECTION_STRING=$(az monitor app-insights component show \
        --app "$APPINSIGHTS_NAME" \
        --resource-group "$RG" \
        --query connectionString -o tsv)

    if [ -z "$APPLICATIONINSIGHTS_CONNECTION_STRING" ]; then
        echo "ERROR: Failed to provision Application Insights or retrieve its connection string."
        exit 1
    fi
fi

if [ -n "$APPLICATIONINSIGHTS_CONNECTION_STRING" ]; then
    echo "    App Insights: $APPINSIGHTS_NAME"
fi

# ── 2. User-Assigned Managed Identity ────────────────────────────────────
echo ">>> Creating managed identity..."
az identity create --name "$IDENTITY_NAME" --resource-group "$RG" -o none

IDENTITY_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RG" --query id -o tsv)
IDENTITY_CLIENT_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RG" --query clientId -o tsv)
IDENTITY_PRINCIPAL_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RG" --query principalId -o tsv)

echo "    Identity Client ID: $IDENTITY_CLIENT_ID"

# ── 3. Azure Container Registry ─────────────────────────────────────────
echo ">>> Creating container registry..."
az acr create --name "$ACR_NAME" --resource-group "$RG" --sku Basic --admin-enabled false -o none

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --resource-group "$RG" --query loginServer -o tsv)
echo "    ACR Login Server: $ACR_LOGIN_SERVER"

# Grant AcrPull to the managed identity
echo ">>> Granting AcrPull to managed identity..."
ACR_ID=$(az acr show --name "$ACR_NAME" --resource-group "$RG" --query id -o tsv)
az role assignment create \
    --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role AcrPull \
    --scope "$ACR_ID" \
    -o none

# ── 4. Cognitive Services role (Azure OpenAI + Content Understanding) ────
AZURE_ENDPOINT="${AZURE_ENDPOINT:-}"
if [ -z "$AZURE_ENDPOINT" ]; then
    echo "ERROR: AZURE_ENDPOINT must be set"
    exit 1
fi

# Cognitive Services User covers both OpenAI and Content Understanding
echo ">>> Granting Cognitive Services User to managed identity..."
AOAI_RESOURCE_NAME=$(echo "$AZURE_ENDPOINT" | sed -n 's|https://\(.*\)\.cognitiveservices.*|\1|p')
if [ -z "$AOAI_RESOURCE_NAME" ]; then
    # Try Foundry-style endpoint: https://name.services.ai.azure.com/
    AOAI_RESOURCE_NAME=$(echo "$AZURE_ENDPOINT" | sed -n 's|https://\(.*\)\.services\.ai\.azure\.com.*|\1|p')
fi
if [ -n "$AOAI_RESOURCE_NAME" ]; then
    AOAI_ID=$(az cognitiveservices account list --resource-group "$RG" \
        --query "[?name=='$AOAI_RESOURCE_NAME'].id" -o tsv 2>/dev/null || true)
    if [ -z "$AOAI_ID" ]; then
        echo "    Note: Cognitive Services resource not found in $RG. Assigning at subscription scope."
        az role assignment create \
            --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
            --assignee-principal-type ServicePrincipal \
            --role "Cognitive Services User" \
            --scope "/subscriptions/$(az account show --query id -o tsv)" \
            -o none
    else
        az role assignment create \
            --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
            --assignee-principal-type ServicePrincipal \
            --role "Cognitive Services User" \
            --scope "$AOAI_ID" \
            -o none
    fi
else
    echo "ERROR: Could not parse Cognitive Services resource name from AZURE_ENDPOINT=$AZURE_ENDPOINT"
    exit 1
fi

# ── 4b. ADLS Gen2 Storage ────────────────────────────────────────────────
# djgrfpagentadls is a moved-in account (eastus, not $LOCATION) — create only
# when absent, and never change its region.
if ! az storage account show --name "$ADLS_ACCOUNT_NAME" --resource-group "$RG" -o none 2>/dev/null; then
    echo ">>> Creating ADLS Gen2 storage account..."
    az storage account create \
        --name "$ADLS_ACCOUNT_NAME" \
        --resource-group "$RG" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --kind StorageV2 \
        --hns true \
        -o none
fi

# R18: storage stays network-private. Artifacts flow through the blob private
# endpoint (djgrfpagentadls-blob-pe); the dfs path (Library indexing) is parked
# with Search for MVP v1. MCAPS policy also enforces this posture.
echo ">>> Asserting storage public network access is disabled..."
az storage account update \
    --name "$ADLS_ACCOUNT_NAME" \
    --resource-group "$RG" \
    --public-network-access Disabled \
    -o none

echo ">>> Creating ADLS filesystem..."
az storage fs create \
    --name "$ADLS_FILESYSTEM" \
    --account-name "$ADLS_ACCOUNT_NAME" \
    --auth-mode login \
    -o none 2>/dev/null || true  # ignore "already exists"

echo ">>> Granting Storage Blob Data Contributor to managed identity on ADLS..."
ADLS_ID=$(az storage account show --name "$ADLS_ACCOUNT_NAME" --resource-group "$RG" --query id -o tsv)
az role assignment create \
    --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Contributor" \
    --scope "$ADLS_ID" \
    -o none

# ── 4c. Azure AI Search (Library / KB retrieval) — OFF for MVP v1 ────────
# Disabled by default per docs/mvp-requirements.md R18: library.py authenticates
# with the shared admin key (a plaintext-env shared secret) and the free SKU
# cannot use Private Link. The library search tool degrades gracefully when
# AZURE_SEARCH_ENDPOINT is unset. Re-enable with ENABLE_SEARCH=true once
# library.py moves to the managed-identity RBAC path.
SEARCH_NAME="${SEARCH_NAME:-${PREFIX}-srch}"
SEARCH_SKU="${SEARCH_SKU:-free}"
SEARCH_ENDPOINT=""
SEARCH_ADMIN_KEY=""
if is_truthy "$ENABLE_SEARCH"; then
    if ! az search service show --name "$SEARCH_NAME" --resource-group "$RG" -o none 2>/dev/null; then
        echo ">>> Creating Azure AI Search service ($SEARCH_SKU)..."
        az search service create \
            --name "$SEARCH_NAME" \
            --resource-group "$RG" \
            --location "$LOCATION" \
            --sku "$SEARCH_SKU" \
            --partition-count 1 \
            --replica-count 1 \
            -o none
    fi

    SEARCH_ENDPOINT="https://${SEARCH_NAME}.search.windows.net"
    # library.py authenticates with the admin key — thread it into the containers.
    SEARCH_ADMIN_KEY=$(az search admin-key show --service-name "$SEARCH_NAME" --resource-group "$RG" --query primaryKey -o tsv)
    echo "    Search endpoint: $SEARCH_ENDPOINT"

    # Grant Search roles to the managed identity
    echo ">>> Granting Search roles to managed identity..."
    SEARCH_ID=$(az search service show --name "$SEARCH_NAME" --resource-group "$RG" --query id -o tsv)
    az role assignment create \
        --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
        --assignee-principal-type ServicePrincipal \
        --role "Search Index Data Reader" \
        --scope "$SEARCH_ID" \
        -o none
    az role assignment create \
        --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
        --assignee-principal-type ServicePrincipal \
        --role "Search Service Contributor" \
        --scope "$SEARCH_ID" \
        -o none
else
    echo ">>> Skipping Azure AI Search (ENABLE_SEARCH=false — MVP v1 default)."
fi

# ── 5. Container Apps Environment (VNet-integrated) ──────────────────────
ACA_SUBNET_ID=$(az network vnet subnet show -g "$RG" --vnet-name "$VNET_NAME" -n aca-infra --query id -o tsv)
if az containerapp env show \
    --name "$ENV_NAME" \
    --resource-group "$RG" \
    -o none >/dev/null 2>&1; then
    echo ">>> Reusing Container Apps environment..."
else
    echo ">>> Creating Container Apps environment (VNet-integrated, $LOCATION)..."
    az containerapp env create \
        --name "$ENV_NAME" \
        --resource-group "$RG" \
        --location "$LOCATION" \
        --logs-workspace-id "$LOG_ANALYTICS_CUSTOMER_ID" \
        --logs-workspace-key "$LOG_ANALYTICS_SHARED_KEY" \
        --infrastructure-subnet-resource-id "$ACA_SUBNET_ID" \
        --enable-workload-profiles \
        -o none
fi

# ── 5b. Cosmos data-plane role (managed identity → app-state doc) ────────
echo ">>> Granting Cosmos DB Built-in Data Contributor to managed identity..."
az cosmosdb sql role assignment create -a "$COSMOS_ACCOUNT_NAME" -g "$RG" \
    --role-definition-id 00000000-0000-0000-0000-000000000002 \
    --principal-id "$IDENTITY_PRINCIPAL_ID" \
    --scope "$COSMOS_ID" -o none 2>/dev/null || true  # already exists on re-run

# ── 6. Build & Push Session Container Image ─────────────────────────────
echo ">>> Building session container image..."
SESSION_IMAGE="$ACR_LOGIN_SERVER/${IMG_PREFIX}-session:$SHA"
az acr build \
    --registry "$ACR_NAME" \
    --image "${IMG_PREFIX}-session:$SHA" \
    --image "${IMG_PREFIX}-session:latest" \
    --file session-container/Dockerfile \
    session-container/ \
    -o none

# ── 7. Create Session Pool (Custom Container) ───────────────────────────
echo ">>> Creating session pool..."

# Get the environment ID
ENV_ID=$(az containerapp env show --name "$ENV_NAME" --resource-group "$RG" --query id -o tsv)

# One env list for create AND update — the update path previously dropped the
# COSMOS_* vars, silently breaking agent tools on redeploys.
SESSION_ENV_VARS=(
    "AZURE_ENDPOINT=$AZURE_ENDPOINT"
    "AZURE_DEPLOYMENT=$AZURE_DEPLOYMENT"
    "ADLS_ACCOUNT_NAME=$ADLS_ACCOUNT_NAME"
    "ADLS_FILESYSTEM=$ADLS_FILESYSTEM"
    "AZURE_CLIENT_ID=$IDENTITY_CLIENT_ID"
    "COSMOS_ENDPOINT=$COSMOS_ENDPOINT"
    "COSMOS_DATABASE=$COSMOS_DATABASE"
    "COSMOS_CONTAINER=$COSMOS_CONTAINER"
    "APPLICATIONINSIGHTS_CONNECTION_STRING=$APPLICATIONINSIGHTS_CONNECTION_STRING"
    "OTEL_SERVICE_NAME=$OTEL_SERVICE_NAME"
    "OTEL_SERVICE_NAMESPACE=$OTEL_SERVICE_NAMESPACE"
    "OTEL_SERVICE_VERSION=$OTEL_SERVICE_VERSION"
    "OTEL_DEPLOYMENT_ENVIRONMENT=$OTEL_DEPLOYMENT_ENVIRONMENT"
)
if is_truthy "$ENABLE_SEARCH"; then
    SESSION_ENV_VARS+=(
        "AZURE_SEARCH_ENDPOINT=$SEARCH_ENDPOINT"
        "AZURE_SEARCH_KEY=$SEARCH_ADMIN_KEY"
        "AZURE_SEARCH_KB_NAME=$AZURE_SEARCH_KB_NAME"
    )
fi

if ! az containerapp sessionpool create \
    --name "$SESSION_POOL_NAME" \
    --resource-group "$RG" \
    --location "$LOCATION" \
    --environment "$ENV_ID" \
    --container-type CustomContainer \
    --image "$SESSION_IMAGE" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-identity "$IDENTITY_ID" \
    --target-port 8080 \
    --cooldown-period 300 \
    --network-status EgressEnabled \
    --max-sessions 20 \
    --ready-sessions "$SESSION_READY_SESSIONS" \
    --cpu 1.0 --memory 2Gi \
    --env-vars "${SESSION_ENV_VARS[@]}" \
    -o none 2>/dev/null; then
    echo "    Session pool exists, updating..."
    az containerapp sessionpool update \
        --name "$SESSION_POOL_NAME" \
        --resource-group "$RG" \
        --image "$SESSION_IMAGE" \
        --cooldown-period 300 \
        --max-sessions 20 \
        --ready-sessions "$SESSION_READY_SESSIONS" \
        --env-vars "${SESSION_ENV_VARS[@]}" \
        -o none
fi

POOL_ID=$(az containerapp sessionpool show \
    --name "$SESSION_POOL_NAME" \
    --resource-group "$RG" \
    --query id -o tsv)

# The containerapp extension has failed to apply --ready-sessions 0 in practice.
# Reassert through the ARM resource API and fail loudly if Azure keeps warm sessions.
az resource update \
    --ids "$POOL_ID" \
    --api-version "$SESSION_POOL_API_VERSION" \
    --set "properties.scaleConfiguration.readySessionInstances=$SESSION_READY_SESSIONS" \
    -o none

ACTUAL_READY_SESSIONS=$(az containerapp sessionpool show \
    --name "$SESSION_POOL_NAME" \
    --resource-group "$RG" \
    --query "properties.scaleConfiguration.readySessionInstances" -o tsv)

if [ "$ACTUAL_READY_SESSIONS" != "$SESSION_READY_SESSIONS" ]; then
    # The platform floors this at 1 (see SESSION_READY_SESSIONS above); report
    # the real value rather than failing the deploy — idle cost is tracked
    # against the ACTUAL number under R17/S7.
    echo "WARNING: Session pool ready sessions is $ACTUAL_READY_SESSIONS, requested $SESSION_READY_SESSIONS (platform floor)."
fi

# Managed identity INSIDE session containers (appdb → Cosmos, ADLS, OpenAI):
# assigning the identity to the pool only covers image pull. Session code gets
# a token endpoint only when managedIdentitySettings lifecycle=Main — without
# it DefaultAzureCredential fails with ClientAuthenticationError. No CLI flag
# for lifecycle as of Jul 2026, hence the raw PATCH.
echo ">>> Enabling managed identity inside session containers (lifecycle=Main)..."
az rest --method PATCH \
    --url "https://management.azure.com${POOL_ID}?api-version=${SESSION_POOL_API_VERSION}" \
    --body "{\"identity\":{\"type\":\"UserAssigned\",\"userAssignedIdentities\":{\"$IDENTITY_ID\":{}}},\"properties\":{\"managedIdentitySettings\":[{\"identity\":\"$IDENTITY_ID\",\"lifecycle\":\"Main\"}]}}" \
    -o none

POOL_ENDPOINT=$(az containerapp sessionpool show \
    --name "$SESSION_POOL_NAME" \
    --resource-group "$RG" \
    --query "properties.poolManagementEndpoint" -o tsv)

echo "    Pool Management Endpoint: $POOL_ENDPOINT"

# ── 8. Session Executor role (needed by orchestrator to call session pool) ─
echo ">>> Granting Session Executor to managed identity..."
az role assignment create \
    --assignee-object-id "$IDENTITY_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Azure ContainerApps Session Executor" \
    --scope "$POOL_ID" \
    -o none

# ── 9. Build & Push Orchestrator Image ───────────────────────────────────
echo ">>> Building orchestrator image..."
az acr build \
    --registry "$ACR_NAME" \
    --image "${IMG_PREFIX}-orchestrator:$SHA" \
    --image "${IMG_PREFIX}-orchestrator:latest" \
    --file Dockerfile \
    . \
    -o none

# ── 10. Deploy Orchestrator as Container App ─────────────────────────────
echo ">>> Deploying orchestrator container app..."
ORCHESTRATOR_IMAGE="$ACR_LOGIN_SERVER/${IMG_PREFIX}-orchestrator:$SHA"

ORCHESTRATOR_ENV_VARS=(
    "POOL_MANAGEMENT_ENDPOINT=$POOL_ENDPOINT"
    "COSMOS_ENDPOINT=$COSMOS_ENDPOINT"
    "COSMOS_DATABASE=$COSMOS_DATABASE"
    "COSMOS_CONTAINER=$COSMOS_CONTAINER"
    "ACS_EMAIL_ENDPOINT=$ACS_EMAIL_ENDPOINT"
    "ACS_SENDER_ADDRESS=$ACS_SENDER_ADDRESS"
    "REMINDER_EMAIL=$REMINDER_EMAIL"
    "AZURE_ENDPOINT=$AZURE_ENDPOINT"
    "ADLS_ACCOUNT_NAME=$ADLS_ACCOUNT_NAME"
    "ADLS_FILESYSTEM=$ADLS_FILESYSTEM"
    "ARTIFACTS_ACCOUNT=$ARTIFACTS_ACCOUNT"
    "ARTIFACTS_CONTAINER=$ARTIFACTS_CONTAINER"
    "AZURE_CLIENT_ID=$IDENTITY_CLIENT_ID"
    "API_AUTH_REQUIRED=$API_AUTH_REQUIRED"
    "DEMO_LOGIN_ENABLED=$DEMO_LOGIN_ENABLED"
)
if is_truthy "$ENABLE_SEARCH"; then
    ORCHESTRATOR_ENV_VARS+=(
        "AZURE_SEARCH_ENDPOINT=$SEARCH_ENDPOINT"
        "AZURE_SEARCH_KEY=$SEARCH_ADMIN_KEY"
        "AZURE_SEARCH_KB_NAME=$AZURE_SEARCH_KB_NAME"
    )
fi

if [ -n "$ENTRA_TENANT_ID" ]; then
    ORCHESTRATOR_ENV_VARS+=("ENTRA_TENANT_ID=$ENTRA_TENANT_ID")
fi
if [ -n "$ENTRA_API_CLIENT_ID" ]; then
    ORCHESTRATOR_ENV_VARS+=("ENTRA_API_CLIENT_ID=$ENTRA_API_CLIENT_ID")
fi
if [ -n "$ENTRA_ALLOWED_AUDIENCES" ]; then
    ORCHESTRATOR_ENV_VARS+=("ENTRA_ALLOWED_AUDIENCES=$ENTRA_ALLOWED_AUDIENCES")
fi

if ! az containerapp create \
    --name "$APP_NAME" \
    --resource-group "$RG" \
    --environment "$ENV_NAME" \
    --image "$ORCHESTRATOR_IMAGE" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-identity "$IDENTITY_ID" \
    --user-assigned "$IDENTITY_ID" \
    --target-port 8000 \
    --ingress external \
    --min-replicas "$ORCHESTRATOR_MIN_REPLICAS" \
    --max-replicas 3 \
    --env-vars \
        "${ORCHESTRATOR_ENV_VARS[@]}" \
    -o none 2>/dev/null; then
    echo "    Orchestrator app exists, updating..."
    az containerapp update \
        --name "$APP_NAME" \
        --resource-group "$RG" \
        --image "$ORCHESTRATOR_IMAGE" \
        --min-replicas "$ORCHESTRATOR_MIN_REPLICAS" \
        --max-replicas 3 \
        --set-env-vars \
            "${ORCHESTRATOR_ENV_VARS[@]}" \
        -o none
fi

if [ -n "$API_KEY" ]; then
    echo ">>> Setting orchestrator API key secret..."
    az containerapp secret set \
        --name "$APP_NAME" \
        --resource-group "$RG" \
        --secrets "api-key=$API_KEY" \
        -o none
    az containerapp update \
        --name "$APP_NAME" \
        --resource-group "$RG" \
        --set-env-vars "API_KEY=secretref:api-key" \
        -o none
fi

APP_URL=$(az containerapp show \
    --name "$APP_NAME" \
    --resource-group "$RG" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

echo "    App URL: https://$APP_URL"

# ── 11. Easy Auth (optional) ─────────────────────────────────────────────
# Requires ENTRA_TENANT_ID, ENTRA_API_CLIENT_ID, and ENTRA_CLIENT_SECRET to be set.
# The app registration itself must be created manually — this step only
# configures Easy Auth on the container app using the existing registration.
if [ -n "$ENTRA_TENANT_ID" ] && [ -n "$ENTRA_API_CLIENT_ID" ] && [ -n "$ENTRA_CLIENT_SECRET" ]; then
    echo ">>> Configuring Easy Auth on orchestrator..."
    # Store the client secret in the container app's secret store so it is
    # never passed as a CLI flag (which would expose it in process listings).
    az containerapp secret set \
        --name "$APP_NAME" --resource-group "$RG" \
        --secrets "entra-client-secret=$ENTRA_CLIENT_SECRET" \
        -o none
    az containerapp auth microsoft update \
        --name "$APP_NAME" --resource-group "$RG" \
        --client-id "$ENTRA_API_CLIENT_ID" \
        --client-secret-setting-name "entra-client-secret" \
        --issuer "https://login.microsoftonline.com/$ENTRA_TENANT_ID/v2.0" \
        --yes \
        -o none
    az containerapp auth update \
        --name "$APP_NAME" --resource-group "$RG" \
        --unauthenticated-client-action Return401 \
        -o none
    echo "    Easy Auth enabled."
else
    echo ">>> Skipping Easy Auth (ENTRA_TENANT_ID / ENTRA_API_CLIENT_ID / ENTRA_CLIENT_SECRET not set)."
fi

# ── 12. Build & Push Frontend Image ─────────────────────────────────────
echo ">>> Building frontend image..."
FRONTEND_IMAGE="$ACR_LOGIN_SERVER/${IMG_PREFIX}-frontend:$SHA"

# Derive redirect URI from frontend URL if not explicitly provided
FRONTEND_URL_PREVIEW="${FRONTEND_NAME}.$(az containerapp env show --name "$ENV_NAME" --resource-group "$RG" --query "properties.defaultDomain" -o tsv)"
RESOLVED_REDIRECT_URI="${ENTRA_REDIRECT_URI:-https://$FRONTEND_URL_PREVIEW}"

az acr build \
    --registry "$ACR_NAME" \
    --image "${IMG_PREFIX}-frontend:$SHA" \
    --image "${IMG_PREFIX}-frontend:latest" \
    --file frontend/Dockerfile \
    --build-arg "NEXT_PUBLIC_API_URL=https://$APP_URL" \
    --build-arg "NEXT_PUBLIC_AUTH_ENABLED=${API_AUTH_REQUIRED}" \
    --build-arg "NEXT_PUBLIC_ENTRA_TENANT_ID=${ENTRA_TENANT_ID}" \
    --build-arg "NEXT_PUBLIC_ENTRA_CLIENT_ID=${ENTRA_FRONTEND_CLIENT_ID}" \
    --build-arg "NEXT_PUBLIC_ENTRA_API_CLIENT_ID=${ENTRA_API_CLIENT_ID}" \
    --build-arg "NEXT_PUBLIC_ENTRA_API_SCOPES=${ENTRA_API_SCOPES}" \
    --build-arg "NEXT_PUBLIC_ENTRA_REDIRECT_URI=${RESOLVED_REDIRECT_URI}" \
    --build-arg "NEXT_PUBLIC_DEMO_LOGIN=${NEXT_PUBLIC_DEMO_LOGIN}" \
    frontend/ \
    -o none

# ── 13. Deploy Frontend as Container App ────────────────────────────────
echo ">>> Deploying frontend container app..."

if ! az containerapp create \
    --name "$FRONTEND_NAME" \
    --resource-group "$RG" \
    --environment "$ENV_NAME" \
    --image "$FRONTEND_IMAGE" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-identity "$IDENTITY_ID" \
    --target-port 3000 \
    --ingress external \
    --min-replicas "$FRONTEND_MIN_REPLICAS" \
    --max-replicas 3 \
    --cpu 0.25 --memory 0.5Gi \
    -o none 2>/dev/null; then
    echo "    Frontend app exists, updating..."
    az containerapp update \
        --name "$FRONTEND_NAME" \
        --resource-group "$RG" \
        --image "$FRONTEND_IMAGE" \
        --min-replicas "$FRONTEND_MIN_REPLICAS" \
        --max-replicas 3 \
        -o none
fi

FRONTEND_URL=$(az containerapp show \
    --name "$FRONTEND_NAME" \
    --resource-group "$RG" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

echo "    Frontend URL: https://$FRONTEND_URL"

# ── 13b. Build & Deploy app-state MCP server ────────────────────────────
if [ -n "$MCP_API_KEY" ]; then
    echo ">>> Building MCP server image..."
    MCP_IMAGE="$ACR_LOGIN_SERVER/${IMG_PREFIX}-mcp:$SHA"
    az acr build \
        --registry "$ACR_NAME" \
        --image "${IMG_PREFIX}-mcp:$SHA" \
        --image "${IMG_PREFIX}-mcp:latest" \
        --file Dockerfile.mcp \
        . \
        -o none

    echo ">>> Deploying MCP server container app..."
    if ! az containerapp create \
        --name "$MCP_NAME" \
        --resource-group "$RG" \
        --environment "$ENV_NAME" \
        --image "$MCP_IMAGE" \
        --registry-server "$ACR_LOGIN_SERVER" \
        --registry-identity "$IDENTITY_ID" \
        --user-assigned "$IDENTITY_ID" \
        --target-port 8080 \
        --ingress external \
        --min-replicas 0 \
        --max-replicas 1 \
        --cpu 0.25 --memory 0.5Gi \
        --secrets "mcp-api-key=$MCP_API_KEY" \
        --env-vars \
            "COSMOS_ENDPOINT=$COSMOS_ENDPOINT" \
            "COSMOS_DATABASE=$COSMOS_DATABASE" \
            "COSMOS_CONTAINER=$COSMOS_CONTAINER" \
            "AZURE_CLIENT_ID=$IDENTITY_CLIENT_ID" \
            "MCP_API_KEY=secretref:mcp-api-key" \
        -o none 2>/dev/null; then
        echo "    MCP app exists, updating..."
        az containerapp update \
            --name "$MCP_NAME" \
            --resource-group "$RG" \
            --image "$MCP_IMAGE" \
            -o none
    fi
    MCP_URL=$(az containerapp show --name "$MCP_NAME" --resource-group "$RG" \
        --query "properties.configuration.ingress.fqdn" -o tsv)
    echo "    MCP URL: https://$MCP_URL/mcp"
else
    echo ">>> Skipping MCP server (MCP_API_KEY not set)."
fi

# ── 14. Update orchestrator CORS with frontend URL ─────────────────────
echo ">>> Updating orchestrator CORS..."
az containerapp update \
    --name "$APP_NAME" \
    --resource-group "$RG" \
    --set-env-vars "FRONTEND_URL=https://$FRONTEND_URL" \
    -o none

# CORS at the ingress level runs before Easy Auth, so preflight (OPTIONS)
# passes through without a token.
echo ">>> Enabling ingress CORS..."
az containerapp ingress cors enable \
    --name "$APP_NAME" --resource-group "$RG" \
    --allowed-origins "https://$FRONTEND_URL" "http://localhost:3000" \
    --allowed-methods "*" \
    --allowed-headers "Authorization" "Content-Type" \
    --allow-credentials true \
    -o none

# ── 15. IP Restrictions ──────────────────────────────────────────────────
if [ -n "$ALLOWED_IP" ]; then
    echo ">>> Restricting ingress to $ALLOWED_IP..."
    az containerapp ingress access-restriction set \
        --name "$APP_NAME" --resource-group "$RG" \
        --rule-name "allow-my-ip" \
        --ip-address "$ALLOWED_IP" \
        --action Allow \
        -o none
    az containerapp ingress access-restriction set \
        --name "$FRONTEND_NAME" --resource-group "$RG" \
        --rule-name "allow-my-ip" \
        --ip-address "$ALLOWED_IP" \
        --action Allow \
        -o none
    echo "    IP restriction set."
else
    echo ">>> Skipping IP restriction (ALLOWED_IP not set)."
fi

# ── 16. Summary ─────────────────────────────────────────────────────────
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Frontend URL:             https://$FRONTEND_URL"
echo "Orchestrator URL:         https://$APP_URL"
echo "Pool Management Endpoint: $POOL_ENDPOINT"
echo "Managed Identity:         $IDENTITY_CLIENT_ID"
if [ -n "$APPLICATIONINSIGHTS_CONNECTION_STRING" ]; then
echo "Application Insights:     $APPINSIGHTS_NAME"
echo "Log Analytics workspace:  $LOG_ANALYTICS_WORKSPACE_NAME"
fi
echo ""
echo "AI Search (knowledge base):"
echo "  Endpoint:               $SEARCH_ENDPOINT"
echo "  KB Name:                $AZURE_SEARCH_KB_NAME"
echo ""
if [ -n "$ENTRA_TENANT_ID" ]; then
echo "Entra ID (auth):"
echo "  Tenant ID:              $ENTRA_TENANT_ID"
echo "  API Client ID:          $ENTRA_API_CLIENT_ID"
echo "  Frontend Client ID:     $ENTRA_FRONTEND_CLIENT_ID"
echo "  Redirect URI:           $RESOLVED_REDIRECT_URI"
else
echo "Entra ID: not configured (pass ENTRA_TENANT_ID / ENTRA_API_CLIENT_ID / ENTRA_FRONTEND_CLIENT_ID to enable)"
fi
echo ""
echo "Foundry tracing note: connect the Application Insights resource to your Foundry project"
echo "from Foundry portal -> Observability/Tracing before expecting traces in Foundry."
echo ""
echo "Next step: run 'uv run python setup_knowledge_base.py' to create the knowledge base."
echo ""
