# Infrastructure boundary

> **Authority:** Focused deployment-shape note. The executable [deployment runbook](../deployment.md) controls operation.

## What this deployment is

`infra/deploy.sh` creates an isolated instance from an explicit `INSTANCE_SLUG` and explicit model
inputs (`MODEL_DEPLOYMENT_NAME`, `MODEL_NAME`, `MODEL_VERSION`, `MODEL_SKU_NAME`,
`MODEL_CAPACITY`) — there is no fixed model or single shared deployment. The script plans by
default, performs guarded Azure reads/what-if, and requires the current plan's exact target-bound confirmation
before apply; see [deployment](../deployment.md) for the plan/apply procedure.

Each instance runs as three Container Apps in one Consumption environment. The frontend and API are
public; the internal session runtime accepts calls only from the API through an Entra workload role.
All three scale `0-1`; there is no warm pool.

## Verified resource shape

```text
resource group: csa-wb-<slug>-rg

Internet
  |-- public frontend Container App  (0-1, port 3000, 0.25 vCPU / 0.5 GiB)
  `-- public API Container App       (0-1, port 8000, 0.5 vCPU / 1 GiB)
        `-- Entra-authenticated HTTPS
              `-- internal runtime Container App (0-1, port 8080, 1 vCPU / 2 GiB)
                    `-- Azure OpenAI (model/SKU/capacity from MODEL_* inputs)

VNet 10.42.0.0/24
  |-- ACA infrastructure subnet 10.42.0.0/27
  `-- private-endpoint subnet 10.42.0.32/27
        |-- Cosmos DB Sql private endpoint + private DNS
        `-- Storage Blob private endpoint + private DNS
```

The resource group also owns a Basic Azure Container Registry (admin access disabled) and the Azure
OpenAI account/deployment. Azure Container Apps necessarily creates a separate Microsoft-managed
`ME_...` resource group for load-balancer infrastructure; it is not an application-owned dependency
and must not be modified.

## Data services

Cosmos DB uses the serverless capability, `disableLocalAuth: true`, and `publicNetworkAccess:
Disabled`. Blob Storage is `Standard_LRS` with `publicNetworkAccess: Disabled`,
`allowSharedKeyAccess: false`, and `allowBlobPublicAccess: false`; the `engagement-artifacts`
container is declared in Bicep rather than created by a best-effort application startup path. Both
use private endpoints and private DNS zones (`privatelink.documents.azure.com`,
`privatelink.blob.core.windows.net`) linked to the instance VNet — private access is part of the
baseline, not optional hardening.

The Azure OpenAI account disables local-key authentication (`disableLocalAuth: true`) but remains on
identity-authenticated public TLS; no Azure OpenAI private endpoint is provisioned.

## Identity and RBAC

Each workload has its own user-assigned managed identity:

| Identity | Declared access |
|---|---|
| Frontend | `AcrPull` only — no Cosmos, Blob, or Azure OpenAI data role |
| API | `AcrPull`; Cosmos DB Built-in Data Contributor; Storage Blob Data Contributor; runtime `invoke` application role |
| Runtime | `AcrPull`; Cosmos DB Built-in Data Contributor; Cognitive Services OpenAI User |

[`infra/entra.py`](../../infra/entra.py) creates or reconciles three single-tenant registrations per
instance (Web, API, Runtime). The API exposes the delegated `access_as_user` scope; the runtime
exposes the application-only `invoke` role, assigned to the API's managed identity. Runtime token
validation binds the configured tenant, audience, API identity object ID, and role.

## Deployment and recovery contract

The guarded [`infra/deploy.sh`](../../infra/deploy.sh) is the imperative edge for validation, Entra
setup, image builds, deployment, and post-deployment inspection over
[`infra/foundation.bicep`](../../infra/foundation.bicep),
[`infra/platform.bicep`](../../infra/platform.bicep), and
[`infra/apps.bicep`](../../infra/apps.bicep). It requires a clean worktree and tags all three images
with the full 40-character `git rev-parse HEAD` SHA — never `latest`.

`plan` authenticates, checks a guarded recovery precondition (an existing, differently-shaped
Container Apps environment for the same slug is a fail-closed condition, not something the script
silently adopts or deletes), and runs a foundation what-if. It prints a `PLAN_ID` and the exact
confirmation string `apply:<plan-id>:<resource-group>`. Only `apply --confirm '<that string>'`
mutates Azure, and it re-validates the plan before doing so — a stale or copied confirmation from an
earlier plan is rejected. Depending on the recovery state, apply deletes only the exact previously
approved recovery targets before foundation deployment, then reconciles Entra, builds images,
deploys apps, and runs the live inventory verifier described in
[deployment](../deployment.md#what-the-post-apply-verifier-checks).

Tenant-governance network security groups and a Defender-for-Storage Event Grid topic may exist
outside the application's own Bicep graph; the verifier tolerates their absence and validates their
exact shape only when present, and application Bicep never creates or deletes them.

## Cost boundary and deliberate exclusions

Zero minimum replicas remove an always-on compute floor; they do not make the deployment free. The
billing surface includes active Container Apps CPU/memory, Cosmos serverless requests/storage, Blob
LRS capacity/operations, two private endpoints and DNS zones, the Basic registry's fixed tier plus
image builds, and Azure OpenAI token usage. There is no checked-in cost export or numeric budget in
this repository.

The baseline has no Log Analytics workspace or Application Insights resource
(`logAnalyticsConfiguration: null` in the Container Apps environment) and excludes NAT Gateway, Azure
Firewall, Front Door/CDN, APIM, VPN, an ACA environment private endpoint, Search, and a warm session
pool. These exclusions are a release boundary, not a reusable decision for other risk profiles.

## Local topology

The local launcher preserves the three process boundaries but not Azure network parity — no private
endpoints, private DNS, or managed-identity workload call. It requires a separately supplied Cosmos
emulator; the repository does not start or configure one. See [development](../development.md) for
the exact local run and isolation variables.

## Evidence status

Focused infrastructure contract tests validate the verifier logic and Bicep-declared shapes against
fixtures (`tests/test_infra_entra_contract.py`); `az bicep build` compiles both entrypoints in
`npm run verify`. The checked-in GitHub Actions workflow (`.github/workflows/deploy.yml`) runs
`npm run verify:ci` and the Bicep compile step only — it has no deployment credential or Azure
mutation. **UNVERIFIED:** no deployment has been applied and observed from this repository; the
resource shapes above are proven by source and fixture-based contract tests, not by a live Azure
inventory read.

## Related authority

- [Design](../design.md)
- [Deployment runbook](../deployment.md)
- [Identity and access](identity-access.md)
- [Testing and evals](testing-evals.md)
