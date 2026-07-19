# Infrastructure Capability

> **Authority:** Capability detail subordinate to the
> [authoritative design](../design.md) and [v1 requirements](../requirements.md)
>
> **Deployed application revision:** `807a0d6766036aa88dce8dcd9f16a2aabeb187b3`
>
> **Deployment recorded by the design:** 2026-07-16, `csa-workbench-rg`
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## What this deployment is

CSA Workbench runs as three small Azure Container Apps in one Consumption environment. The
frontend and API are public. The session runtime is internal and accepts calls from the API through
an Entra workload role. All three apps scale from zero to one replica; there is no warm pool.

Cosmos DB holds durable actors and Engagement records, and Blob Storage holds durable Engagement
artifact bytes. Their public endpoints are disabled and their application paths use private
endpoints and managed identity. Agent conversations, chat uploads, runtime workspaces, and local
traces remain ephemeral in this release. Replacing compute can lose them, while Engagement records
and saved Engagement artifacts remain outside compute.

The release is intentionally a small, single-region deployment. It does not claim multi-region
recovery, multi-replica session coordination, durable conversations, behavior-receipt storage, or
an enterprise network edge.

## Verified Azure shape

The authoritative design records the following deployment in East US 2:

```text
resource group: csa-workbench-rg

Internet
  |-- public frontend Container App (0-1)
  `-- public API Container App (0-1)
        `-- Entra-authenticated HTTPS
              `-- internal runtime Container App (0-1)
                    `-- Azure OpenAI gpt-4.1 (Standard, 10K TPM)

Basic Azure Container Registry
  `-- three immutable SHA-tagged application images

VNet 10.42.0.0/24
  |-- ACA infrastructure subnet 10.42.0.0/27
  `-- private-endpoint subnet 10.42.0.32/27
        |-- Cosmos DB Sql private endpoint + private DNS
        `-- Storage Blob private endpoint + private DNS
```

One VNet-integrated Container Apps Consumption environment hosts all three apps. The runtime app
uses internal ingress, but the environment is not an environment-wide private-ingress deployment.

| Workload | Ingress | Scale | CPU / memory | Durable local state |
|---|---|---:|---:|---|
| `csa-workbench-frontend` | Public, port 3000 | 0-1 | 0.25 / 0.5 GiB | None |
| `csa-workbench-api` | Public, port 8000 | 0-1 | 0.5 / 1 GiB | None |
| `csa-workbench-runtime` | Internal, port 8080 | 0-1 | 1 / 2 GiB | None |

The application resource group owns the environment and apps, three user-assigned managed
identities, VNet, subnets, Cosmos account/database/container, Storage account/Blob container, two
private endpoints, two private DNS zones and links, the Basic registry, and the Azure OpenAI account
and deployment. There are no application-managed Azure dependencies in another resource group.

The registry retains the globally unique `djgsharedacr` name and East US location because moving the
existing Basic registry avoids paying for a duplicate fixed-cost registry. The Azure OpenAI account
is `csa-workbench-ai` in East US 2. It disables local-key authentication and exposes one Standard
10K-TPM `gpt-4.1` deployment (`2025-04-14`); Standard capacity limits throughput but is billed by
token use rather than as provisioned hourly model compute. The runtime reaches it through
identity-authenticated public TLS, and no Azure OpenAI private endpoint is provisioned.

The VNet-integrated Container Apps environment necessarily has a separate
`ME_csa-workbench-env_csa-workbench-rg_eastus2` resource group containing Azure-managed public-IP
and load-balancer resources. Microsoft documents that this group is created and operated by the
Container Apps platform and must not be modified. It is the sole resource-group exception and is
not an application-owned dependency.

## Identity and data paths

Each workload has its own user-assigned managed identity:

| Identity | Repository-declared access |
|---|---|
| Frontend | `AcrPull` on the CSA-owned registry |
| API | `AcrPull`; Cosmos DB Built-in Data Contributor; Storage Blob Data Contributor; runtime `invoke` application role |
| Runtime | `AcrPull`; Cosmos DB Built-in Data Contributor; Cognitive Services OpenAI User |

The [Entra helper](../../infra/entra.py) creates or reconciles three single-tenant registrations:
`CSA Workbench Web`, `CSA Workbench API`, and `CSA Workbench Runtime`. The API exposes the delegated
`access_as_user` scope. The runtime exposes the application-only `invoke` role, assigned to the API
managed identity. Runtime token validation binds the configured tenant, audience, API identity
object ID, and role. The helper rejects duplicate or conflicting dedicated registrations before
mutation and only reconciles the narrow shapes it owns.

Cosmos DB uses the serverless capability and disables local authentication and public network
access. Blob Storage is Standard LRS, disables shared-key and public-blob access, and disables public
network access. The `engagement-artifacts` container is declared in Bicep rather than created by a
best-effort application startup path.

Private access is part of the baseline, not optional hardening:

- Cosmos uses the `Sql` private-link group and `privatelink.documents.azure.com`;
- Blob uses the `blob` private-link group and `privatelink.blob.core.windows.net`;
- both private DNS zones link to `csa-workbench-vnet`; and
- the verifier requires the endpoint connections to be approved and their A records to resolve
  inside `10.42.0.32/27`.

## Deployment and recovery contract

[Bicep](../../infra/foundation.bicep) owns the resource graph. The guarded
[deployment script](../../infra/deploy.sh) is its imperative edge for validation, Entra setup,
image builds, deployment, and post-deployment inspection.

The script requires an Azure CLI session, Bicep support, a clean worktree, and the full
40-character SHA returned by `git rev-parse HEAD`. It builds all three images with that SHA as the
tag; [the apps module](../../infra/apps.bicep) accepts only a 40-character tag. The final verifier
requires every running image reference to use the same exact SHA and never relies on `latest`.

The safe sequence is:

1. Build both Bicep entrypoints locally and inspect any existing Container Apps environment.
2. If the environment is absent or already matches the VNet/Consumption contract, run the
   subscription foundation what-if. With `APPLY` false, stop there without Azure or Entra mutation.
3. If the named environment is incompatible, fail closed unless exactly the three named apps are
   attached. A dry run reports that recovery needs `APPLY=true` and does not run a misleading
   foundation what-if. On the apply path, delete only those three apps and that environment before
   the foundation what-if and deployment.
4. Apply the foundation, reconcile the three dedicated Entra registrations, and build the three SHA
   images.
5. Run the resource-group app what-if, deploy the apps, and execute the live inventory verifier.

The current environment required one migration before this sequence: remove the three direct
`AcrPull` assignments from `djgsharedacr`, move that registry from `shared-services-rg` into
`csa-workbench-rg`, and let the foundation deployment recreate the same least-privilege assignments
at the new resource ID. The move preserves the registry, images, login server, region, and single
Basic-SKU cost.

The app what-if occurs after the foundation, Entra, and image steps on the apply path; it previews
the app deployment, not those earlier mutations. Recovery ordering and fail-closed cases are covered
by the focused infrastructure tests.

The checked-in [GitHub workflow](../../.github/workflows/deploy.yml) is validation-only. On pushes,
pull requests, or manual dispatch it runs the focused infrastructure contracts and compiles the two
Bicep entrypoints. It has no deployment credentials, OIDC permission, image publication, Azure
deployment, or release-evidence upload.

## What the post-deployment verifier proves

After an applied deployment, the embedded verifier checks live Azure JSON rather than treating a
successful command as sufficient. It requires:

- exactly the three named Container Apps in one Consumption environment, with the ingress, ports,
  0-1 scale, resources, provisioning state, and SHA image references shown above;
- one Basic registry with admin access disabled, and one AAD-only OpenAI S0 account with exactly one
  Standard 10K-TPM `gpt-4.1` deployment;
- the exact VNet and two-subnet shape, two approved private endpoints, two private DNS zones and
  links, endpoint zone groups, and matching private A records;
- disabled Cosmos local/public access and disabled Storage public/shared-key/public-blob access;
- the required ACR, Cosmos, Blob, and Azure OpenAI role assignments, with every Azure RBAC scope for
  the three workload identities contained by `csa-workbench-rg`; and
- the owned resource inventory with Search, session pools, telemetry workspaces, APIM, CDN/Front
  Door, NAT, Firewall, VPN gateways, and route tables absent. Application Bicep declares no network
  security groups.

The RBAC verifier proves that the required roles exist and that these identities have no
subscription-scoped assignment. It does not reject every possible extra resource-scoped role, so it
is not by itself a complete least-privilege audit. The verifier prints results but does not create a
checked-in deployment record.

Tenant policy may add one Defender for Storage Event Grid system topic and its event subscription.
They are not application-owned topology. Their absence is accepted. When present, the verifier
requires exactly one topic sourced from this Storage account with type
`Microsoft.Storage.StorageAccounts` and successful provisioning, plus exactly one successful
subscription named `StorageAntimalwareSubscription`. Extra or malformed topic/subscription
artifacts fail verification.

Tenant governance may add no network security groups or exactly
`csa-workbench-vnet-aca-infrastructure-nsg-eastus2` and
`csa-workbench-vnet-private-endpoints-nsg-eastus2`; they remain outside the application-owned
topology. When present, the verifier requires the complete East US 2 pair to have succeeded, no
custom security rules, and no network-interface associations. The private-endpoints NSG must be
attached only to the private-endpoints subnet; the ACA NSG may be unattached while governance
attachment is asynchronous or attached only to the ACA infrastructure subnet. Any partial, extra,
or otherwise mismatched NSG inventory fails verification. Before foundation mutation, the guarded
deployment validates that optional inventory and passes the two existing IDs into Bicep so a VNet
update preserves the approved associations. It never creates or deletes those governance resources.

## Cost boundary and deliberate exclusions

Zero minimum replicas remove an intentional always-on **compute** floor; they do not make the
deployment free. The actual billing boundary includes:

- active Container Apps CPU and memory;
- Cosmos serverless requests and storage;
- Blob LRS capacity, operations, and transfer;
- two private endpoints and two private DNS zones;
- the one Basic registry's fixed tier plus image build/storage/pull activity;
- Azure OpenAI input/output tokens on the Standard deployment; and
- any tenant-policy Defender for Storage charges that apply outside the application-owned graph.

There is no checked-in Azure cost export or numeric budget, so no dollar amount is claimed here.
Azure billing and usage data remain the oracle. The authoritative design records an observed
scale-to-zero cold start of roughly 24 seconds; this repository contains no raw timing log for that
observation. The latency is accepted for this cost-minimized release.

The baseline has no Application Insights or Log Analytics resources and explicitly configures the
Container Apps environment without that log destination. It also excludes NAT Gateway, Azure
Firewall, Front Door/CDN, APIM, VPN, an ACA environment private endpoint or environment-wide private
ingress, Search, Dynamic Sessions or another warm pool, and unrelated hardening. The runtime's
internal app ingress, Cosmos/Blob private endpoints, and managed-identity controls remain required
parts of the baseline.

These exclusions are a release boundary, not a reusable decision for other risk profiles. Any
change to it requires the product, architecture, security, and evidence decision owned above this
capability document.

## Failure and replacement behavior

The authoritative design defines these boundaries. Except for the recorded cold start and successful
release smoke, this repository has no checked-in deployed failure-injection record for them.

| Condition | Design contract |
|---|---|
| Frontend/API/runtime scaled to zero | The request waits for a cold start; the live deployment observed roughly 24 seconds |
| Runtime or Azure OpenAI unavailable | Agent work fails visibly; manual Engagement work remains a separate path |
| Cosmos unavailable | Durable Engagement operations fail; Azure compute does not fall back to process or local-file state |
| Blob unavailable | Artifact byte operations fail rather than implying that durable bytes exist |
| API or runtime replaced | The frontend establishes a new ephemeral agent session; durable Engagement records and saved artifacts remain |
| Search absent | Core navigation, Engagement operations, and direct authorized artifact work remain; semantic retrieval is unavailable |

There is no deployed multi-replica recovery protocol to describe: every app is bounded at one
replica. There is also no durable conversation rehydration or Cosmos behavior-receipt contract in
this release. Structured tool outcomes and authoritative Engagement readback are product evidence;
they are not an infrastructure receipt store.

## Local topology

The local launcher preserves the three process boundaries but not Azure network parity:

```text
browser -> frontend :3000 -> API :8000 -> runtime :8080 -> Azure OpenAI
                              |             |
                              `------ Cosmos emulator supplied separately
API -> local artifact directory
```

[`dev.py`](../../dev.py) requires `IDENTITY_MODE=demo`, points the API at the local runtime, clears
the runtime workspace and local traces at startup, and launches all three processes. The application
still requires Cosmos. The repository does not provision or configure a Cosmos emulator; the
checked-in Compose file also starts only the three application services. A developer must supply
the emulator endpoint and emulator-only key separately. Local artifact bytes use
`ARTIFACTS_DIR` unless an Azure Blob account is explicitly configured; Azurite is not wired by the
repository. Azure OpenAI is the ordinary remote dependency and uses the developer's Azure identity.

This local profile has no private endpoints, private DNS, managed workload call, or Azure scale
behavior. It is useful for product tests, not proof of the deployed topology. Follow the
[local development runbook](../development.md) for configuration and the
[testing capability](testing-evals.md) for evidence handling.

## Evidence status and source map

Repository-verifiable contracts are separate from observations of the live release:

| Evidence kind | What is available |
|---|---|
| Repository contract | Bicep resource declarations, guarded deployment/recovery/verifier logic, Entra desired-shape helper, validation-only workflow, and focused contract tests |
| Live release evidence recorded by the authoritative design | East US 2 deployment in `csa-workbench-rg`; frontend/API health, real-Entra identity, Engagement and quick-link reads, session creation, authoritative Engagement readback, a typed Deep Agents turn, private Blob round trip, exact topology and RBAC containment, the registry consolidation, exact tenant-governance NSG pair, and the earlier roughly 24-second cold-start observation |
| Not checked in | Azure CLI inventory or NSG JSON, what-if output, deployment transcript, private-DNS probe output, replica metrics, timing log, billing export, or cost estimate |
| Remaining live evidence named by the design | A second real tenant actor and an interactive real-Entra browser journey |

Use these local sources to inspect or validate the contract:

- [foundation entrypoint](../../infra/foundation.bicep),
  [platform resources](../../infra/platform.bicep), and [apps](../../infra/apps.bicep);
- [deployment and verifier](../../infra/deploy.sh) and [Entra helper](../../infra/entra.py);
- [infrastructure/Entra contracts](../../tests/test_infra_entra_contract.py) and
  [runtime release boundaries](../../tests/test_release_boundaries.py); and
- [authoritative design](../design.md), [v1 requirements](../requirements.md), and
  [local development](../development.md).

Safe repository checks are:

```bash
PYTHONPATH=$PWD:$PWD/session-container uv run --project session-container --with pytest \
  pytest -q tests/test_infra_entra_contract.py tests/test_release_boundaries.py
az bicep build --file infra/foundation.bicep --outfile /tmp/csa-workbench-foundation.json
az bicep build --file infra/apps.bicep --outfile /tmp/csa-workbench-apps.json
bash -n infra/deploy.sh
```

These checks validate source contracts and syntax. They do not deploy, mutate Entra, or prove the
live Azure observations above.
