# Agent evaluation reference architecture

## What we evaluate (target program)

The proposed program measures six things:

1. **Capability** — can the assistant do the jobs users ask of it?
2. **Trustworthiness** — does what it *says* match what actually *happened*? It must never claim an
   action that didn't commit, omit or deny one that did, or state facts the tools never returned.
   This is the product's defining rule — a claim never outruns reality — measured.
3. **Safety** — does it refuse everything it must refuse, without leaking?
4. **Consistency** — does it behave the same way when asked the same thing again?
5. **Performance** — is it fast enough and cheap enough?
6. **Change impact** — did the latest change make the system better or worse, and by how much?
   Improvements are measured with the same rigor as regressions.

In the target program, every eval run scores all six and leaves a permanent scorecard, so any change
can be compared against the last known-good state, metric by metric — no durable scorecard history
exists today. The unit under evaluation is the **harness + model
pair**, not the model alone: every scorecard records harness, model deployment, and code revision,
and the suite can run identical tasks against both Deep Agents and Copilot head-to-head.

Terms: a **task** is one test (request + success criteria); a **trial** is one attempt at it; a
**grader** scores an attempt; a **transcript** is the complete recording of one attempt.

## The method

Agents break the assumptions ordinary software testing relies on:

| What is different about agents | What it forces |
|---|---|
| The same request produces different behavior run to run | Tasks are attempted multiple times; consistency is measured, never assumed |
| There are many valid ways to do a job correctly | Success is defined by the outcome, never one prescribed sequence of steps |
| The output is part action, part language | Facts are graded by code; language is graded by an AI judge; neither grades the other's territory |
| It can be confidently wrong | The reply is always checked against the recorded facts |
| It acts on real systems | Evaluation runs in a controlled, reset environment — never against real users' data |

That produces a four-part loop: define success before running (required end state, forbidden
actions, judge questions); run and record a complete transcript; grade it three ways (code checks
facts, an AI judge checks language, measurements are taken not judged); and score, keep, and compare
scorecards across runs in both directions — regressions must be caught, and claimed improvements must
show up.

## What one attempt is graded on

| Layer | Question | Graded by |
|---|---|---|
| Outcome | Did the data end correct, and did nothing else change? | Code checks against the real database |
| Boundaries | Did it avoid tools/actions it must never take here? | Code checks |
| Response | Was the reply accurate, useful, and safe to say? | AI judge |
| Operational | How long, how many tokens, how many tool calls, what cost? | Measurement |

Four rules keep the layers separate: grade what the assistant produced, not the exact path (the tool
sequence is recorded and reported but never pass/fail); the judge grades only language and can never
overturn a code check; code checks never grade wording; and partial credit is kept (a task reports the
fraction of checks passed, not just pass/fail) except safety tasks, which stay all-or-nothing.

## Writing good tasks

A task file records a prompt, the required end state (`expectedState`), forbidden tools
(`forbiddenActions`), tools a good solution is expected to use for reporting only
(`referenceActions`), and judge questions. Authoring rules: apply the two-expert test (two people who
know the product would independently reach the same verdict); give every task a reference solution
that shows it is solvable; write prompts the way people actually talk, not the way tools are named;
test both directions (where a behavior should happen and where it shouldn't); accept legitimate
alternatives explicitly and consistently across sibling tasks; and derive tasks from the job, not the
tool list — a task that fails because a capability is missing is kept and reported as product signal.

## Three suites, three jobs

- **Capability** — "what can it do well?" Supposed to start with a low pass rate; it targets what the
  assistant struggles with.
- **Regression** — "does it still handle everything it used to?" Sits near 100%; any drop means
  something broke. Capability tasks that become reliably passable **graduate** into regression.
- **Safety** — permission denials, leak prevention, injection immunity. Zero tolerance, runs every
  time, never graduates out.

In these terms, the nine atomic cases plus the three-turn workflow in
[`tests/evals/`](../../tests/evals/) are a small regression+safety suite, covering both the
Engagement and the personal-work pages. The separate Waza check evaluates only the
`engagement-meeting-prep` skill's routing and read-only tool constraints through Copilot in a
isolated test environment — the `tasks`, `calendar`, and `weekly-review` skills have no Waza
coverage today. A gold capability suite derived from real CSA use cases does not exist yet.

## The judge, precisely

One question per dimension (accuracy, leakage, tone are asked separately), each answered with a
one-sentence reason before the verdict. The judge may answer "Unknown" when the transcript doesn't
contain enough to decide. The judge model must differ from the model under test. Its verdicts are
compared against human spot-checks before it gates a release; it stays advisory until that agreement
is demonstrated, and humans keep spot-checking occasionally forever.

## What we measure

| Metric | Plain meaning | Blocks a release? |
|---|---|---|
| Check pass rate | Of all individual checks across all tasks, how many passed (partial credit) | Yes |
| Task pass rate | How many tasks fully passed | Yes — regression suite stays near 100% |
| Safety | Did every safety task pass | Yes — one failure fails the run |
| Judge pass rate | How many judge questions passed | Advisory until the judge is calibrated |
| Truthfulness | No reply contradicts the recorded facts | Treated like safety once calibrated |
| pass@k / pass^k | Chance at least one / all of k tries succeed | Reported |
| Speed, effort, cost | Time, tool calls, tokens/dollars vs. the reference | Reported; trended |

## Current implementation

- The loopback-only Deep Agents runner has nine atomic cases (seven Engagement, two personal-work)
  and one three-turn workflow, resets the fixture before each, and grades saved application state,
  structured events, exact targets/arguments, forbidden tools, and complete model-visible
  product-tool outputs.
- Four native product skills (`engagement-meeting-prep`, `tasks`, `calendar`, `weekly-review`) are
  versioned and available for progressive disclosure; only `engagement-meeting-prep` is exercised by
  the current versioned workflow.
- Waza has an isolated skill-routing check for the `engagement-meeting-prep` skill only; its
  pass/fail gate covers Copilot laboratory behavior rather than Deep Agents product behavior, and
  it does not cover the other three skills.
- There is no durable scorecard history, gold capability task set derived from real use cases,
  repeated-trial orchestration, or calibrated automated judge yet. Judging today, when done, is
  manual review rather than an automated grader.
- Product-runtime token and cost capture are not implemented; only the Waza check reports those
  values.

## Roadmap

| Phase | Delivers | Depends on |
|---|---|---|
| 1. Scorecard history | Accept one reviewed baseline, then keep permanent comparable scorecards | A clean live product workflow result and human grounding review |
| 2. Judge formalized | Judge questions for the existing tasks checked in; verdicts stored beside each run | Nothing |
| 3. Runner upgrades | Partial credit, response-start timing, product token/cost capture, repeat-trial orchestration | Token capture touches the harness and is reviewed separately |
| 4. Gold task suite | Use-case-derived tasks with expected outcomes, judge questions, and reference solutions | A use-case set |
| 5. Consistency & comparison | Repeat trials, pass@k/pass^k, side-by-side harness runs | Phases 3–4 |
| 6. Automated judge + Azure | Calibrated judge, Azure AI Foundry evaluators, Blob upload, Application Insights, a dev Azure eval copy | Phases 1–5 |

## Related documents

- [Design](../product/overview.md)
- [Testing Charter](../governance/testing-charter.md)
- [Demo guide](../guides/demo.md)
- [Current assistant architecture](../architecture/capabilities/assistant.md)
