# Session Compute & User State — Design Decision

Status: DRAFT for decision, 2026-07-13. Companion to [mvp-requirements.md](mvp-requirements.md)
(R17 scale-to-zero conflict discovered at deploy time) and issue #10.

## The three kinds of state (don't conflate them)

1. **App data** — engagements, tasks, users, context. Lives in Cosmos (serverless, private,
   MI). Settled; no open question.
2. **Engagement artifacts** — shared team files. Azure Blob via managed identity behind a
   private endpoint. Built; satisfies R9/R10. No open question.
3. **Per-user session workspace** — mid-conversation uploads, generated files, running agent
   context. **Ephemeral in every configuration deployed so far.** This is the gap "persistent
   state via ACA sandboxes" addresses, and it is a product capability, not plumbing: *your
   workspace is where you left it.*

The open decision is the **session compute runtime**, which determines both the isolation
model and whether state-3 can persist.

## Options

| | A. Dynamic Sessions pool (deployed today) | B. Scale-to-zero app (merged, unapplied) | C. ACA Sandboxes (preview) |
|---|---|---|---|
| Isolation | Hypervisor, per session | Shared container; data-layer only (uid binding, per-session dirs) | MicroVM, per sandbox |
| Idle compute cost | **~$79/mo** (platform now floors pools at 1 warm instance; verified unbypassable) | $0 | **$0** (suspend releases compute) |
| Session workspace | Ephemeral (dies at cooldown) | Ephemeral (dies at scale-in) | **Persistent** — memory+disk suspend/resume (sub-second), snapshots, Blob/Data-Disk volumes |
| Warm start | Instant (that's what the $79 buys) | Cold start on first request after idle (seconds) | Sub-second resume from suspend |
| Maturity | Established preview, stable API | Plain ACA app — GA machinery | **Preview (Build '26)**: API may change, sandboxes may need recreation, VNet integration + MI image pull behind feature flags |
| Integration cost | None (running) | None (merged; repoint one env var) | New `session_manager` backend speaking the sandbox data plane (`management.azuredevcompute.io`), new RBAC role, per-user sandbox lifecycle mapping |
| Reaches private Cosmos | Yes (VNet env) | Yes (VNet env) | **Unverified** — custom VNet integration is behind a preview feature flag |
| Pricing | Known (ACA consumption) | Known (ACA consumption) | **Unpublished/TBD** for preview; snapshot storage billed |

## Assessment

- **C is the destination.** It is the only option that satisfies all three v1 pressures at
  once — strong isolation, true scale-to-zero, and persistent per-user state — and it adds
  the workspace-continuity capability the product story wants. It also future-proofs the
  isolation posture if the agent ever gains code-execution tools.
- **C is not a safe v1 gate this week.** Three unknowns must be resolved by a spike, not
  assumed: (1) VNet feature flag → can a sandbox reach the private Cosmos endpoint;
  (2) preview pricing and regional availability in eastus2; (3) API stability (Microsoft
  explicitly warns preview sandboxes may need recreation).
- **A vs B as the bridge** is a $79/month vs cold-start trade with no persistent workspace
  either way. B additionally trades away hypervisor isolation — acceptable today because the
  agent has no exec tool and file tools are workspace-dir-scoped, but it is a real
  defense-in-depth reduction.

## Recommendation

1. **Bridge (v1 gate):** run the deployed gate on **A (Dynamic Sessions, as deployed and
   working)**. Accept the ~$79/mo warm floor for the bridge period and annotate R17
   accordingly rather than swap runtimes mid-gate. B stays merged and one env-var away if
   the bridge cost is unacceptable.
2. **Target (v1.1):** a time-boxed **sandbox spike** — one sandbox group, session-container
   disk image, per-user sandbox with memory autosuspend, behind a new `session_manager`
   backend selected by env (same seam pattern as `AGENT_BACKEND`). Exit criteria: private
   Cosmos reachability through the VNet flag, measured resume latency, real pricing, and a
   user workspace surviving suspend→resume. Then migrate and delete the pool.
3. **Artifacts stay on Blob** regardless — sandbox Blob volumes can *mount* the same
   container later (nice convergence: the artifact store becomes visible inside the user's
   sandbox filesystem).

## Open questions for the spike

- Preview pricing model (compute-seconds while running; storage for memory snapshots).
- eastus2 availability; snapshot region-pinning implications for any future multi-region.
- Whether per-user (not per-session) sandboxes are the right granularity — one sandbox per
  user matches "your workspace," but concurrent sessions from one user then share a sandbox.
- Egress policy defaults (sandboxes add domain/CIDR egress controls — stronger than today).

Sources: [Sandboxes overview](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-overview),
[Snapshots & state management](https://learn.microsoft.com/en-us/azure/container-apps/sandboxes-snapshots-state-management),
live platform verification of the pool floor (2026-07-13, both API versions).
