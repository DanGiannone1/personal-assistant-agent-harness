# CSA Workbench v1 Requirements and Acceptance Bar

> **Authority:** Canonical v1 product requirements and acceptance criteria  
> **State:** Target release bar subordinate to [the authoritative design](design.md)  
> **Baseline:** Reconciled with integrated `master@1fcaac6`; target behavior is not yet accepted  
> **Last reviewed:** 2026-07-14

## What v1 must prove

CSA Workbench v1 is a small but complete solution-architect Engagement workspace. It must prove that several
people can operate shared work through either the UI or an embedded assistant without losing track
of identity, scope, durable state, or truth.

This is a product acceptance bar, not a wish list and not an implementation design. The detailed
architecture lives in [design.md](design.md) and its capability documents.

## Product requirements

### Identity and scope

- **R1 — Real identity.** Internal users sign in through one Entra tenant. External and anonymous
  users are not supported.
- **R2 — Safe demo identity.** Seeded synthetic accounts support repeatable local and deployed
  journeys, can be disabled by backend configuration, use secret-managed credentials, and cannot
  access non-synthetic data.
- **R3 — Two explicit scopes.** Personal work is private to one actor. Engagement work is visible
  only to current members. The UI always makes the effective scope legible.
- **R4 — Consistent authorization.** Owner/editor/viewer rules are identical through UI, REST, and
  agent tools. Non-membership is indistinguishable from non-existence.
- **R5 — Attributable work.** Every committed Engagement change records the signed-in actor, source
  channel, request/turn correlation, changed resource, and safe summary.

### Engagement workspace

- **R6 — Engagement is primary.** The default landing is an Engagement portfolio. Any signed-in
  actor may create an Engagement and becomes its first owner.
- **R7 — Slim delivery record.** An Engagement exposes name, customer, description, optional target
  date, members, status, tasks, conventions, artifacts, and bounded activity.
- **R8 — Exact status contract.** Public wording is **Green / Yellow / Red**. Yellow or Red cannot be
  committed without a non-empty reason through any surface. Setting Green clears the blocker reason.
- **R9 — Fixed roles.** Viewers are read-only. Editors manage description, customer, target date,
  status, tasks, conventions, and artifacts. Owners additionally manage the name and membership. The
  final owner cannot be removed or demoted.
- **R10 — Authoritative state.** Manual and agent changes use the same validation, authorization,
  confirmation, concurrency, and outcome path. The UI reloads authoritative state after mutation.
- **R11 — Explicit keeping and sharing.** Conversation uploads and generated drafts remain private
  until the actor explicitly keeps one in their Personal Library or an editor/owner saves a distinct
  copy as a durable Engagement artifact.

### Assistant behavior

- **R12 — Product, not chat wrapper.** Every core Engagement journey remains available through the
  manual UI. Agent unavailability does not make the workspace unusable.
- **R13 — Grounded facts.** Changing Engagement facts come from live, permissioned product tools at
  answer time, never model memory or a stale prompt snapshot.
- **R14 — Truthful outcomes.** `noop`, confirmation, ambiguity, invalid input, denial, conflict, and
  failure cannot be narrated or painted as committed work.
- **R15 — Deterministic navigation.** Direct destinations navigate immediately. Natural-language
  navigation resolves against the actor's authorized destination catalog using deterministic
  lexical/context ranking. Bound alternatives require no second model pass.
- **R16 — Minimal context.** Each turn receives only authenticated identity, validated current view,
  active Engagement and membership role, minimal persona, applicable conventions, account time zone,
  and bounded authorized visit signals.
- **R17 — Legible context.** The user can open “What I used” for a completed turn and see the exact
  safe context snapshot, source reasons, omissions, and freshness that the runtime applied.
- **R18 — Harness portability.** Deep Agents is the deployed primary harness. Copilot implements the
  same v1 product/tool/event contract locally and remains a non-blocking portability check.

### Experience and accessibility

- **R19 — Professional workspace.** The interface prioritizes Engagement state and next work over
  assistant decoration. Dock and full workbench preserve one conversation and artifact selection.
- **R20 — Responsive web.** Core journeys work without page-level horizontal scrolling at wide,
  compact, and narrow web widths down to 390 CSS px. Narrow support does not imply a native or offline
  mobile application.
- **R21 — Accessible operation.** Core journeys meet WCAG 2.2 AA intent: complete keyboard access,
  visible focus, correct dialog behavior, status beyond color, associated errors, live updates,
  200% zoom/reflow, and reduced motion.

### Durability, platform, and evidence

- **R22 — Compute-independent state.** Actors, Engagements, conversations, transcripts, context/turn
  receipts, and metadata live in Cosmos; durable bytes live in Blob. Runtime memory and workspace are
  replaceable cache/scratch.
- **R23 — Conversation continuity.** A user can resume a conversation and its uploads after runtime
  scale-in or replacement. Starting a new conversation never resets personal or Engagement data.
- **R24 — Scale-to-zero profile.** Azure compute uses consumption Container Apps with zero minimum
  replicas. Cold starts are acceptable; warm pools and preview sandboxes are not v1 dependencies.
- **R25 — Essential service security.** Durable stores use private endpoints and managed identity
  with public/shared-key access disabled. Azure OpenAI uses workload identity; a model private
  endpoint is an optional hardened profile.
- **R26 — Derived Search only.** Core product behavior works with Search off. Search cannot be enabled
  until actor/realm/scope filtering, identity-based access, and cross-user isolation are proven.
- **R27 — Retrievable behavior receipt.** Every agent turn stores run, harness/model revision,
  applied context, safe tool arguments, structured outcomes, terminal state, and correlation IDs.
- **R28 — Repeatable evidence.** Synthetic seed/reset supports back-to-back test runs with equivalent
  starting state and no cross-user or cross-run leakage.
- **R29 — Three-view oracle.** Acceptance reconciles the real frontend, authoritative state, and the
  stored behavior receipt. Assistant wording alone is never proof.
- **R30 — Degraded truth.** Optional-service loss is explicit and leaves unaffected manual behavior
  usable. Unknown freshness or commit state is shown as unknown, never guessed.

## Acceptance scenarios

Every scenario records its starting state, action, expected result, and authoritative observation.
Exact assistant prose is not an oracle.

### S1 — Portfolio and shared status

Two actors sign in and see only their member Engagements. On a shared Engagement, an editor commits
Yellow with a reason; another member reloads and sees the same status/reason, and their agent reports
it from a live read. A non-member learns nothing about the Engagement.

### S2 — Role matrix

The real UI exposes no mutation affordance to a viewer. Direct viewer REST and agent attempts are
denied with no state or activity change. Editors and owners exercise every approved row; owner-only
membership rules and the final-owner invariant hold during concurrent updates.

### S3 — Status guard and common service

UI, direct API, Deep Agents, and Copilot all reject Yellow/Red without a reason and preserve the old
state. Equivalent valid changes produce the same structured status, state effect, and activity shape.
Green clears the obsolete blocker reason.

### S4 — Honest actions and navigation

Create/update, no-op, ambiguity, invalid input, confirmation, forbidden access, conflict, deliberate
tool failure, cancellation, and lost-response retry are exercised. Only a committed or resolved
structured destination moves the UI. Trace, reply, and refetched state agree.

### S5 — Durable private and shared files

A chat upload and transcript survive runtime replacement and resume privately. An explicitly kept
document remains in that actor's Personal Library. A generated draft is not visible to Engagement
members before explicit promotion. After an editor saves it, another member can list and open the
authenticated durable artifact; a viewer cannot upload or remove it.

### S6 — Context integrity

The stored `CONTEXT_APPLIED` snapshot matches “What I used” and the trace. A forged or inaccessible
route contributes no name, convention, candidate, or permission. Revocation after composition still
blocks the tool. Changing facts are read live.

### S7 — Responsive and accessible journeys

At representative wide, compact, and 390 px narrow viewports, a user can sign in, triage, open an
Engagement, change status, use the assistant, inspect context, confirm/cancel, and work with an
artifact without clipped controls or page-level horizontal scrolling. Automated accessibility
checks and manual keyboard/dialog/zoom/reduced-motion checks meet the documented bar.

### S8 — Harness and event contract

Deep Agents passes the complete release profile. Copilot passes the core contract locally. Both
expose the same approved tool schemas and structured outcomes, keep context separate from user text,
emit valid normalized event ordering with exactly one terminal event, and expose no shell, code,
filesystem escape, or subagent capability.

### S9 — Session and identity isolation

Switching actors clears the prior actor's browser/session state. Another actor cannot read, chat,
upload, trace, delete, or resume using a known foreign session ID. Session ownership remains bound
after cold start and all credential ambiguity fails closed.

### S10 — Azure reference profile

When deployment behavior changes, the Azure profile proves Entra/demo sign-in, private Cosmos/Blob
access through managed identity, no production shared keys, conversation/artifact rehydration after
scale-in, retrievable receipts, immutable deployed revision identity, and successful cold start from
zero replicas. Cost/billing observation is periodic architecture evidence, not a 24-hour gate on
unrelated product changes.

## Verification profiles

Use the smallest profile that covers the changed behavior; widening evidence without a risk reason is
not quality.

| Profile | Required evidence | When it applies |
|---|---|---|
| Documentation | Links, terminology, authority, current/target labels, diff scope | Documentation-only changes |
| Core product | Deterministic tests, relevant integration contracts, real-UI journeys, state/trace reconciliation | Product/domain/UI changes |
| Harness | Core product plus both adapters, event/cancel/failure cases, small eval set | Prompt, skill, tool, harness, or orchestration changes |
| Deployment | Deep Agents deployed journeys plus identity, private stores, durability, trace, scale-to-zero smoke | Infrastructure/deployment or runtime-boundary changes |

Runtime claims remain **UNVERIFIED** until supported by current captured evidence. Historical review
artifacts and static code inspection are useful inputs but do not accept the current build.

## Non-goals for v1

Stage/milestone/risk/action modules; Engagement calendar and reminder scheduler; standing approvals;
free-form durable memory; external identities; fine-grained policy; generalized connectors or
semantic layer; cross-Engagement search by default; generic workflows; agent code execution;
multi-agent orchestration; native/offline mobile; horizontal runtime scale; SLA, multi-region, DR,
enterprise security operations, and other production-hardening programs outside the essential trust
and durability boundaries above.
