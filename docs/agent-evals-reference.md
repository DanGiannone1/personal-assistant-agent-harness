# Evaluating AI Agents — A Reference

This document explains how to evaluate an AI agent: an assistant that uses
tools to read and change real data on a user's behalf. It is a general guide.
It does not describe any specific product, and it contains no status or
roadmap. How one team applies it is always a separate, smaller document.

Four words used throughout:

- A **task** is one test: a request plus a definition of success.
- A **trial** is one attempt at a task.
- A **grader** is whatever scores an attempt.
- A **transcript** is the complete recording of one attempt: the tools the
  agent used, the data before and after, what it said, and how long it took.

One more, because it matters more than people expect: the **harness** is the
code that connects the AI model to the tools and the application. Test
results belong to the model *and* the harness together — swapping the harness
around the same model measurably changes results, which is why public
leaderboards now score them as a pair. Always record both, and if you have
more than one harness, run the same tasks against each and compare.

## What to evaluate

Six things, continuously:

1. **Capability** — can the agent do the jobs users ask of it?
2. **Truthfulness** — does what it *says* match what actually *happened*? It
   must never claim an action it didn't complete, deny or omit one it did, or
   state facts its tools never returned.
3. **Safety** — does it refuse everything it must refuse, without leaking
   anything in the process?
4. **Consistency** — does it behave the same way when asked the same thing
   again?
5. **Performance** — is it fast enough and cheap enough?
6. **Change impact** — did the latest change make things better or worse, and
   by how much? Improvements need proof just as much as regressions do.

Every run scores all six and leaves a permanent scorecard, so any change — a
new prompt, a new model, new tools — can be compared against the last known
good state, number by number.

## Why agents can't be tested like normal software

Each way agents differ from ordinary software forces one piece of the
method. The method isn't a style choice — it's what's left once you take
these five facts seriously:

| What's different about agents | What it forces |
|---|---|
| The same request produces different behavior each run | Run important tasks several times; measure consistency, never assume it |
| There are many valid ways to do a job correctly | Define success by the outcome — how the data ends up and what lines weren't crossed — never by one required sequence of steps |
| The output is part action, part language | Code grades the facts; an AI judge grades the words; neither grades the other's territory |
| It can be confidently wrong | Always check the reply against the recorded facts, so a fluent claim of success can't pass on confidence alone |
| It acts on real systems | Test in a controlled environment with known data, reset before every attempt — never against real users' data |

Those five facts produce a four-part loop:

1. **Define success before running.** Every task states in advance what must
   be true afterward: how the data should look, what the agent must never do,
   and what a good reply must say. Success defined after the fact is opinion.
2. **Run and record.** The agent attempts the task while everything is
   captured: every tool call and its inputs, every data change, the full
   reply, all timings. This recording is the one thing every grader reads —
   and because grading works from a recording, it can be redone, improved,
   and applied to old runs at any time.
3. **Grade the recording, three ways.**
   - **Code checks the facts.** Did the data end up right? Did anything
     change that shouldn't have? Did a forbidden action run? No AI involved.
   - **An AI judge checks the words.** Is the reply accurate, based on what
     the tools actually returned, and safe to say? Some failures exist only
     in wording — a refusal phrased as "you don't have access to X" confirms
     that X exists, which can itself be a leak. No code check can catch
     that. This class of failure is why a judge is part of the method at all.
   - **Measurements are taken, not judged:** total time, time until the
     reply starts, tokens, cost, and how many tool calls it took.
4. **Score, keep, compare.** Each run produces a small permanent scorecard.
   Nothing is declared better or worse by impression — only by comparing
   scorecards, in both directions: regressions must be caught, and claimed
   improvements must show up.

## What you need before you can start

Six things. If one is missing, the results can't be trusted or compared.

| # | You need | Why |
|---|---|---|
| 1 | Test questions | You can only measure what you test. Write questions users would really ask. Don't write them from the tool list — that only tests what you already built. |
| 2 | The right answer for each question | How should the data look after? What must the agent never do? What should a good reply say? If this isn't written down, grading is opinion. Writing questions is fast; writing right answers is the real work. |
| 3 | The same starting data every time | If every run starts from different data, "the right answer" means nothing. |
| 4 | A script that asks the questions and records everything | The recording is what gets graded. Anything not recorded can never be graded. |
| 5 | Graders | Code for the facts, an AI judge for the words. Each catches problems the other can't see. |
| 6 | A place to keep the scores | One run tells you nothing. Comparing this week's run to last week's is the entire point. |

## How one run works

1. Pick which tests to run (see "Three kinds of test suites" below).
2. For each task: reset the data, snapshot it, send the question exactly as a
   user would, record everything, snapshot again.
3. Code grading runs immediately: data outcomes, forbidden actions, nothing
   else changed, plus the measurements.
4. Judge grading runs on the recordings: each task's judge questions get a
   verdict and a one-sentence reason.
5. Write the scorecard: pass rates, safety result, speed, cost — plus which
   harness, model, and code version produced it.
6. Compare against the previous accepted scorecard, both directions.
7. **Read some recordings.** Never take scores at face value. When a task
   fails, the recording shows whether the agent truly failed or a grader
   rejected a valid answer. Failures should look fair when a person reads
   them. If they don't, fix the test, not the score.

## The grading rules

1. **Grade what the agent produced, not the path it took.** The data outcome
   and the forbidden-action list are hard pass/fail. The exact tool sequence
   is recorded and reported, but never pass/fail — agents regularly find
   valid approaches the test author didn't anticipate, and rigid
   step-checking fails correct behavior.
2. **The judge only grades words.** It can never overrule a code check — the
   database beats any opinion about wording. But the two graders can
   disagree, in both directions, and both disagreements are useful: code
   fails but the judge passes usually means the test was too narrow; code
   passes but the judge fails means the agent did the right thing and
   communicated it badly. Review disagreements — don't average them away.
3. **Code never grades wording.** No keyword matching on what the agent
   said, ever. Words belong to the judge.
4. **Keep partial credit.** Report the fraction of checks each task passed,
   not just pass/fail — an agent that got three of four steps right is
   better than one that failed immediately, and the scores should show it.
   The exception is safety: safety tasks are all-or-nothing, always.

## Writing good test questions

- **The two-expert test.** A question is well written when two people who
  know the product would independently agree on pass or fail — and could
  pass it themselves. Vague questions become noisy numbers.
- **Every task needs one proven-good answer on file** — a recording that
  passes every grader. It proves the task is solvable and the graders work.
  If nothing can pass a task after many tries, the task is almost certainly
  broken, not the agent.
- **Write questions the way people actually talk.** "Use the navigation tool
  to open my portfolio" tests plumbing, not behavior.
- **Test both directions.** For every behavior, include questions where it
  should happen and questions where it shouldn't (change vs. refuse; act vs.
  ask first). One-sided tests train one-sided agents.
- **Accept every legitimate behavior — consistently.** If refusing outright
  and asking a clarifying question are both correct, say so in the task. And
  if one task accepts a harmless extra step (like reading before refusing),
  every similar task must accept it too, or a style change in the model
  turns into false failures.
- **Questions come from the job, not the tool list.** Write them from what
  users actually need — including things the agent can't do yet. A test that
  fails because a capability is missing is information about the product.
  Keep it and report it; don't delete it to make the numbers look good.

## Three kinds of test suites

- **Capability** — "what can it do well?" *Supposed to start with a low pass
  rate.* It aims at what the agent struggles with, including features you
  plan to build — write the tests before the feature, and when a new model
  or prompt lands, the suite instantly shows which bets paid off.
- **Regression** — "does it still handle everything it used to?" Should sit
  near 100%; any drop means something broke. Capability tasks that become
  reliably passable move into regression.
- **Safety** — refusals, leak prevention, resistance to instructions hidden
  in messages. Zero tolerance, runs every time, never moves out.

When a capability suite passes everything, it has stopped teaching you
anything — add harder tasks.

## The AI judge

- One question per topic — accuracy, leakage, tone are asked separately, not
  scored as one blob.
- Every verdict comes with a one-sentence reason, written *before* the
  verdict.
- "Unknown" is always an allowed answer. If the recording doesn't contain
  enough to decide, the judge must say so instead of guessing.
- The judge model must be different from the model being tested — a broken
  model must never grade itself.
- **The judge earns trust before it blocks anything.** Compare its verdicts
  against human spot-checks on real recordings; keep it advisory until the
  agreement is good, and keep spot-checking occasionally forever.
- The judge questions live with the task. The thing that asks them — a
  person today, an automated judge tomorrow — can change; the questions
  don't.

## What to measure

| Measure | Plain meaning | Blocks a release? |
|---|---|---|
| Check pass rate | Of all individual checks across all tasks, how many passed | Yes — must not drop against the baseline |
| Task pass rate | How many tasks fully passed | Yes — regression suite stays near 100% |
| Safety | Did every safety task pass | Yes — one failure fails the run |
| Truthfulness | No reply contradicted the recorded facts | Treat like safety once the judge is trusted |
| Judge pass rate | How many judge questions passed | Advisory until the judge is trusted |
| At-least-once rate (often written "pass@k") | Try a task k times: the chance at least one try succeeds — "can it do this at all?" | Reported |
| Every-time rate (often written "pass^k") | The chance all k tries succeed — "can users rely on it?" This is the customer-experience number | Reported |
| Speed | Seconds per answer — typical and worst case, plus time until the reply starts | Reported; alert on big jumps |
| Effort | Tool calls per task compared to the proven-good answer — catches flailing | Reported |
| Cost | Tokens per answer, money per run — always shown next to accuracy | Reported and trended |

Every scorecard records which harness, model, code version, test-data
version, and environment produced it, so comparisons are always
like-for-like.

## Where to keep things

Three different homes, because the data has three different jobs:

| Data | Keep it in | Why |
|---|---|---|
| Full recordings | Cheap file storage, one folder per run | Must stay complete and exact forever — this is the only thing graders and judges read |
| Scorecards | Version control, next to the tests | Small, permanent, and comparable across time |
| Timing and cost numbers | A telemetry dashboard | Good for trends and alerts |

The rule that keeps this honest: dashboards trim, sample, and expire data by
design — fine for trends, disqualifying for evidence. **Graders and judges
read only the recordings.** Give recordings and dashboard entries the same
run ID so a slow blip on a chart can be traced to its exact recording.

Label every result with the environment it came from, and never compare
results across environments as if they were the same thing. And never, in
any environment, run evals against real users' data.

## When to run

- **Before any change ships** that could affect behavior — prompt, model,
  tools, harness: regression and safety suites, compared to the baseline.
- **Safety: every run**, no exceptions.
- **Capability and repeat-trials: nightly or on demand** — they're slow and
  cost money.
- **When the underlying model changes** — including when a provider updates
  a model you didn't choose to change. That is precisely the moment the
  scorecard history pays for itself.

Evals are one leg of understanding an agent. Watching production, listening
to users, and reading recordings are the others. A test suite that drifts
away from what users actually do creates false confidence — once real usage
data exists, real failures become the best source of new test questions.

## Sources

Checked against current published practice (reviewed 2026-07-19):

- Anthropic, *Demystifying evals for AI agents* (January 2026) — grader
  types, capability vs. regression suites, question-writing rules, "grade
  the product, not the path," partial credit, judge calibration, reading
  recordings, the at-least-once and every-time rates.
- Princeton, *HAL: Holistic Agent Leaderboard* (2026) — cost shown beside
  accuracy, harness effects on scores, reliability as the current frontier.
- Terminal-Bench — harness + model pairs as the unit on the leaderboard.
- τ-bench / τ²-bench — grading conversational agents by the end state of a
  database; simulated users; the every-time rate.
