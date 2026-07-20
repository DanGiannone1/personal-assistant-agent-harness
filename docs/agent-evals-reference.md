# Evaluating AI Agents — A Technical Walkthrough

A one-hour session for engineers who build or operate tool-using agents. It
covers the concepts and the reference architecture, not any specific product
or vendor SDK. It assumes you know what an agent harness is; it does not
assume you have run evaluations before.

**Agenda**

| # | Section | ~Minutes |
|---|---|---|
| 1 | Why agents break normal testing | 5 |
| 2 | The evaluation loop | 5 |
| 3 | What to measure | 12 |
| 4 | Grading: code and judges | 10 |
| 5 | Building the test suite | 8 |
| 6 | Reference architecture | 7 |
| 7 | Running it day to day | 5 |
| — | Going deeper, sources | Q&A |

---

## 1. Why agents break normal testing

Conventional testing assumes the same input produces the same output, and
that the output can be checked mechanically. Agents violate every part of
that assumption. Five properties matter, and each one forces a piece of the
evaluation method:

| What's different about agents | What it forces |
|---|---|
| The same request produces different behavior each run | Run important tests several times; measure consistency, never assume it |
| There are many valid ways to do a job correctly | Define success by the outcome — the end state of the data, the boundaries respected — never by one required sequence of steps |
| The output is part action, part language | Facts are graded by code; language is graded by an LLM judge; neither grades the other's territory |
| The agent can be confidently wrong | Every reply is checked against what actually happened, so a fluent claim of success cannot pass on confidence alone |
| It acts on real systems | Evaluation runs in a controlled environment with known, resettable data — never against production |

The rest of this session is what remains once these five facts are taken
seriously. None of the method is a style preference.

## 2. The evaluation loop

Four terms, used throughout: a **task** is one test — a request plus success
criteria. A **trial** is one attempt at a task. A **grader** is whatever
scores a trial. A **transcript** is the complete recording of a trial: every
tool call with its arguments and results, the state of the data before and
after, the reply, and all timings.

The loop has four steps:

1. **Define success before running.** Every task states in advance what must
   be true afterward: the expected end state of the data, the actions the
   agent must never take, and the questions a judge will answer about the
   reply. Success defined after looking at the output is opinion.
2. **Run and record.** The agent attempts the task in a controlled
   environment while everything is captured. The transcript is the single
   source every grader reads. Because grading works from recordings, graders
   can be improved later and re-applied to historical runs without
   re-executing anything.
3. **Grade the recording** — three ways, covered in section 4: code checks
   for facts, an LLM judge for language, and measurements that are taken
   rather than judged.
4. **Score, keep, compare.** Each run produces a small permanent scorecard.
   Nothing is declared better or worse by impression — only by comparing
   scorecards, in both directions: regressions must be caught, and claimed
   improvements must actually show up.

One rule makes the comparisons meaningful: **the unit under test is the
whole configuration, not the model.** Swapping the harness around an
unchanged model measurably shifts results — public leaderboards now score
harness-and-model pairs for exactly this reason. Every scorecard therefore
records a configuration fingerprint: model and version, sampling parameters,
system prompt, tool schemas, harness revision, fixture version, and the
judge model and rubric version. Capture it from the running system, not from
the repository — models change on the provider's side without a commit. A
score difference is attributable only when you know exactly which element
changed; a difference with an unknown cause is noise, not signal.

## 3. What to measure

This is the complete map. Not every row applies to every agent — planning
rows only apply if the harness plans explicitly, skill rows only if it uses
skills. Where a surface doesn't exist, mark the row not-applicable rather
than pretending coverage.

**A. Understanding**

1. **Intent resolution** — did it correctly identify what the user actually
   wants, including underspecified asks. Judged.

**B. Planning** *(only for harnesses that plan explicitly)*

2. **Plan quality** — was the proposed route complete, realistic, efficient,
   before execution. Judged.
3. **Plan adherence** — did it stick to the plan and constraints once tool
   outputs arrived, or drift out of scope. Judged.

**C. Tool use, per step**

4. **Tool selection** — right tool called. Deterministic: compare against the
   expected set.
5. **Argument correctness** — right inputs into that tool. Deterministic
   where arguments have one right answer; judged where they don't.
6. **Tool output utilization** — did it actually use what the tool returned,
   or ignore it. Judged.
7. **Tool call success** — did calls execute without errors, and did it
   recover from failures. Deterministic.

**D. Trajectory — the path as a whole**

8. **Efficiency and wandering** — was the route sane. This one is judged, and
   deliberately so: deterministic proxies (redundant-call percentages, step
   thresholds) break down as soon as trajectories branch. Give the judge the
   goal, the full tool sequence, and the tool catalog, and ask whether the
   route was efficient. That catches loops, retry spirals, and irrelevant
   detours. The split that makes this workable: *sequence membership is
   code* ("were these the right tools"), *route sanity is judge* ("was this
   a reasonable way through them"), and you hard-code ordering only when
   order is semantic — verify identity before issuing the refund.
9. **Reasoning relevancy** — intermediate decisions tie back to the request.
   Judged, where the harness exposes reasoning.
10. **Reasoning coherence** — the chain of thinking follows step to step.
    Judged, same caveat.

**E. Outcome**

11. **Task completion** — was the goal actually achieved. Deterministic
    end-state check wherever ground truth exists — read the data and compare;
    this is the strongest oracle in the whole system because it cannot be
    talked into anything. Judged only for genuinely open-ended tasks.
12. **Task adherence** — did the behavior respect system instructions and
    policy, independent of whether the user is satisfied. The canonical
    example: approving a refund the policy forbids satisfies the user and
    fails adherence.

**F. The final answer**

13. **Groundedness** — the reply claims only what tool results support.
14. **Relevance** — it actually addresses the question.
15. **Completeness and transparency** — it includes what matters: checked
    alternatives, surfaced failures. An agent that fails silently and reports
    success is a worse system than one that fails loudly.

**G. Safety** — refusal correctness, refusal leakage ("you don't have access
to X" confirms X exists), resistance to instructions embedded in content the
agent reads, and content safety. Binary, zero tolerance, runs every time.

**H. Reliability** — run the same task k times. **pass@k** is the chance at
least one trial succeeds: can it do this at all. **pass^k** is the chance
every trial succeeds: can users depend on it. They diverge fast — a task
with a 75% per-trial rate has a pass^3 near 42% — and pass^k is the number
that matches what users actually experience.

**I. Tracked, not graded** — tokens, cost, latency, time to first token,
tool-call counts. Always report cost next to accuracy: accuracy gains are
frequently purchased with tokens, and that trade should be a visible
decision.

**J. Skills** *(only for harnesses that load skills)*

16. **Skill selection** — did the right skill load. Deterministic, same
    shape as tool selection.
17. **Skill triggering** — does it trigger when it should and stay quiet when
    it shouldn't. Build should-trigger and should-not-trigger queries; the
    negatives must be near-misses from adjacent domains, not strawmen. Run
    each several times for a trigger rate.
18. **Skill value** — pair every with-skill run against a baseline run
    without it, and report the delta in pass rate, time, and tokens. The
    delta is the skill's entire justification: if with-skill doesn't beat
    without-skill, the skill is deleting itself.

**One more subject: the tools themselves.** Eval transcripts double as tool
evaluations. Repeated redundant calls point at pagination or verbosity
defects; repeated invalid-argument errors point at unclear descriptions or
parameter names; agents ignoring a tool's output point at responses that
bury the signal. Two tool-design rules fall straight out of eval data: error
and empty responses should tell the agent what to try next rather than
returning an opaque code, and token-heavy tools should offer a concise and a
detailed response mode. Some of the largest observed eval gains have come
from rewriting tool descriptions, not changing the agent.

## 4. Grading: code and judges

Two graders, with a strict division of labor.

**Code grades facts.** End-state comparison against the data store,
forbidden-action checks, error handling, sequence membership. Deterministic,
cheap, reproducible, immune to persuasion.

**An LLM judge grades language and routes.** Groundedness, leakage, refusal
quality, route sanity — properties that exist only in text or in the shape
of the whole path. Judge design rules:

- The judge runs in a **separate context** from the agent under test —
  a different deployment at minimum. The same model family is acceptable;
  what is never acceptable is the agent's own conversation grading itself.
- One rubric per dimension. Accuracy, leakage, and tone are separate
  questions, not one blended score.
- The judge writes its reasoning before its verdict, and "unknown" is always
  an allowed answer. A judge forced to decide will guess.
- Calibrate against human judgments on a sample of real transcripts before
  judge results block anything, and keep spot-checking after.
- The judge model and rubric version are part of the configuration
  fingerprint: changing either shifts scores with zero agent change, and
  that must never read as an agent regression.

**Why judged metrics advise and code gates.** This is a measured finding,
not a preference. Run two capable judge models over identical transcripts
and they will disagree — including flipping pass to fail on the same
recording. Worse, judges systematically penalize correct refusals: given a
transcript where the agent rightly declined a policy-violating request, a
judge grading "did the agent do what the user asked" scores the refusal as
failure. A judged metric that gated releases would push the agent toward
violating its own guardrails. So: deterministic outcome checks gate; judged
metrics inform; and grader disagreement is reviewed, never averaged, because
it is diagnostic in both directions — code-fail with judge-pass usually
means the task spec was too narrow; code-pass with judge-fail usually means
the agent did the right thing and communicated it badly.

Two final rules: score partial credit (an agent that got three of four steps
right is better than one that failed immediately, and the scores should show
it), except for safety, which is binary and where one failure fails the run.

## 5. Building the test suite

**Writing good tasks:**

- A task is well specified when two people who know the domain would
  independently reach the same pass/fail verdict on the same transcript —
  and could pass the task themselves. Ambiguous tasks become noisy metrics.
- Every task ships with a reference solution: one recording that provably
  passes all of its graders. It proves the task is solvable and the graders
  are wired correctly. With capable models, a near-0% pass rate over many
  trials almost always means a broken task, not a broken agent.
- Phrase requests the way users actually talk. A request that names the tool
  to use tests wiring, not behavior.
- Cover both directions of every behavior: act and refuse, answer and
  clarify. One-sided suites optimize one-sided agents.
- Where multiple behaviors are acceptable — refusing outright versus asking
  a clarifying question — say so explicitly, and consistently across similar
  tasks, or a model's style change shows up as a cluster of false failures.
- Write tasks from the job users need done, including things the agent
  cannot do yet. A task that fails for a missing capability is product
  information; keep it and report it.

**Three suites, three jobs:**

- **Capability** — targets current failures; a low pass rate is its purpose.
  Write tasks for planned features before building them, and a new model or
  prompt immediately shows which bets paid off.
- **Regression** — everything known to work; holds near 100%; any decline is
  a defect. Capability tasks graduate here once reliably passed. A suite
  passing everything has saturated and teaches nothing — add harder tasks.
- **Safety** — runs in full every time, never graduates, zero tolerance.

**Practical sizing:** start with 20–50 tasks drawn from real failures and
the manual checks you already perform before releases. Early on, changes
have large effects and small suites detect them; grow the suite as the agent
matures and the effects you need to detect get smaller. And keep a held-out
set that is never used while tuning prompts or tool descriptions — a suite
you optimized against can no longer measure you.

## 6. Reference architecture

```
                 ┌──────────────────────────────┐
   runner ──────►│  agent under test            │
   (no AI;       │  (harness + model + tools)   │
   plays the     └──────────────┬───────────────┘
   user, resets                 │ acts on
   fixtures)     ┌──────────────▼───────────────┐
                 │  environment: seeded, known  │
                 │  data — reset every trial    │
                 └──────────────┬───────────────┘
                                │ everything recorded
                 ┌──────────────▼───────────────┐
                 │  transcript store            │  immutable, one bundle per
                 │  (object storage)            │  run — the ONLY grader input
                 └──────┬───────────────┬───────┘
                        │               │
              ┌─────────▼─────┐  ┌──────▼────────┐
              │ code graders  │  │ LLM judge(s)  │  separate deployment,
              └─────────┬─────┘  └──────┬────────┘  own rubrics
                        └───────┬───────┘
                 ┌──────────────▼───────────────┐
                 │  scorecards (version control)│  small, permanent,
                 └──────────────┬───────────────┘  the comparison baseline
                                │ joined by run ID
                 ┌──────────────▼───────────────┐
                 │  telemetry / APM dashboards  │  trends and alerts only
                 └──────────────────────────────┘
```

The design rules embedded in that picture:

- **The runner contains no AI.** It plays the user, resets fixtures between
  trials, records, and applies the code graders. Trial isolation is not
  optional: leftover state causes correlated false failures, and it leaks —
  agents have been observed mining artifacts from previous trials.
- **Transcripts are immutable and complete**, in cheap object storage, and
  they are the only thing graders and judges ever read.
- **Scorecards live in version control** next to the tests: small, diffable,
  permanent. This is the memory that makes "did the change help?" answerable.
- **Telemetry dashboards are for trends, never for evidence.** APM systems
  sample and truncate by design — right for latency charts and alerts,
  disqualifying for grading. Share run IDs so a blip on a chart can be
  traced to its exact transcript.
- **Environments:** local with synthetic fixtures for iteration; a staging
  clone with the same fixtures for pre-release confirmation; production
  never — evals do not touch real user data in any environment.

## 7. Running it day to day

- **Before any behavior-affecting change ships** — prompt, model, tools,
  harness — the regression and safety suites run, and the decision is made
  on the scorecard diff against the last accepted run.
- **Repeat-trial runs are scheduled**, not per-commit: reliability numbers
  are slow and cost real money.
- **One trigger is unscheduled and non-negotiable:** the model underneath
  the agent changed — including a provider-side update nobody asked for. This
  is the scenario the entire scorecard history exists for, because it answers
  in minutes what would otherwise be discovered from users.
- **People read transcripts.** Regularly, and always when a score is
  surprising. A failing task whose recording shows reasonable behavior is a
  defective task. Failures should look fair to a human reader, and a score
  nobody has looked behind is not evidence.
- **Ownership:** engineers own the runner, graders, and storage; the people
  closest to users — product owners, domain experts — author and review the
  tasks, which is why task files stay in plain language.
- **Evals precede features.** Writing the eval first forces the success
  criteria to be concrete, and it is the cheapest moment to discover they
  aren't.

## Going deeper (beyond this session)

- **Statistics of small suites** — standard errors on eval scores, paired
  comparisons between variants, and how many tasks you need before a
  score difference means anything.
- **Eval awareness and gaming** — frontier models have been documented
  detecting that they are inside a benchmark, locating its public dataset,
  and decrypting answer keys. Grader and task design is an adversarial
  problem, and safety suites never retire.
- **Continuous evaluation of production traffic** — sampling live
  interactions into the same graders, via standardized trace formats
  (OpenTelemetry GenAI conventions). Requires durable production tracing
  first.
- **Simulated users** — for multi-turn agents, a second model plays the
  user, with its own tools and goals (the τ²-bench pattern).

## Sources

- Anthropic, *Demystifying evals for AI agents* (2026) — grader taxonomy,
  suite lifecycle, task-writing rules, partial credit, judge calibration.
- Anthropic, *Writing tools for agents* (2025) — evaluating and improving
  tools from eval transcripts.
- τ-bench / τ²-bench — end-state grading for conversational agents,
  simulated users, pass^k.
- Princeton HAL (2026) — cost beside accuracy; harness effects on scores.
- Terminal-Bench — harness + model pairs as the unit on the leaderboard.
- Azure AI Foundry agent evaluators; Microsoft Waza — worked examples of
  the judged-metric and skill-evaluation catalogs described here.
