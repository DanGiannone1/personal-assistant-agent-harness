# Azure deployment runbook

> **Purpose:** Operate the current guarded deployment; architecture authority remains in
> [Infrastructure](capabilities/infrastructure.md).
>
> **Verified application revision:** `807a0d6766036aa88dce8dcd9f16a2aabeb187b3`
>
> **Last verified:** 2026-07-16 in `csa-workbench-rg`, East US 2

## What this runbook deploys

The baseline creates one Container Apps Consumption environment with three apps: a public frontend,
a public API, and an internal session runtime. Each scales from zero to one replica. Cosmos DB and
Blob Storage disable public network access and use two private endpoints plus private DNS. Workload
access uses managed identity.

The same resource group owns the Basic Azure Container Registry and the Azure OpenAI account with
one 10K-TPM Standard `gpt-4.1` deployment. The registry retains its East US location while all other
application resources use East US 2. Azure OpenAI disables local-key authentication and remains on
identity-authenticated public TLS. Search, warm session pools, NAT Gateway, Firewall, Front Door,
APIM, VPN, and broader private ingress are not part of this profile.

Azure Container Apps creates a separate `ME_...` resource group for platform-managed load-balancer
infrastructure when the environment uses the application VNet. It is an Azure-owned implementation
detail, not an application dependency, and must not be modified.

Read [Infrastructure](capabilities/infrastructure.md) for the exact resource, identity, network,
cost, and exclusion contract before changing the deployment.

## Prerequisites

- Azure CLI with Bicep support and an authenticated account in the intended subscription.
- Permission to create subscription/resource-group deployments, reconcile the three dedicated
  Entra applications, assign the declared roles, build images, and create an Azure OpenAI model
  deployment.
- A clean Git worktree at the exact revision to deploy. Image tags are the full 40-character commit
  SHA; `latest` is not used.
- For the one-time legacy consolidation only: move `djgsharedacr` from `shared-services-rg` into
  `csa-workbench-rg` before running the deployment. Azure changes the resource ID during a move, so
  remove the old direct `AcrPull` assignments first; the foundation deployment recreates them at
  the destination. A fresh deployment creates the registry directly in the target group.

The script accepts narrow environment overrides such as `LOCATION`, `RESOURCE_GROUP`, `ACR_NAME`,
`ACR_LOCATION`, `AOAI_NAME`, and `AZURE_DEPLOYMENT`. Registry and model resources cannot be pointed
at another resource group. Review the defaults at the top of
[`infra/deploy.sh`](../infra/deploy.sh) before applying.

## Dry run

From the repository root:

```bash
./infra/deploy.sh
```

With `APPLY` unset or false, the script validates its tools and clean revision, compiles both Bicep
entrypoints, inspects any existing Container Apps environment, and runs the safe foundation what-if
when recovery state permits. It does not reconcile Entra, build images, or deploy resources.

If the named environment exists with an incompatible network contract, dry run fails closed and
reports that recovery requires an explicit apply. It does not delete the environment or pretend an
invalid what-if is useful.

## Apply

```bash
APPLY=true ./infra/deploy.sh
```

The apply path:

1. validates the existing environment and recovery allowlist;
2. if recovery is required, deletes only the three named apps and their named environment;
3. runs foundation what-if and deployment;
4. reconciles the three dedicated Entra registrations;
5. builds frontend, API, and runtime images at the same full Git SHA;
6. runs the app what-if and deployment; and
7. executes the live exact-inventory verifier.

The recovery allowlist is intentional. An unexpected app, environment, Entra shape, or resource
inventory fails closed rather than being adopted or deleted.

## What success means

The final verifier checks live Azure JSON. It requires:

- exactly the frontend, API, and internal runtime apps with the declared ports, resources, `0–1`
  scale, and identical SHA tags;
- the exact VNet, two subnets, two approved private endpoints, two private DNS zones/links/groups,
  and private A records;
- the Basic, admin-disabled registry and the AAD-only Azure OpenAI S0 account with exactly one
  Standard 10K-TPM `gpt-4.1` deployment;
- disabled Cosmos public/local-key access and disabled Storage public/shared-key/public-blob access;
- the required resource-scoped managed-identity and Cosmos data-plane roles, with every Azure RBAC
  scope contained by `csa-workbench-rg`; and
- the expected resource allowlist, excluding the deferred services named above.

Tenant policy may add one Defender for Storage Event Grid system topic and the exact
`StorageAntimalwareSubscription`. The application does not require them. The verifier accepts their
absence and validates their exact shape when present.

Tenant governance may also add no NSGs or the exact East US 2 pair named in
[Infrastructure](capabilities/infrastructure.md). Application Bicep declares no NSGs. When the pair
is present, the verifier requires both successful resources, no custom rules or NIC associations,
and only the approved ACA/private-endpoint subnet attachments. Partial, extra, or mismatched policy
state fails.

A successful deployment command or health endpoint alone is not acceptance. Follow
[Testing and evals](capabilities/testing-evals.md) for real-Entra, state, typed agent, Blob, browser,
and responsive evidence.

## Verified release observation

For `807a0d6766036aa88dce8dcd9f16a2aabeb187b3`:

- all three apps were healthy and pinned to that SHA;
- the frontend and API were public, the runtime was internal, and all apps were `0–1`;
- the frontend root and `/assistant` route returned `200`, and the API health endpoint returned
  `200`;
- real-Entra `/auth/me`, Engagement and quick-link reads, session creation, Cosmos-backed
  Engagement state readback, and a typed `list_engagements` Deep Agents turn succeeded;
- Blob upload/list/byte-for-byte download/delete succeeded with Storage public access disabled;
- the exact topology verifier passed, including the optional tenant-governance NSG pair;
- the Basic registry and all application-managed RBAC scopes were consolidated into
  `csa-workbench-rg`; and
- `shared-services-rg` retained only its unrelated Fabric capacity.

The application images remain stamped with the application revision above. The later verifier-only
commit `56d1fdd` changed `infra/deploy.sh` and its tests, not the application image contents; that
checked-in verifier was then run read-only against the deployed SHA.

The running URLs for that environment are:

- frontend: <https://csa-workbench-frontend.bluedesert-4d686b6f.eastus2.azurecontainerapps.io>
- API: <https://csa-workbench-api.bluedesert-4d686b6f.eastus2.azurecontainerapps.io>
- runtime: internal DNS only; it is not a public endpoint

The repository does not contain the raw deployment transcript, inventory JSON, Blob hash record,
timing log, or billing export. The observations above are release evidence recorded by the
[authoritative design](design.md), not replayable artifacts committed to Git.

## Workflow boundary

`.github/workflows/deploy.yml` is validation-only. It runs focused infrastructure contracts and
compiles Bicep; it has no deployment credential, image publication, Azure mutation, or release
evidence upload. The guarded manual script is the current deployment path.
