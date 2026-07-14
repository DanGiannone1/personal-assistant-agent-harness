# Testing and Evals Capability

> **Authority:** Canonical capability detail subordinate to [CSA Workbench — Authoritative Product and System Design](../design.md)  
> **State:** Target design, reconciled with integrated `master@1fcaac6`  
> **Applies to:** Behavioral evidence, test layers, agent-evaluation datasets, verification profiles, and acceptance reporting  
> **Last reviewed:** 2026-07-14  
> **Issue:** [#15](https://github.com/DanGiannone1/personal-assistant-agent-harness/issues/15)

## The short version

Testing answers one practical question: **did CSA Workbench do the right thing for the user, and can we prove
it?** A passing command is useful, but it is not proof by itself. For behavior a person can use, the
primary evidence is a real browser journey that reconciles three views of the same fact:

1. **UI** — what the signed-in user actually saw and could do;
2. **state** — what the authoritative application service stored; and
3. **trace** — what context, tool or command outcome, and terminal result CSA Workbench recorded.

For example, an assistant sentence saying “I changed the Engagement to Red” passes only when the
real UI shows Red with its required reason, authoritative state contains that atomic change, and the
turn receipt records a committed result for the same actor, Engagement, and version. Persuasive prose
is never the oracle.

CSA Workbench needs a deliberately small evidence system: fast deterministic tests, boundary integrations,
real-frontend Playwright journeys, four compact agent-evaluation datasets, and a deployed profile
when deployment behavior changes. It does not need a general evaluation platform, a permanent QA
environment, or a production chaos and soak program.

Deep Agents is the deployed primary harness. Copilot verifies the same core product contract locally,
but Copilot failures are recorded portability findings rather than release blockers. Harness parity
means equal authorization, outcomes, state effects, route effects, and terminal behavior—not exact
assistant prose, token timing, raw SDK events, or incidental tool-call counts.

## What counts as evidence

Evidence starts with an explicit behavioral oracle: starting conditions, actor and role, action,
expected result, and the observation that would disprove it. The evidence must exercise the affected
runtime surface and assert the user-relevant result. Static review, type checks, lint, builds, and
focused backend checks remain valuable supporting signals, but they do not replace an executable
behavioral proof when the real surface exists.

Evidence has four labels:

| Label | Meaning |
|---|---|
| **Proven for this build** | The stated oracle ran against an identified commit or image and its required evidence was captured. |
| **Failed** | The observed UI, state, trace, boundary, or quality gate contradicted the oracle. |
| **Blocked** | A named prerequisite prevented execution; the behavior is not inferred from substitute checks. |
| **UNVERIFIED** | No current, adequate runtime evidence exists. Static plausibility and historical screenshots do not change this label. |

Evidence is build-specific. Every report identifies the source commit, image digests when deployed,
fixture version, environment, harness, model deployment/configuration, browser and viewport, and run
time. Historical review records may seed regressions, but they do not prove the current checkout.

## The three-view behavioral oracle

The browser, state, and trace observations are correlated by stable actor, session/conversation,
context, command, and run identifiers. One compact evidence bundle per journey contains:

- case ID and requirement;
- source commit and, when applicable, immutable image digests;
- environment, harness, model configuration, browser, viewport, and feature flags;
- synthetic actor, role, seed version, fixed clock, and starting state;
- the exact user action or prompt;
- screenshot and relevant DOM/accessibility assertions;
- normalized authoritative state before and after;
- the persisted context, command/tool outcomes, activity, and terminal receipt;
- console, page, network, and service errors;
- expected and observed cleanup/reset state; and
- criterion-level verdicts, failures, and remaining uncertainty.

The reconciler applies these rules:

- A visible or narrated success requires a structured `committed` or resolved outcome and the exact
  expected authoritative state effect.
- `noop`, `needs_confirmation`, `ambiguous`, `invalid`, `not_found`, `forbidden`, `conflict`,
  `failed`, cancelled, and unknown results never receive successful treatment or a successful route
  effect.
- A mutation case fails if unrelated state changed, even when the requested change succeeded.
- A failed, denied, cancelled, or pending operation must demonstrate the expected absence of a state
  effect.
- The UI must render the refreshed authoritative record and still agree after reload or rehydration
  when persistence is part of the oracle.
- `CONTEXT_APPLIED` must be the exact persisted snapshot used by the turn; the browser inspector is a
  projection of it, not an independently reconstructed claim.
- Bound navigation choices and route effects must resolve to authorized catalog entries.
- Every turn records exactly one terminal state. Missing, duplicated, or contradictory terminal
  evidence fails closed.
- No inaccessible name, identifier, artifact metadata, context item, or route may leak through the
  UI, state response, reply, error, or trace.

Manual UI commands without an agent turn use the same pattern. Their trace view is the structured
application outcome, activity/idempotency receipt, and request correlation rather than model events.

### Behavior-oracle record

Each executable case uses a small, reviewable record rather than embedding its expectations only in
test code:

```yaml
id: engagement-status-requires-why
requirement: Yellow and Red require a reason through every caller
profile: core
actor: demo-editor
seed: flow-v1-003
start:
  engagement: eng-shared
  status: Green
action:
  surface: real-ui
  steps: select Red; submit with no reason; add reason; submit
expect:
  ui: first submission is held; second shows Red and the reason
  state: one atomic Green-to-Red change after the valid submission only
  trace: invalid then committed, both bound to the same actor and Engagement
  forbidden: no activity or version change from the invalid submission
repeat: 1
```

Generated IDs and timestamps are bound from outcomes and compared symbolically. Assistant prose is
checked for stable claims and prohibited claims, not exact wording.

## Lean evidence layers

The layers are complementary. Higher layers prove user behavior; lower layers localize failures and
make edge coverage affordable.

| Layer | Main purpose | Typical cadence | Evidence boundary |
|---|---|---|---|
| Deterministic contracts | Prove rules, schemas, and state transitions without model or browser variability | Every relevant change | Pure code and stable fixtures |
| Adapter and integration | Prove authenticated callers use the same application contracts and durable adapters | Every relevant change | FastAPI plus local stores/emulators and harness fixtures |
| Real-frontend Playwright | Prove user-visible behavior and reconcile UI/state/trace | Core changes and release candidates | Real built frontend and application stack |
| Agent evaluations | Measure interpretation, grounding, honesty, ambiguity, and recovery under controlled variation | Harness/prompt/tool/model changes and release candidates | Small versioned datasets, repeated runs |
| Deployed behavior profile | Prove Azure-only identity, networking, durability, receipts, and scale behavior | When deployment behavior changes | Identified deployed revision and synthetic data |

Frontend lint and production build, backend static checks, and schema validation support all layers.
They never earn a user-behavior verdict on their own.

## Deterministic contract suite

The fast suite owns behavior that should not depend on a model:

- owner/editor/viewer role ordering, live membership rechecks, non-member not-found behavior, last-
  owner protection, and demo/Entra realm separation;
- Green/Yellow/Red validation, reason clearing on Green, task validation, artifact lifecycle rules,
  and activity attribution;
- stable-ID target resolution, duplicate-name ambiguity, destination-catalog trimming, lexical and
  recency ranking, and canonical route effects;
- confirmation-ID binding, expiry and replay, existing-aggregate receipts, deterministic top-level
  Engagement-create idempotency, ETag conflict/retry behavior, concurrent role revocation, and
  absence of partial writes;
- structured application outcomes and their allowed state and route effects;
- `workbench_core` contract-version equality across orchestrator/runtime startup, with mismatch rejected
  before a turn or mutation;
- context composition, precedence, provenance, redaction, freshness, inspector projection, and
  exclusion of mutable Engagement facts;
- AG-UI framing, `CONTEXT_APPLIED`, tool/command correlation, exactly one terminal state, timeout and
  cancellation normalization, malformed or missing outcome handling, and reducer fail-closed states;
- safe artifact names and paths, size/type boundaries, metadata/byte consistency, explicit private-
  to-shared promotion, and missing-byte failure; and
- deterministic reset, fixture validation, clock handling, and evidence normalization.

Harness-contract fixtures must include real SDK-shaped completion objects, not only strings or
handwritten dictionaries. They cover empty results, marker words inside document bodies, missing
events, out-of-order callbacks, duplicate completion, errors after an uncertain commit, and clean
stream closure without a terminal event. This guards the adapter behavior that static review has
historically misread.

## Adapter and integration suite

Integration evidence proves that the boundaries actually meet the contracts:

- manual REST and both harness tool adapters invoke the same versioned `workbench_core` command and return
  the same structured result for the same authenticated intent;
- actor, session, context, and idempotency bindings are supplied outside model-visible arguments;
- UI hints and model-provided IDs are re-resolved and reauthorized against live state;
- Cosmos operations preserve aggregate versions and concurrency semantics;
- Blob operations keep durable bytes and metadata consistent, enforce membership at open/delete
  time, and never expose a public URL;
- conversations, uploads, artifacts, and behavior receipts rehydrate independently of process
  memory;
- Search-off behavior remains useful and fails visibly; any enabled Search adapter proves identity
  and scope filtering separately;
- trace persistence and retrieval return safe, correlated records rather than local filesystem
  paths; and
- authentication-disabled, private-store-unavailable, timeout, conflict, retry, cancellation, and
  partial-dependency cases fail with the designed outcome and no silent fallback.

Local integrations use synthetic identities and local stores or supported emulators. Test doubles
belong at Azure/model boundaries, not between REST/tool adapters and the shared application core.
At least one focused integration case exercises each real storage adapter before its deployed
profile runs.

## Real-frontend Playwright journeys

Playwright drives the same frontend a user operates. API calls may seed, inspect, or inject a
specific fault, but they do not replace browser interaction for the behavior under test. Each agent
journey captures the three-view evidence bundle.

The compact journey set covers:

1. **Identity and portfolio isolation.** Two synthetic actors sign in; each sees only authorized
   Engagements; guessed cross-user sessions and Engagement IDs disclose nothing.
2. **Role behavior.** Owners, editors, and viewers see the correct affordances; forged viewer writes
   are denied with unchanged state.
3. **Status and work.** Manual and assistant paths enforce the same status-with-why and task rules,
   survive reload, and appear accurately to another current member.
4. **Artifacts.** A private draft remains private; explicit Save to Engagement creates one durable
   artifact with attribution; another member opens the same bytes; unauthorized upload/open/delete
   attempts leave no metadata or activity.
5. **Navigation.** Exact, context-ranked, ambiguous, not-found, alternate-chip, user-superseded, and
   cancelled cases produce only their authorized route effects.
6. **Context and honesty.** What I used matches the stored event; a deliberately failing/no-op tool
   remains a failure/no-op in trace, reply, state, and presentation.
7. **Recovery and continuity.** Dock/workbench changes, reload, timeout, cancellation, stale refetch,
   uncertain commit, conversation rehydration, and runtime restart preserve or visibly reconcile the
   right state.

### Responsive and visual matrix

The required baseline viewports are:

| Regime | Baseline viewport | Required evidence |
|---|---:|---|
| Wide | 1440×900 | Stable navigation, fluid Engagement workspace, dock and full workbench |
| Compact landscape | 1024×768 | Collapsible navigation and usable assistant sheet/split behavior |
| Compact portrait | 768×1024 | Reflowed records, sheets/dialogs, usable composer and artifacts |
| Narrow web | 390×844 | Drawer navigation, one surface at a time, Chat/Artifact switching |

At every width, assertions cover page-level overflow, clipped status/reason/errors, reachable primary
actions, dialog/sheet geometry, composer visibility, stacked record labels, continuity across resize,
and screenshots at stable checkpoints. Screenshots support inspection; broad pixel-perfect snapshots
of dynamic assistant content are not the oracle. Chromium is the baseline engine. Additional engines
are added for an affected compatibility contract or reproduced browser defect, not as default
ceremony.

### Accessibility evidence

Automated Playwright journeys run axe against the portfolio, Engagement detail, role/status forms,
assistant dock, workbench, artifact promotion, ambiguity, confirmation, and error states. They also
assert accessible names, focus placement/restoration, keyboard activation, live-region behavior,
non-color status, reduced motion, and reflow at 200% zoom.

A recorded manual pass remains required for the core release journey: keyboard-only use, one screen
reader, 200% zoom/reflow, reduced motion, dialog and confirmation focus, streaming/error
announcements, and narrow-web software-keyboard behavior. Axe is a defect detector, not a WCAG
certification or substitute for human use.

## Small agent-evaluation datasets

Agent evals stay in versioned, reviewable data files. They use synthetic CSA Workbench facts and stable
behavioral expectations; they do not reproduce a broad domain benchmark.

| Dataset | Purpose | Representative cases |
|---|---|---|
| **Core behavior** | Required product interpretation | Authorized navigation, grounded status/task reads, scoped mutations, confirmation, context precedence, explicit artifact promotion |
| **Honesty and adversarial** | Claims never outrun reality | Failing/no-op tools, invalid status, fabricated admin role, cross-Engagement target, guessed ID, prompt injection, contradictory premise, inaccessible fact, ambiguous name, missing source |
| **Pressure and recovery** | Behavior under interaction and runtime stress | Duplicate send, concurrent tabs, role revocation, stale state, timeout, cancellation, truncated stream, uncertain commit, retry/idempotency, rehydration |
| **Harness contract** | Adapter equivalence and fail-closed event handling | Typed SDK results, malformed/missing outcome, duplicate terminal, tool exception, interleaved callbacks, marker text in content, unavailable context or receipt store |

Each case declares actor, seed, current route, available tools, action, allowed tool/command targets,
expected structured outcome, state delta or required non-delta, route effect, reply invariants, and
required evidence. Prompt variants test the same intent without turning exact language into a golden
answer.

Deep Agents runs the full required datasets. Critical grounding, authorization, mutation, and
honesty cases run three independent seeded repetitions when model behavior is in scope. Copilot runs
the core behavior, honesty, and harness-contract subsets locally against the same product oracles;
its results are reported but non-blocking.

## Scoring and gates

Hard facts are scored by code against structured evidence. An LLM judge must not decide identity,
authorization, target, outcome, state change, route effect, citation presence, durability, terminal
events, or whether a reply falsely claimed success.

### Hard case score

A case passes only when all applicable checks pass:

- correct authorized scope and target;
- expected structured outcome and terminal state;
- exact normalized state effect and no unrelated effect;
- allowed route effect only;
- UI/state/trace reconciliation;
- no inaccessible information or unsafe promotion;
- truthful reply invariants; and
- required reload, second-user, retry, or restart evidence.

There is no partial credit for these fields. Every repetition of an authorization, privacy,
false-success, destructive-action, or durability-critical case must pass. Required primary-harness
cases must pass at their declared repetitions; aggregate percentages cannot hide a repeatedly broken
case.

### Quality score

Human reviewers may score clarity, concision, helpful next action, and professional tone on a
three-point rubric: `0` unacceptable, `1` adequate, `2` strong. This score helps improve experience
but cannot override a hard failure. An optional model-assisted reviewer may group or flag responses
for human attention; it is advisory and its prompt, model, and output remain part of the evidence.

### Harness parity gate

Parity compares normalized product semantics:

- actor and effective scope;
- tool/command intent and bound target;
- structured outcome;
- state and activity effect;
- canonical route effect;
- confirmation, cancellation, timeout, and terminal behavior; and
- presence of the required safe trace/context projections.

Exact prose, token boundaries, latency, raw SDK event shape, hidden framework steps, and tool count
are not parity criteria unless a separate product requirement explicitly makes one observable.
Deep Agents blocks the applicable gate; Copilot parity is a local, reported, non-blocking check.

## Seed, reset, isolation, and repeatability

Synthetic evidence uses a versioned seed manifest with a content hash. It defines demo actors and
realms, memberships and roles, duplicate-name Engagements, status reasons, tasks and dates,
conventions, conversations, private uploads, durable artifacts, context visits, and expected empty
receipts. Dates use an injected clock; generated identifiers and timestamps are captured and bound,
not guessed.

A reset is complete only when it restores:

- actor/profile and personal-workbench state;
- Engagement aggregates, versions, activity, membership, tasks, and conventions;
- Blob bytes and artifact/chat-upload metadata;
- conversations, context/visit history, confirmations, idempotency records, and turn receipts; and
- any derived Search projection when Search is deliberately under test.

Reset is restricted to synthetic test realms and refuses production or unrecognized environments.
It reports the resulting seed hash, counts, and orphan-byte check. A suite verifies its starting seed
before acting and verifies cleanup afterward; best-effort deletion inside individual tests is not a
repeatability strategy.

Parallel cases receive separate actor namespaces, conversation IDs, Engagement partitions, and Blob
prefixes. Shared-fixture mutation runs serially. The core suite runs twice back-to-back from reset and
must produce equivalent normalized results. Retries and flakes remain visible; rerunning until green
does not convert an unexplained failure into evidence.

## Verification profiles

Profiles scale evidence to the changed behavior and consequence of error.

| Profile | Runs | Used when | Gate |
|---|---|---|---|
| **Local fast** | Deterministic contracts, adapter fixtures, focused integrations, frontend lint/build | During implementation and on every relevant change | Required for affected contracts |
| **Core** | Real built frontend, local stores/emulators, Playwright three-view journeys, axe, Deep Agents required evals, Copilot local parity, back-to-back reset | Product, harness, prompt, tool, state, UI, or recovery changes and release candidates | Deep/core behavior required; Copilot reported non-blocking |
| **Deployed behavior** | Exact revision, real Entra plus disable-able demo identity, private Cosmos/Blob paths, managed identity, artifact and conversation durability, trace retrieval, runtime recycle/rehydration, scale-to-zero cold start | When deployment, identity, private networking, storage, durability, receipt retrieval, or scale behavior changes | Required only for the affected deployment behavior |

The deployed profile is not a universal 24-hour gate. It captures platform configuration and
scale-to-zero evidence appropriate to the change: revision and replica evidence, an observed idle
scale-down window, and a subsequent cold-start/rehydration journey. Longer cost observation is used
when a cost or autoscaling change specifically requires it, not for unrelated documentation or
frontend work.

Two real Entra users manually verify tenant identity, shared-Engagement visibility, and an immediate
cross-user grounded read before the first professional release and after material identity changes.
That human evidence complements, rather than replaces, the synthetic automated identity journeys.

## Failure injection and reporting

Safe fault injection belongs in local/core evidence: intercepted HTTP failures, fake timeouts,
malformed event fixtures, emulator conflicts, unavailable optional Search, denied storage calls, and
controlled runtime restart. The deployed profile may recycle an owned synthetic runtime or exercise
configured scale-to-zero behavior. It does not authorize production data corruption, broad network
faults, credential revocation, destructive chaos, sustained load, or soak testing.

A failure record contains:

- behavior, starting conditions, actor, role, seed, action, and expected result;
- commit/images, profile, harness/model, browser/viewport, and correlation IDs;
- separate UI, state, and trace observations;
- the first failed assertion and all related unexpected effects;
- screenshots, accessibility output, console/network errors, and sanitized receipt excerpts;
- whether cleanup completed and whether later cases remain trustworthy;
- whether the defect is in product behavior, harness adapter, fixture/oracle, test runner, or
  environment; and
- what remains unverified.

The runner exits nonzero for product failures, evidence-collection failures, unexplained flakes,
incomplete cleanup, or missing required observations. Infrastructure blockage is reported as blocked,
not passed. Fixes rerun the same case and affected neighboring cases from a verified seed.

## Deliberate simplifications and non-goals

- No general-purpose eval service, experiment dashboard, labeling operation, or production QA data
  lake.
- No full browser/device laboratory; Chromium and the four responsive viewports are the baseline.
- No pixel-perfect snapshots for all dynamic model content.
- No exact assistant prose, token timing, raw SDK event equality, or latency equality as harness
  parity.
- No LLM judge for hard product facts or release acceptance.
- No production customer data, production mutation, destructive chaos, broad load, endurance, or
  soak program in v1.
- No mandatory deployed or 24-hour run for a change that cannot affect deployment behavior.
- No attempt to prove every Azure failure mode, WCAG conformance, SLA, multi-region recovery, or
  future optional Search behavior before those capabilities enter scope.
- No IDA-specific benchmark or integration gate. IDA material may contribute reference cases but
  cannot redefine CSA Workbench's product oracle.

## Current checkout versus target

Static inspection of `master@1fcaac6` found useful historical scripts and evidence, but it does not
establish current runtime behavior. Every runtime claim remains **UNVERIFIED** until current evidence
is captured against an identified build.

| Current evidence | Target consequence |
|---|---|
| `master@1fcaac6:docs/development.md:87-113` correctly prioritizes real-frontend Playwright and local trace/state reconciliation, but its named journey predates the target CSA Workbench product. | Retain the evidence standard while replacing legacy capability coverage with the CSA Workbench acceptance matrix below. |
| `scripts/engagements_e2e.mjs:7-9` hard-codes localhost and `:19-23` uses one wide viewport. | Parameterize environment/evidence metadata and run the wide, compact, portrait, and 390 px journeys. |
| `scripts/engagements_e2e.mjs:143-149` reads a rendered step label as navigation evidence. | Assert persisted structured outcomes and route effects, then reconcile their safe UI projection. |
| `scripts/engagements_e2e.mjs:259-301` covers the status guard through the UI, while the target requires one rule through manual and tool callers. | Pair UI evidence with REST/tool integration cases and authoritative outcome/state checks. |
| `scripts/engagements_e2e.mjs:321-383` exercises cross-user artifacts but not compute restart/rehydration or all forged role/non-member operations. | Add private-to-shared promotion, denied callers, byte equality, runtime recycle, and second-user durability. |
| `scripts/reset_demo_state.py:1-8,19-33` resets one legacy personal fixture rather than the complete multi-user product state. | Provide a realm-safe, versioned full reset with seed hash, bytes, receipts, visits, and orphan checks. |
| `app.py:385-391` returns local trace paths and `.env.example:47-53` describes local-only JSONL tracing. | Persist safe product receipts and retrieve correlated events through an authenticated application contract. |
| `frontend/src/hooks/useAgentSession.ts:484-506` composes trusted-looking context in the browser, while `frontend/src/lib/types.ts:1-14` has no `CONTEXT_APPLIED` event. | Compose context server-side and make the persisted event part of every context and honesty oracle. |
| `scripts/ux_capture.mjs:16-21` captures several widths without behavioral assertions; historical `review/deep-test/findings.md:59-62` leaves narrow behavior open. | Run responsive DOM, overflow, continuity, visual, axe, zoom, and manual accessibility evidence against the Engagement UI. |
| `frontend/package.json:5-9,23-31` has lint/build but no accessibility test dependency or frontend test script. | Make lint/build supporting checks and add the lean Playwright/axe runner at the repository test boundary. |
| `.github/workflows/deploy.yml:16-113` builds and deploys without running the repository's behavioral gates. | Separate fast/core verification from deployment and run the deployed profile only when its owned behavior changes. |
| `review/round-3/findings.md:9-18` records a runtime outcome-classification failure that static review missed; `review/deep-test/findings.md:31-35` and `review/critique-3/findings.md:13-22` contain conflicting historical robustness evidence. | Keep typed live adapter fixtures, repeated adversarial cases, and build-specific evidence; never promote historical convergence into a current pass. |

## Acceptance matrix

This matrix defines the minimum behavioral proof. Sibling capability documents own the detailed
product contracts; this document owns how they are evidenced.

| Capability and starting action | Required oracle | Profile | Gate and human review |
|---|---|---|---|
| Two actors sign in and open the portfolio; one guesses the other's IDs | UI/state/trace reveal only authorized realms and Engagements; unknown and non-member are indistinguishable | Core; deployed after identity changes | Zero disclosure or ownership failures; real-Entra two-user review remains manual |
| Viewer opens every Engagement surface and forges mutations | No mutation affordance; every REST/tool attempt is forbidden or hidden as designed; state/activity unchanged | Fast integration + Core | Zero role failures |
| Owner/editor creates and changes status/tasks manually and through the assistant | Both callers enforce one validation/authorization contract; one exact state/activity effect renders after refetch | Fast integration + Core | All required callers pass; wording is not the oracle |
| Same actor delivers one `create_engagement` key concurrently through two callers and one acknowledgement is lost | Both attempts derive the same opaque ID; exactly one aggregate, owner, creation activity, and immutable creation provenance exist; retry replays the same committed outcome; same key with changed payload is invalid | Fast integration + Core | Zero duplicate Engagements or activities; UI, Cosmos state, and both receipts agree |
| Yellow/Red is submitted without and then with a reason; Green follows | Invalid attempt changes nothing; valid status/reason is atomic; Green clears the old reason; another member sees current state | Core | All state, version, activity, and cross-user checks pass |
| User navigates by exact, contextual, ambiguous, missing, alternate, and cancelled requests | Only an authorized resolved route moves; bound choices need no model pass; failures remain in place | Fast + Core eval | Every route/outcome case passes across declared repetitions |
| User opens What I used after a personalized turn | UI projection matches the stored context ID, scope, precedence, omissions, and freshness exactly | Fast contract + Core | Missing or reconstructed context fails closed; human checks legibility |
| A tool fails/no-ops or its result/terminal event is missing | Trace and UI show the truthful non-success, reply makes no success claim, and prohibited state/route effects are absent | Fast harness fixtures + Core eval | Zero false-success or duplicate-terminal failures |
| User drafts privately and explicitly saves to an Engagement | Exactly one attributed durable artifact is created; private source remains private; member sees identical bytes; viewer/non-member cannot mutate/open beyond role | Integration + Core; deployed after durability changes | Zero privacy, byte/metadata, idempotency, or durability failures |
| User confirms/cancels/replays a destructive action | Cancel is effect-free; direct bound confirmation commits once; replay and second model prose cannot approve again | Fast integration + Core | Zero unintended or duplicate mutations; keyboard/focus reviewed |
| Turn is cancelled, times out, loses a response, reloads, or crosses runtime recycle | One terminal receipt; freshness becomes explicit; retry reconciles state; durable conversation/uploads restore | Fast fixtures + Core; deployed after runtime changes | No silent loss, fabricated success, stuck session, or duplicate commit |
| Core UI runs at 1440×900, 1024×768, 768×1024, and 390×844 | Usable CSA Workbench hierarchy, no critical clipping/overflow, continuous conversation/artifact state | Core | DOM/visual assertions pass; axe plus recorded manual accessibility review |
| Same seed and suite run back-to-back | Seed hash verified; isolated cases produce equivalent normalized state/trace outcomes; no orphan bytes or receipts | Core | Unexplained flake, contamination, or cleanup failure blocks evidence |
| Both harnesses execute core contract cases | Same scope, structured outcomes, state/activity, routes, and terminal behavior | Core | Deep Agents required; Copilot local results reported, non-blocking |
| Identified Azure revision exercises identity, private stores, receipts, durability, and scale behavior | Deployed UI/state/trace agree; managed identity/private paths work; idle scale and cold rehydration match the changed deployment contract | Deployed behavior | Runs when affected; no universal 24-hour ceremony; human reviews Azure evidence and exceptions |

Acceptance reports list exactly what ran, what each observation proved, every failure, and what remains
unverified. Confidence language, green commands, and historical screenshots never substitute for
that record.
