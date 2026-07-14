# Deployment status

The current deployment script and GitHub workflow are **UNVERIFIED** implementation
artifacts. They are not an approved deployment runbook and this page makes no claim
that running either produces the target CSA Workbench profile. Do not treat a successful CLI
command, workflow, image build, or health endpoint as deployment evidence.

The authoritative Azure topology, identity boundaries, scale contract, deployment
oracles, and target local profile are in
[Infrastructure](capabilities/infrastructure.md). The release evidence required for
deployment-affecting work is in [Testing and evals](capabilities/testing-evals.md).

## Target profile

The intended baseline is three Container Apps consumption workloads: external
frontend and orchestrator, plus an internal session runtime. Cosmos serverless and
Blob are private, durable stores; workloads use scoped managed identities; Search is
off by default; all compute can scale to zero. Deep Agents is the deployed primary
harness. Copilot is a local, reported portability check, not a release gate.

This section describes the target only. It does not assert that the integrated
scripts, cloud resources, or a running revision satisfy it.

## Current static blockers

Inspection of `infra/deploy.sh`, `.github/workflows/deploy.yml`, and the integrated
runtime identifies blockers already reconciled in the Infrastructure capability:

- the script and workflow describe different, legacy deployment shapes; the workflow
  is not a reliable representation of the current script or target baseline;
- the workflow uses a long-lived Azure credential and lacks the target behavioral
  gates; the target requires GitHub OIDC and exact-revision evidence;
- process-local session, conversation, upload, and authorization state prevents the
  required rehydration and safe multi-replica behavior;
- the script permits orchestrator replicas beyond the process-local ownership model,
  includes a subscription-scope role fallback, and disables runtime pool
  authentication in its default path;
- the optional Search path injects an admin key into workload configuration, so it
  must remain off; and
- current traces are local files rather than actor-authorized durable behavior
  receipts.

Additional local-topology and current-versus-target findings, including the missing
emulator wiring, are maintained in
[Infrastructure](capabilities/infrastructure.md#current-integrated-state-versus-target).

## Safe posture

Do not deploy from this checkout on the strength of the existing script or workflow.
Before an authorized deployment, resolve the blockers above and run the affected
deployed-behavior profile against an identified revision: identity, private data
paths, durable state and receipts, replica/scale behavior, and a real browser
journey must agree. Until then, deployment state, runtime behavior, and operational
claims remain **UNVERIFIED**.
