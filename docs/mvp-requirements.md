# Engagement Workspace MVP — Requirements

Status: agreed direction, 2026-07-13. Pure requirements and success criteria — no
implementation detail. Background: [manifesto](manifesto.md), [engagements](engagements.md).

**Goal.** A multi-user engagement workspace deployed to Azure that proves the
architecture — a shared, role-gated engagement entity; per-user identity flowing to the
agent; deterministic navigation; legible context — before any further domain complexity
is added. Start small, observe it working in production, then grow.

## Users & identity

- **R1** — Users are members of our internal tenant and sign in with their real
  organizational identity (Entra ID). No external audience.
- **R2** — Seeded demo accounts also work, through the app's own sign-in, so automated
  tests can drive the deployed app without interactive corporate login. Demo accounts
  carry no elevated privileges, hold only synthetic data, and can be switched off by
  configuration without a redeploy.
- **R3** — A user sees only the engagements they are a member of. Roles are
  owner / editor / viewer and are enforced identically in the UI, the REST API, and the
  agent's tools. Non-membership is indistinguishable from non-existence.
- **R4** — Every agent action is attributable to the signed-in user: the agent acts as
  that user, sees only their world, and its writes land in their name.

## Engagement (v1 scope)

- **R5** — An engagement carries: name, customer, description, members with roles,
  status, documents/artifacts, tasks, working conventions, and an activity log.
- **R6** — Status is **Green / Yellow / Red** (this wording, everywhere). Yellow or Red
  always carries a "why"; a status change without one is impossible through any surface
  — UI, REST, or agent.
- **R7** — Parked for a later release (out of v1's visible surface, in any harness or
  screen): stage pipeline, milestones, risks, actions, engagement-scoped calendar,
  standing approvals, free-form agent memories.
- **R8** — Personal space ("your stuff": tasks, notes, reminders) remains separate from
  engagements ("our stuff") per the manifesto's two-scope model.

## Documents / artifacts

- **R9** — An engagement has artifacts that persist independently of any agent session's
  lifetime: files survive session container restarts and are visible to every member.
  Acceptable backing: Azure Blob storage or Container Apps session persistence (preview)
  — whichever, the requirement is durability plus member-only access.
- **R10** — Members can add, list, and open artifacts; removing one requires editor or
  above. No anonymous or public access path exists.

## Agent

- **R11** — Two harnesses remain behind one seam, selectable by configuration. The
  deepagents (LangGraph) harness is primary: every v1 capability must work there, and it
  is the one proven on Azure. The Copilot harness is secondary: kept working for v1
  capabilities locally, but it never blocks a release.
- **R12** — Grounded answers: engagement facts come from live state at answer time,
  never from model memory. A failed or no-op tool call is never narrated as success.
- **R13** — Navigation is resolved deterministically from intent, membership, and
  recency. Ambiguity and "decided, with alternates" both surface as fully-bound chips;
  clicking a chip is a plain navigation with no second model pass.
- **R14** — The agent's tool surface reflects v1 scope only (parked capabilities expose
  no tools).

## User context (MVP)

- **R15** — Each agent turn is personalized by a context bundle limited to: identity and
  role, working context (active engagement, recent visits), minimal persona (role, tone,
  language), and the engagement's conventions. Precedence: turn instruction › engagement
  convention › persona › app default.
- **R16** — Context is legible: the UI can show, for the last turn, exactly what
  personalized it.

## Platform & cost

- **R17** — Deployed on Azure and reachable by tenant users. All compute scales to zero
  when idle; data services use serverless/consumption tiers. No always-on premium SKUs.
  Target: monthly cost at demo usage stays under ~$100, with idle compute cost at zero.
- **R18** — Data paths are private: no public network access to data stores, identity-
  based auth for services, and no shared keys in production configuration. (Local dev
  against an emulator is exempt.)
- **R19** — Every agent turn leaves a retrievable trace (tool calls, outcomes, context
  bundle used) sufficient to debug behavior after the fact.

## Success criteria

All criteria are observed against the **deployed Azure app**, not just locally.

- **S1** — A Playwright suite runs against the deployed URL using demo accounts and
  passes: sign-in isolation (two users, two worlds), membership trimming, viewer has
  zero mutation affordances, the G/Y/R why-guard (Yellow/Red blocked without a why;
  commits with one; survives reload), artifact upload by one member visible to another,
  and the two-user navigation demo ("take me to the launch tasks" lands each user in
  *their* engagement). Assertions check agent traces, not just what the UI paints.
- **S2** — Two real Entra users verify manually: each sees only their engagements; on a
  shared engagement, one sets Yellow with a why and the other's agent reports that
  status and why accurately.
- **S3** — The deepagents harness passes S1 on Azure. The Copilot harness passes the
  same suite's core checks locally.
- **S4** — Honesty probe: a deliberately failing tool call is visible in the trace as a
  failure and is not reported as success in the reply.
- **S5** — An artifact uploaded before a session container restart is still listed and
  openable after it.
- **S6** — Demo data can be reset to a known seed state, and the S1 suite is re-runnable
  back-to-back with identical results.
- **S7** — After 24 idle hours, billing shows zero compute consumption for the period;
  the app cold-starts and passes a smoke sign-in afterwards.
- **S8** — For any S1 run, each agent turn's trace (R19) can be pulled and read: which
  tools ran, their outcomes, and the context bundle used.

## Non-goals (v1)

External or anonymous users · mobile layouts · SLAs or multi-region · permissions finer
than the three roles · the parked delivery-record depth (R7) · harness feature work
beyond parity for v1 capabilities.
