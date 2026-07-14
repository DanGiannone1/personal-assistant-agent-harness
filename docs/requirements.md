# CSA Workbench MVP Success Criteria

> **Authority:** Canonical MVP release bar
>
> **State:** Target until proven by evidence from the release revision
>
> **Applies to:** Product acceptance and release completion
>
> **Issue:** [#18](https://github.com/DanGiannone1/csa-workbench/issues/18)

## What the MVP must prove

CSA Workbench is successful when it is a working, professional engagement workspace for solution
architects and a clear reference implementation of agent-harness architecture. The application,
documentation, tests, and deployed environment must describe and prove the same behavior.

Accuracy and simplicity take precedence. Cost and latency are minimized within that boundary.

## Success criteria

### R1 — Cohesive, truthful documentation

The documentation flows from the executive overview in the root README to the authoritative design
and then to focused capability designs. It explains the working release in progressively deeper
detail without competing authorities or unlabelled aspirational claims.

### R2 — CSA Workbench deployment

The product is consistently branded **CSA Workbench** and can be deployed into a new, explicitly
named Azure resource group. The deployed profile contains only resources needed by the MVP and has
no accidental always-on cost.

### R3 — Real and deterministic users

Real people from the configured Entra tenant can sign in. Deterministic fake users exercise the
same product and authorization rules in test mode. Test identity support is explicit and cannot be
mistaken for tenant authentication.

### R4 — Personal and shared work

Each CSA has a personal space showing their own work. Engagements are shared only with
their members, and the effective actor and role are clear. One CSA cannot read or change another
CSA's private or non-member data.

### R5 — Basic Engagement workflow

A CSA can create, list, open, and edit an Engagement; manage its membership; and share its durable
record with another member. The manual UI and agent tools apply the same validation and
authorization rules and read back authoritative state after changes.

### R6 — Professional responsive experience

The existing polished visual character is preserved. The core journey remains clear and usable on
wide, compact, and 390 CSS-pixel narrow layouts, including loading, empty, validation, permission,
and failure states. Important actions are keyboard reachable and status is not communicated by
color alone.

### R7 — Structured agent behavior

The assistant reads and changes product state through explicit, typed tools and returns structured
outcomes. Navigation and other application control flow use validated structured events. No caller
parses user text, assistant text, marker strings, or raw stream prose to infer an action, route, or
successful commit.

### R8 — Meaningful evidence

Core journeys are proven with behavioral tests, a focused agent-evaluation set, and reviewed
Playwright screenshots of the real frontend at representative widths. Evidence identifies the
tested source revision and distinguishes local, synthetic-user, real-Entra, and deployed results.

## Acceptance journeys

### S1 — Personal portfolio and collaboration

Two different users sign in, see their own personal space, and see only Engagements where they are
members. One user creates an Engagement, adds the other, and both observe the same shared state.
An outsider cannot read it.

### S2 — Basic Engagement changes

An authorized member edits the Engagement through the UI and through an agent tool. Invalid or
unauthorized changes are rejected without changing authoritative state. Successful changes become
visible after authoritative refresh.

### S3 — Structured agent control

The assistant opens an Engagement and performs one supported change through typed tools and
structured results. Test inputs containing route names, tool names, marker-like strings, and
success-like prose cannot trigger navigation or a false success without the corresponding
structured event and committed outcome.

### S4 — Responsive UI/UX

The personal-space and Engagement journeys complete at wide, compact, and 390 CSS-pixel narrow
widths without page-level horizontal scrolling, clipped critical controls, or unusable navigation.
Reviewed screenshots capture the important states.

### S5 — Clean Azure deployment

The release revision deploys into the new CSA Workbench resource group. Real Entra sign-in and the
core Engagement journey work there. The resource inventory and configuration show the intended
scale-to-zero and low-cost profile, and observed latency is recorded rather than hidden.

## Evidence map

| Criterion | Detailed authority | Minimum acceptance evidence |
|---|---|---|
| R1 | [Authoritative design](design.md) | Link/authority/terminology audit against the release revision |
| R2 | [Infrastructure](capabilities/infrastructure.md) | Clean deployment record, resource inventory, branding scan |
| R3–R4 | [Identity and access](capabilities/identity-access.md) | Fake-user journey, real-Entra smoke, isolation probes |
| R5 | [CRUD](capabilities/crud.md) | UI/API/tool behavior reconciled with authoritative state |
| R6 | [UI/UX](capabilities/ui-ux.md) | Multi-width Playwright journey and reviewed screenshots |
| R7 | [Agent harness](capabilities/agent-harness.md) and [navigation](capabilities/navigation.md) | Typed contract tests and adversarial no-text-parsing cases |
| R8 | [Testing and evals](capabilities/testing-evals.md) | Criterion-level test, eval, screenshot, and deployment record |

## MVP boundary

The MVP does not require broad project-management modules, enterprise search, generalized
connectors, multi-agent orchestration, native mobile or offline support, high-scale topology,
multi-region recovery, or other production-hardening programs. A capability document may explain a
future reference pattern, but it cannot make that pattern an MVP requirement unless this file is
explicitly changed.

Completion is not inferred from code, prose, or a green build. Every criterion remains unverified
until the final release revision has the evidence named above.
