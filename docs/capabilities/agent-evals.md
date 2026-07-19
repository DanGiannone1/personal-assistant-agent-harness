# Agent Evaluation Capability

> **Authority:** Forward-looking evaluation strategy subordinate to the
> [authoritative design](../design.md) and the
> [Testing Charter](../governance/testing-charter.md). The current release
> evidence record is owned by [Testing and evals](testing-evals.md); this
> document does not restate or replace it.
>
> **Applies to:** Gold-standard eval tasks, eval execution, grading, metrics,
> scorecard history, harness comparison, and eval environments
>
> **Status:** Approved strategy; implementation phased below. Approved in
> conversation with the repository owner on 2026-07-19 and checked the same
> day against current field practice (sources at the end).

## What we evaluate

Six things, continuously:

1. **Capability** — can the assistant do the jobs users ask of it?
2. **Trustworthiness** — does what it *says* match what actually *happened*?
   It must never claim an action that didn't commit, omit or deny one that
   did, or state facts the tools never returned (hallucination). This is the
   product's defining rule — a claim never outruns reality — measured.
3. **Safety** — does it refuse everything it must refuse, without leaking?
4. **Consistency** — does it behave the same way when asked the same thing again?
5. **Performance** — is it fast enough and cheap enough?
6. **Change impact** — did the latest change make the system better or worse,
   and by how much? Improvements are measured with the same rigor as
   regressions: a change that claims to help must show it on the scorecard.

Every eval run scores all six and leaves a permanent scorecard, so any
change — a new prompt, a new model, new tools — can be compared against the
last known-good state, metric by metric.

The unit under evaluation is the **harness + model pair**, not the model
alone. Public leaderboards moved to this in the last year for a reason:
swapping the harness around an unchanged model measurably shifts results.
Every scorecard therefore records harness, model deployment, and code
revision, and the suite can run identical tasks against both of our harnesses
(Deep Agents and Copilot) head-to-head.

Terms used throughout: a **task** is one test (request + success criteria); a
**trial** is one attempt at it; a **grader** scores an attempt; a
**transcript** is the complete recording of one attempt — tools called, data
before and after, the reply, and timings.

## The method, and why it is shaped this way

Agents break the assumptions ordinary software testing relies on. Each break
forces one piece of the evaluation method — the method is not a style choice,
it is what remains once these properties are taken seriously:

| What is different about agents | What it forces |
|---|---|
| The same request produces different behavior run to run | Tasks are attempted multiple times; consistency is measured, never assumed |
| There are many valid ways to do a job correctly | Success is defined by the outcome — the end state of the data and the boundaries respected — never by one prescribed sequence of steps |
| The output is part action, part language | Facts are graded by code; language is graded by an AI judge; neither grades the other's territory |
| It can be confidently wrong | The reply is always checked against the recorded facts, so a fluent claim of success cannot pass on confidence alone |
| It acts on real systems | Evaluation runs in a controlled environment with known data, reset before every attempt — never against real users' data |

Those constraints produce a four-part loop:

1. **Define success before running.** Every task states, in advance, what
   must be true afterward: the required end state of the data, the actions
   that are forbidden, and the questions the reply must satisfy. If success
   is defined after the fact, grading is opinion.
2. **Run and record.** The agent attempts the task in the controlled
   environment while everything is captured: every tool call and its inputs,
   every data change, the full reply, all timings. This recording — the
   transcript — is the single source everything else grades. Grading a
   recording rather than a live run means grading can be repeated, improved,
   and re-applied to old runs at any time.
3. **Grade the recording, three ways.**
   - **Code checks decide facts.** Is the end state correct? Did anything
     change that shouldn't have? Did a forbidden action run? Objective,
     repeatable, no AI involved.
   - **An AI judge decides language.** Is the reply accurate, grounded in
     what the tools returned, and safe to say? The database says what
     actually happened; the judge checks whether the words match it — neither
     alone can catch a confident lie. Some failures exist only in wording — a refusal phrased in a way that
     confirms the existence of something the requester was never allowed to
     know about is a leak that no data check can see. This class of failure
     is why a judge is part of the method at all.
   - **Measurements are taken, not judged:** elapsed time, time until the
     reply starts, tokens, cost, and tool-call count.
4. **Score, keep, compare.** Each run produces a small permanent scorecard.
   Nothing is declared better or worse by impression — only by comparing
   scorecards across runs, in both directions: regressions must be caught,
   and claimed improvements must show up.

Everything else in this document is the detail of this loop: what has to
exist before it can run, the operational steps, the grading rules and their
order of authority, how tasks are written so grading is fair, and where the
recordings and scorecards live.

## Prerequisites: what you need before you can evaluate anything

| # | Prerequisite | Why it's required | Status |
|---|---|---|---|
| 1 | A set of realistic tasks | You can only measure what you test | In progress (use-case work, separate owner); 7 exist today |
| 2 | A written "right answer" per task — expected data outcome, forbidden actions, judge questions | Without it, grading is opinion | To write per task; this is the real labor |
| 3 | Fixed, known starting data | "Expected outcome" is meaningless if every run starts differently | ✅ Exists (dan/ava/sam test data with reset) |
| 4 | A runner that plays the user and records transcripts | The recording is what everything else grades | ✅ Exists; needs upgrades (see roadmap) |
| 5 | Graders: code checks + an AI judge | Code for facts, judge for language | Code checks exist; judge is manual today |
| 6 | Somewhere scores accumulate | One run tells you nothing; the comparison is the product | ❌ Missing — first thing to build |

## How a run works, step by step

1. **Pick the suite** — safety and regression tasks before any change ships;
   the full set including capability tasks nightly or on demand.
2. **For each task:** reset the test data, snapshot, send the prompt, record
   the transcript, snapshot again.
3. **Code grading** happens immediately: data outcomes, forbidden actions,
   nothing-else-changed, plus measurements (time, tokens, tool count).
4. **Judge grading** happens on the recorded transcripts: each task's judge
   questions are answered with a verdict and a one-sentence reason. Today a
   Claude session does this; the target is an automated judge model asking
   the identical questions.
5. **The scorecard is written** — one small file per run: pass rates, safety
   result, speed, cost, plus which harness, model, code version, and
   environment produced it.
6. **Compare against the baseline** — the previous accepted scorecard. Better,
   worse, or noise, metric by metric.
7. **Read some transcripts.** Scores are never taken at face value. When a
   task fails, the transcript shows whether the assistant truly failed or a
   grader rejected a valid answer. Failures should look fair when a person
   reads them; if they don't, fix the task or grader, not the score.

## What one attempt is graded on

Four layers, graded by different tools:

| Layer | Question | Graded by |
|---|---|---|
| Outcome | Did the data end correct — and did nothing else change? | Code checks against the real database |
| Boundaries | Did it avoid tools and actions it must never take here? | Code checks |
| Response | Was the reply accurate, useful, and safe to say? | AI judge |
| Operational | How long, how many tokens, how many tool calls, what cost? | Measurement |

Four rules keep the layers honest:

1. **Grade what the assistant produced, not the path it took.** The data
   outcome and the forbidden-action list are hard pass/fail. The exact tool
   sequence is recorded and reported but never pass/fail: agents regularly
   find valid approaches the task author didn't anticipate, and rigid
   step-checking fails correct behavior.
2. **The judge grades only language.** It can never overturn a code check —
   the database outranks any opinion about wording.
3. **Code checks never grade wording.** No keyword matching on assistant text,
   ever. Language belongs to the judge.
4. **Partial credit is kept.** A task reports the fraction of its checks
   passed, not just pass/fail — an assistant that got three of four steps
   right is better than one that failed immediately, and scores must show it.
   Exception: safety tasks are all-or-nothing, always.

The repository's standard of proof
([Testing and evals](testing-evals.md#what-counts-as-proof)) applies
unchanged: the real database outranks structured events, which outrank what
anything rendered or said.

## Writing good tasks

The task file format is plain enough that non-engineers can write and review
tasks — that is a design goal, not an accident. The people closest to users
are the best task authors.

What one task looks like in the file:

```jsonc
{
  "id": "GS-example",
  "actor": "dan",
  "prompt": "Set Website Launch to red — the content freeze slipped again.",

  "expectedState": { "id": "eng-website-launch", "status": "red",
                     "onlyThisEngagementChanged": true },   // hard pass/fail
  "forbiddenActions": ["share_engagement", "create_engagement"], // hard pass/fail
  "referenceActions": ["list_engagements", "set_engagement_status"], // reported only

  "judge": ["Does the reply accurately describe what happened, without claiming anything the tools did not do?"],

  "referenceSolution": "evidence-ref/GS-example-reference.json",
  "mutates": true,
  "suite": "capability"
}
```

Authoring rules, learned the hard way by the field:

- **The two-expert test.** A task is well specified when two people who know
  the product would independently reach the same pass/fail verdict — and could
  pass the task themselves. Vague tasks turn into noisy metrics.
- **Every task needs a reference solution** — one known-good recording that
  passes every grader. It proves the task is solvable and the graders work. A
  task nobody can pass is a broken task: near-0% pass rates across many
  attempts almost always mean the task or grader is wrong, not the assistant.
- **Write prompts the way people actually talk.** "Use the navigation tool to
  open my portfolio" tests plumbing, not behavior.
- **Test both directions.** For every behavior, include tasks where it should
  happen and tasks where it shouldn't (update vs. refuse; act vs. ask first).
  One-sided tests train one-sided assistants.
- **Accept legitimate alternatives explicitly.** If refusing via the tool and
  asking a clarifying question are both correct, the task says so — and still
  requires the same unchanged data.
- **Tasks come from the job, not from the tool list.** They derive from CSA
  use cases and, over time, from real observed failures. A task that fails
  because a capability is missing is kept and reported as product signal —
  never deleted to make the suite green.

## Three suites, three jobs

- **Capability** — "what can it do well?" *Supposed to start with a low pass
  rate*: it targets what the assistant struggles with and gives the team a
  hill to climb. Also how bets are made visible: write tasks for planned
  capabilities before the assistant can pass them; when a new model or prompt
  lands, the suite instantly shows which bets paid off.
- **Regression** — "does it still handle everything it used to?" Sits near
  100%; any drop means something broke. Capability tasks that become reliably
  passable **graduate** into regression.
- **Safety** — permission denials, leak prevention, injection immunity. Zero
  tolerance, runs every time, never graduates out.

In these terms, today's seven-case MVP set is a small regression+safety
suite; the gold set starts life as capability. When a capability suite passes
everything, it has stopped teaching you anything — extend it with harder
tasks.

## The judge, precisely

- One question per dimension (accuracy, leakage, tone are asked separately),
  each answered with a one-sentence reason **before** the verdict.
- The judge may answer **"Unknown"** when the transcript doesn't contain
  enough to decide — guessing is forbidden.
- Judge questions live in the task file, in plain language. The *executor*
  changes over time — a Claude session today, an automated Azure judge model
  later — but the questions do not.
- The judge model must be different from the model under test, so a regressed
  model never grades itself.
- **The judge earns trust before it gates releases.** Its verdicts are
  compared against human spot-checks on real transcripts; it stays advisory
  until that agreement is demonstrated, and humans keep spot-checking
  occasionally forever.

## What we measure

| Metric | Plain meaning | Blocks a release? |
|---|---|---|
| Check pass rate | Of all individual checks across all tasks, how many passed (partial credit) | Yes — must not drop vs. baseline |
| Task pass rate | How many tasks fully passed | Yes — regression suite stays near 100% |
| Safety | Did every safety task pass | Yes — one failure fails the run |
| Judge pass rate | How many judge questions passed | Advisory until the judge is calibrated |
| Truthfulness | No reply contradicts the recorded facts — no claimed-but-didn't, did-but-denied, or invented detail | Treated like safety once the judge is calibrated |
| pass@k | If we try a task k times, chance at least one succeeds — "can it do this at all?" | Reported |
| pass^k | Chance all k tries succeed — "can users rely on it every time?" This is the customer-experience number | Reported |
| Speed | Seconds per answer — typical and worst-case; plus time until the reply starts | Reported; alert on big jumps |
| Effort | Tool calls per task vs. the reference — detects flailing | Reported |
| Cost | Tokens per answer, dollars per run — always shown next to accuracy | Reported; trended |

Every scorecard records which harness, model, code version, test-data version,
and environment produced it — so comparisons are always like-for-like, and
"which harness serves this product better?" is a question the suite can answer
directly.

## Where everything lives

| Data | Where | Why |
|---|---|---|
| Task definitions, judge questions, reference solutions | `tests/evals/` in Git | Versioned and reviewed like code |
| Full transcripts (one bundle per run, ~everything recorded) | Local `evidence/` folder, uploaded to an `eval-runs` container in Blob Storage | Kept exact and complete; the only thing graders and judges ever read |
| Scorecards (~1 KB each) | `evidence/evals/history/` — committed to Git | The permanent, comparable time series |
| Operational telemetry (timings, statuses, token counts per step) | Application Insights | Dashboards and trends |

Two rules:

- Application Insights truncates large values (8,192-character limit per
  property) and samples data — fine for dashboards, disqualifying for
  evidence. **Graders and judges read only the transcript bundles.**
- Telemetry and bundles share the same run and task IDs, so a slow turn on a
  dashboard can be traced to its exact transcript.

## Environments

| Environment | Purpose | Status |
|---|---|---|
| Laptop (fake users, local database emulator) | Where most eval work happens — full suite, including data changes | ✅ Works today |
| Dev Azure eval copy (same app deployed with fake users and its own dev database) | Prove the deployed setup behaves like the laptop | Planned — needs a deliberate, reviewed loosening of guards that currently (correctly) block remote eval runs |
| Production-like with real sign-in | A thin read-only smoke check with a test user | Existing practice; never the eval suite |

Each attempt starts from freshly reset test data; nothing from one attempt may
be visible to the next. Leftover state corrupts results in both directions —
it causes spurious failures *and* lets later attempts crib from earlier ones.
Evals never run against real users' data.

## When evals run

- **Before any behavior-affecting change ships** (prompt, model, tools,
  harness): regression + safety, compared to baseline.
- **Safety: every run**, zero tolerance.
- **Capability and repeat-trials: nightly or on demand** — slow and costs
  tokens.
- **Harness comparison: on demand**, when that decision is live.
- **Dev Azure suite: before deploys**, once the environment exists.

Evals are one leg of understanding the assistant — production monitoring,
user feedback, and human transcript review are the others. An eval suite that
drifts from real usage creates false confidence; once durable production
records exist, real failures become the primary source of new tasks.

## Where we are today, honestly

- ✅ Runner works; 7 tasks; code checks against the real database work
- ✅ Full transcripts already recorded on every run
- ❌ No scorecard survives a run — nothing is comparable to anything yet
- ❌ Forbidden or excessive tool calls are invisible to grading
- ❌ Tokens and cost are not captured anywhere
- ❌ No task has a reference solution
- ❌ The runner is single-turn; the app's own suggested multi-turn flows are
  untestable
- ⚠️ Two of the seven current tasks pass because the assistant safely
  declined — without ever proving the rejection behavior they were written to
  test
- ⚠️ Judging is manual (a Claude session), not yet automated or calibrated

## Roadmap

| Phase | Delivers | Depends on |
|---|---|---|
| 1. Scorecard history | Every run leaves a permanent, comparable scorecard; backfill from existing recordings | Nothing |
| 2. Judge formalized | Judge questions for the existing tasks checked in; verdicts stored beside each run | Nothing |
| 3. Runner upgrades | Forbidden-action checks, partial credit, per-attempt data reset, response-start timing, token/cost capture | Token capture touches the harness and is reviewed separately |
| 4. Gold task suite | Use-case-derived tasks with expected outcomes, judge questions, and reference solutions, balanced in both directions | Use-case set (separate owner, in progress) |
| 5. Consistency & comparison | Repeat trials, pass@k / pass^k, side-by-side harness runs | Phases 3–4 |
| 6. Automated judge + Azure | Judge calibrated against human spot-checks; Azure AI Foundry evaluators over the stored bundles; Blob upload; Application Insights; dev Azure eval copy | Phases 1–5; infra rides the normal release path |
| 7. Multi-turn tasks | Runner drives conversations; a small model simulates the user | Phase 3 |

## Method sources

Current-practice sources this strategy was checked against (all fetched and
reviewed 2026-07-19):

- Anthropic, *Demystifying evals for AI agents* (Jan 2026) — grader taxonomy,
  capability/regression split, task-authoring rules, "grade the product, not
  the path," partial credit, judge calibration, transcript reading,
  pass@k / pass^k.
- Princeton SAgE, *HAL: Holistic Agent Leaderboard* (ICLR 2026) — cost beside
  accuracy, harness-swap effects, reliability as the current frontier.
- Terminal-Bench 2.1 — harness+model pairs as the leaderboard unit.
- τ-bench / τ²-bench — end-state database grading for conversational agents,
  simulated users, pass^k.
- Azure AI Foundry agent evaluators — judge input format and evaluator
  catalog used in phase 6.

## Related authority

- [Authoritative design](../design.md)
- [Testing Charter](../governance/testing-charter.md)
- [Testing and evals](testing-evals.md)
- [Agent harness](agent-harness.md)
- [MVP success criteria](../requirements.md)
