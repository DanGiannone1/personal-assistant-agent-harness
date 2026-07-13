# Deployment

Personal Assistant deploys to Azure Container Apps: the orchestrator and frontend as Container Apps, and the agent
as a **custom-container session pool** (one isolated container per user). The runnable source of
truth is [`infra/deploy.sh`](../infra/deploy.sh) — this page explains its shape and the two failure
modes that have bitten us.

## What gets provisioned

[`infra/deploy.sh`](../infra/deploy.sh) provisions everything from scratch and is parameterised by a
`PREFIX` environment variable (override it to name your own resources). It creates:

- a user-assigned **managed identity**, an **Azure Container Registry**, and an **ACA environment**;
- the **private-networking layer** (VNets, peering, Cosmos private endpoint + private DNS — see below);
- the **session pool** (custom container image, `--max-sessions 20`, `--cooldown-period 300`,
  configurable `ready-sessions`, API version `2024-10-02-preview`);
- the **orchestrator** and **frontend** Container Apps (each `0–N` replicas);
- the **role assignments** below.

App-state (Cosmos), the Library index (Azure AI Search), upload originals (ADLS), Content
Understanding, and reminder email (ACS) are expected to exist or be configured via environment
variables — see [`.env.example`](../.env.example) and [retrieval.md](retrieval.md).

## Private networking (Cosmos)

Everything lives in **`flow-dev-rg`** (July 2026 rebuild). Cosmos (`flow-dev-cosmos`, **serverless**
capacity mode, AAD-only) has public network access **disabled** — an MCAPS management-group policy
(`CosmosDB_PublicNetwork_Modify`) force-disables it anyway — so all Cosmos traffic goes through a
**private endpoint**:

| Piece | Where | Why |
|---|---|---|
| `flow-dev-vnet` (10.20.0.0/16, eastus2) | `aca-infra` (10.20.0.0/23, delegated) + `private-endpoints` (10.20.2.0/24) | one VNet hosts the ACA env and the Cosmos PE (10.20.2.4 / .5) |
| Private DNS zone `privatelink.documents.azure.com` | linked to the VNet | resolves the account to the PE IPs inside Azure |

**No machine outside the VNet can reach Cosmos — by design, including dev laptops.** There is no
VPN (a VpnGw1AZ gateway was provisioned and deliberately retired on 2026-07-10 — at ~$140/mo it
only served laptop→Cosmos for local dev). The access paths are:

- **Using the app**: the frontend/orchestrator are public + auth'd; they do the Cosmos talking.
- **App-state access from laptops/agents** (Claude Code, schedulers): the **`flow-mcp`** Container
  App — an MCP server over streamable HTTP ([`mcp_server.py`](../mcp_server.py), scale-to-zero)
  that wraps `appdb` inside the VNet. Attach with:
  `claude mcp add --transport http flow https://<flow-mcp-fqdn>/mcp --header "x-api-key: <MCP_API_KEY>"`
- **Backend code development**: run the **Cosmos DB emulator** locally (Docker) and point
  `COSMOS_ENDPOINT` at it — real Cosmos is never reachable from a laptop.

The ACA environment is **VNet-integrated** (`flow-dev-env`); an environment can NEVER be moved
into a VNet after creation — getting this wrong means recreating the env and every app in it. The
session containers and orchestrator reach Cosmos through the PE; everything else (Search, ADLS,
OpenAI, ACS) is still public + AAD/keys.

Moved-in vs. recreated during the July 2026 rebuild: `rfpagent-ai` (OpenAI, kept its gpt-4.1
deployment + quota) and `djgrfpagentadls` (uploads) were **moved** across RGs; ACS email had to be
**recreated** (`flow-dev-acs`/`flow-dev-email` — Microsoft.Communication/EmailServices does not
support resource moves, so the sender address changed); Search was recreated as **free tier**
(`flow-dev-srch`, $0 — eastus, since eastus2 free tier had no capacity).

## Build & deploy

Images are built cloud-side with `az acr build` and deployed by **git SHA tag** (see the gotcha
below). Image and resource names derive from a `PREFIX` variable in
[`infra/deploy.sh`](../infra/deploy.sh) — which currently defaults to the legacy `taxagent`, so
override it — and the script is the authoritative source. The essence:

```bash
SHA=$(git rev-parse --short HEAD)
# Image names are <prefix>-session / -orchestrator / -frontend (see PREFIX in infra/deploy.sh)
az acr build --registry <acr> --image <prefix>-session:$SHA      --file session-container/Dockerfile session-container/
az acr build --registry <acr> --image <prefix>-orchestrator:$SHA --file Dockerfile .
az acr build --registry <acr> --image <prefix>-frontend:$SHA     --build-arg NEXT_PUBLIC_API_URL=<orchestrator-url> --file frontend/Dockerfile frontend/

az containerapp sessionpool update --name <pool> --resource-group <rg> --image <acr>/<prefix>-session:$SHA \
  --cooldown-period 300 --max-sessions 20 --env-vars <ALL VARS…>
az containerapp update --name <app>      --resource-group <rg> --image <acr>/<prefix>-orchestrator:$SHA
az containerapp update --name <frontend> --resource-group <rg> --image <acr>/<prefix>-frontend:$SHA
```

A session-pool update reprovisions containers (~2–3 min); the orchestrator/frontend update in ~30s.

## Gotchas that will silently bite you

1. **Never deploy `:latest`.** `az containerapp … --image repo:latest` is silently broken across all
   ACA services. ACA resolves the tag to a digest at revision-creation time and caches it; if the
   image *string* hasn't changed since the last revision, ACA no-ops — no new revision, no pull, old
   code keeps running. **Always use a changing tag (the git SHA).**
2. **`sessionpool update` without `--env-vars` wipes all environment variables.** Always re-specify
   the complete env-var set when updating the pool. `infra/deploy.sh` holds the authoritative list.
3. **`--ready-sessions 0` is no longer accepted** (since ~mid-2026, `SessionPoolInvalidReadySessionInstances`
   at create AND via the raw ARM API). The floor is 1: one warm session is always running and billed.
   Old pools created with 0 are grandfathered.
4. **Managed identity is NOT available inside session containers by default.** Assigning the
   identity to the pool only covers image pull. Code inside sessions (appdb → Cosmos etc.) gets a
   token endpoint only when the pool's `managedIdentitySettings` has `lifecycle: "Main"` — set via
   raw ARM PATCH (no CLI flag as of Jul 2026; `deploy.sh` does it). Without it,
   `DefaultAzureCredential` raises `ClientAuthenticationError` on the first data call.
5. **Dockerfile `COPY` lists drift from `import`s.** Both images enumerate the files they ship; a new
   module (or a new cross-container import like `app.py` → `session-container/appdb.py`) crash-loops
   the container at startup with `ModuleNotFoundError` — which surfaces from the session pool only as
   HTTP 429 on `POST /sessions`, because crashed sessions never become ready. Check
   `AppEnvSessionConsoleLogs_CL` in Log Analytics for the real traceback. (Bit us twice on 2026-07-10;
   the orchestrator also needs `.dockerignore`'s `!session-container/appdb.py` exceptions.)

## RBAC

The managed identity needs:

| Role | On | Why |
|---|---|---|
| AcrPull | Container Registry | Pull images |
| Cognitive Services User | Foundry / Azure OpenAI | Model + Content Understanding |
| Cosmos DB Built-in Data Contributor | Cosmos account | App state (AAD-only) |
| Storage Blob Data Contributor | ADLS | Upload originals + converted markdown |
| Search Index Data Reader · Search Service Contributor | Azure AI Search | Provisioned by `deploy.sh` |
| Azure ContainerApps Session Executor | Session pool | Orchestrator calls the pool |
| Email-send role *(granted manually)* | Communication Services | Scheduled-reminder email — **not** in `deploy.sh` |

Two notes: (1) although Search RBAC roles are provisioned, the agent's `search_documents` currently
authenticates with the **admin key** (`AZURE_SEARCH_KEY`), so set it. (2) The ACS email role is a
manual prerequisite — `deploy.sh` does not grant it.

## Auth

Two complementary layers, both optional and configured via [`.env.example`](../.env.example):

- **IP restriction** (`ALLOWED_IP`) locks the Container Apps to a single address.
- **Entra app registrations** (`API_AUTH_REQUIRED`, `ENTRA_*`) require a signed-in user at the API
  and enable browser sign-in. Two registrations are used: a backend/API app and a SPA app for the
  frontend.
