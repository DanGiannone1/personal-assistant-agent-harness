import { MVP_EVAL_MANIFEST, atomicScoringMode, expectedAtomicScoredCheckNames, expectedAtomicScoringPath, expectedWorkflowCheckContract, expectedWorkflowScoredCheckNames, hasExactCanonicalIds } from "./mvp_eval_manifest.mjs";
import { summarizeMvpJudge } from "./mvp_judge.mjs";

function countPassed(items = []) {
  return items.filter((item) => item.pass === true).length;
}

function latencyAggregate(items, label) {
  const values = items.map((item) => item?.latencyMs);
  if (!values.every((value) => Number.isSafeInteger(value) && value >= 0)) {
    throw new Error(`${label} latencyMs must be a non-negative safe integer`);
  }
  const totalMs = values.reduce((total, value) => total + value, 0);
  if (!Number.isSafeInteger(totalMs)) throw new Error(`${label} latency total exceeds the safe integer range`);
  return values.length === 0
    ? { count: 0, totalMs: 0, minMs: null, maxMs: null, meanMs: null }
    : { count: values.length, totalMs, minMs: Math.min(...values), maxMs: Math.max(...values), meanMs: Math.floor(totalMs / values.length) };
}

function workflowTurnLatencyItems(workflows) {
  const items = [];
  for (const workflow of workflows) {
    let contract;
    try { contract = expectedWorkflowCheckContract(workflow.id); } catch {
      items.push(...(workflow.turns ?? []));
      continue;
    }
    if (!Array.isArray(workflow.turns) || workflow.turns.length !== contract.turns.length
      || workflow.turns.some((turn, index) => turn?.id !== contract.turns[index].id)) {
      throw new Error(`Workflow ${workflow.id} latency turns do not match the canonical workflow`);
    }
    items.push(...workflow.turns);
  }
  return items;
}

function hasExactKeys(value, expected) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  return actual.length === keys.length && actual.every((key, index) => key === keys[index]);
}

function sameBooleanMap(left, right) {
  if (!left || !right || typeof left !== "object" || typeof right !== "object" || Array.isArray(left) || Array.isArray(right)) return false;
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return JSON.stringify(leftKeys) === JSON.stringify(rightKeys)
    && leftKeys.every((key) => typeof left[key] === "boolean" && left[key] === right[key]);
}

function workflowEvidenceMatches(item) {
  let contract;
  try { contract = expectedWorkflowCheckContract(item.id); } catch { return false; }
  if (!Array.isArray(item.turnResults) || item.turnResults.length !== contract.turns.length) return false;
  const reconstructed = {};
  for (const name of contract.workflowNames) {
    if (typeof item.checks?.[name] !== "boolean") return false;
    reconstructed[name] = item.checks[name];
  }
  for (const [index, turn] of contract.turns.entries()) {
    const result = item.turnResults[index];
    const expectedNames = turn.names;
    const turnFailed = expectedNames.filter((name) => result?.scoredChecks?.[name] !== true);
    const turnScore = result?.checkScore;
    if (!result || result.checkScore?.mode !== "partial" || result.checkScore?.path !== "primary"
      || !sameBooleanMap(result.scoredChecks, Object.fromEntries(expectedNames.map((name) => [name, result.checks?.[name]])))
      || !hasExactKeys(turnScore, ["mode", "path", "observed", "credit"])
      || !hasExactKeys(turnScore.observed, ["passed", "total", "failed"])
      || !hasExactKeys(turnScore.credit, ["passed", "total"])
      || !Array.isArray(turnScore.observed.failed)
      || turnScore.observed.passed !== expectedNames.length - turnFailed.length
      || turnScore.observed.total !== expectedNames.length
      || JSON.stringify([...turnScore.observed.failed].sort()) !== JSON.stringify([...turnFailed].sort())
      || turnScore.credit.passed !== turnScore.observed.passed || turnScore.credit.total !== turnScore.observed.total
      || result.pass !== Object.values(result.checks ?? {}).every((value) => value === true)
      || result.pass !== Object.values(result.scoredChecks ?? {}).every((value) => value === true)) return false;
    for (const name of expectedNames) reconstructed[`${turn.id}.${name}`] = result.scoredChecks[name];
  }
  if (item.checks?.allTurnsPass !== item.turnResults.every((result) => result.pass === true)) return false;
  return sameBooleanMap(item.scoredChecks, reconstructed);
}

function completeCheckScore(item, kind) {
  const score = item?.checkScore;
  if (!hasExactKeys(score, ["mode", "path", "observed", "credit"])
    || !["partial", "all-or-nothing"].includes(score.mode)
    || !["primary", "safeNonExecution", "workflow"].includes(score.path)) return null;
  const observed = score.observed;
  const credit = score.credit;
  const scoredChecks = item?.scoredChecks;
  const scoredNames = scoredChecks && typeof scoredChecks === "object" && !Array.isArray(scoredChecks)
    ? Object.keys(scoredChecks)
    : [];
  const failedNames = scoredNames.filter((name) => scoredChecks[name] !== true);
  const sourceChecks = score.path === "safeNonExecution" ? item?.safeNonExecution?.checks : item?.checks;
  let expectedNames;
  try {
    expectedNames = kind === "atomic"
      ? expectedAtomicScoredCheckNames(item.id, score.path)
      : expectedWorkflowScoredCheckNames(item.id);
  } catch { return null; }
  if (!hasExactKeys(observed, ["passed", "total", "failed"])
    || !hasExactKeys(credit, ["passed", "total"])
    || !scoredChecks || scoredNames.length === 0 || !scoredNames.every((name) => typeof scoredChecks[name] === "boolean")
    || !sourceChecks || typeof sourceChecks !== "object" || Array.isArray(sourceChecks)
    || typeof item.pass !== "boolean"
    || !Number.isInteger(observed.passed) || !Number.isInteger(observed.total)
    || !Array.isArray(observed.failed) || !Number.isInteger(credit.passed) || !Number.isInteger(credit.total)
    || observed.passed < 0 || observed.total <= 0 || observed.passed > observed.total
    || credit.total !== observed.total || observed.passed + observed.failed.length !== observed.total
    || credit.passed < 0 || credit.passed > credit.total
    || new Set(observed.failed).size !== observed.failed.length
    || !observed.failed.every((name) => typeof name === "string" && !!name.trim())
    || observed.total !== scoredNames.length
    || JSON.stringify([...scoredNames].sort()) !== JSON.stringify([...expectedNames].sort())
    || JSON.stringify([...observed.failed].sort()) !== JSON.stringify([...failedNames].sort())
    || observed.passed !== scoredNames.length - failedNames.length
    || scoredNames.some((name) => score.path !== "workflow" && sourceChecks[name] !== scoredChecks[name])
    || Object.values(sourceChecks).some((value) => typeof value !== "boolean")
    || item.pass !== Object.values(sourceChecks).every((value) => value === true)
    || item.pass !== (observed.passed === observed.total)
    || score.mode === "partial" && credit.passed !== observed.passed
    || score.mode === "all-or-nothing" && credit.passed !== (item.pass ? credit.total : 0)) return null;
  if (kind === "atomic") {
    let expectedPath;
    try { expectedPath = expectedAtomicScoringPath(item.id, item.checks, item.safeNonExecution?.checks ?? null); } catch { return null; }
    if (score.path !== expectedPath) return null;
  } else if (!workflowEvidenceMatches(item)) return null;
  return score;
}

export function hasCompleteCheckScore(item, kind) {
  return completeCheckScore(item, kind) !== null;
}

function checkMetrics(items, kind) {
  const scores = items.map((item) => completeCheckScore(item, kind));
  return {
    checks: {
      passed: scores.reduce((total, score) => total + (score?.credit.passed ?? 0), 0),
      total: scores.reduce((total, score) => total + (score?.credit.total ?? 0), 0),
    },
    complete: scores.every(Boolean),
  };
}

export const WAZA_GATE_TASK_IDS = Object.freeze([
  "WAZA-MP-1-direct-trigger",
  "WAZA-MP-2-paraphrased-trigger",
  "WAZA-MP-3-list-does-not-trigger",
  "WAZA-MP-4-update-does-not-trigger",
]);

function wazaTrialOutcome(trial) {
  if (trial?.status === "passed") return "passed";
  if (trial?.status === "failed") return "failed";
  if (trial?.status === "error") return "error";
  if (trial?.status === "skipped") return "skipped";
  if (trial?.passed === true || trial?.pass === true) return "passed";
  if (trial?.passed === false || trial?.pass === false) return "failed";
  return "unknown";
}

function isCount(value) {
  return Number.isInteger(value) && value >= 0;
}

function declaredPassedCount(summary) {
  const values = [summary?.succeeded, summary?.passed].filter((value) => value !== undefined);
  if (!values.length || !values.every(isCount) || !values.every((value) => value === values[0])) return null;
  return values[0];
}

export function summarizeWaza(wazaReport) {
  if (!wazaReport) {
    return {
      status: "NOT_RUN",
      provenance: "waza/copilot-sdk",
      note: "Supply a Waza results JSON file to the scorecard merger; Waza evidence is not Deep Agents product-runtime evidence.",
    };
  }
  const trialCollection = wazaReport.trials ?? wazaReport.results ?? wazaReport.outcomes ?? wazaReport.tasks;
  const trials = Array.isArray(trialCollection) ? trialCollection : [];
  const outcomes = trials.map(wazaTrialOutcome);
  const passed = outcomes.filter((outcome) => outcome === "passed").length;
  const failed = trials
    .filter((trial, index) => ["failed", "error"].includes(outcomes[index]))
    .map((trial) => trial.task_id ?? trial.taskId ?? trial.test_id ?? trial.id ?? "unknown");
  const observedFailed = outcomes.filter((outcome) => outcome === "failed").length;
  const observedErrors = outcomes.filter((outcome) => outcome === "error").length;
  const observedSkipped = outcomes.filter((outcome) => outcome === "skipped").length;
  const summary = wazaReport.summary ?? {};
  const total = summary.total_tests ?? trials.length;
  const errors = summary.errors ?? observedErrors;
  const skipped = summary.skipped ?? observedSkipped;
  const declaredPassed = declaredPassedCount(summary);
  const countsConsistent = Array.isArray(trialCollection)
    && isCount(summary.total_tests) && isCount(declaredPassed) && isCount(summary.failed)
    && isCount(summary.errors) && isCount(summary.skipped)
    && summary.total_tests === trials.length
    && summary.total_tests === declaredPassed + summary.failed + summary.errors + summary.skipped
    && declaredPassed === passed && summary.failed === observedFailed
    && summary.errors === observedErrors && summary.skipped === observedSkipped
    && !outcomes.includes("unknown");
  const completePass = countsConsistent && total > 0 && passed === total && failed.length === 0 && errors === 0 && skipped === 0;
  const taskStatus = new Map(trials.map((trial) => [
    trial.task_id ?? trial.taskId ?? trial.test_id ?? trial.id,
    trial.status ?? (trial.passed === true || trial.pass === true ? "passed" : "failed"),
  ]));
  const provenance = wazaReport.csaMvpProvenance ?? null;
  const engine = wazaReport.config?.engine_type ?? null;
  const schemaVersion = wazaReport.schemaVersion ?? wazaReport.schema_version ?? null;
  const exactGateTasks = trials.length === WAZA_GATE_TASK_IDS.length
    && new Set(trials.map((trial) => trial.task_id ?? trial.taskId ?? trial.test_id ?? trial.id)).size === WAZA_GATE_TASK_IDS.length
    && WAZA_GATE_TASK_IDS.every((id) => taskStatus.get(id) === "passed");
  const gatePass = countsConsistent
    && schemaVersion === "1.2"
    && engine === "copilot-sdk"
    && provenance?.runner === "scripts/waza_eval.sh"
    && provenance?.wazaVersion === "0.38.3"
    && provenance?.tag === "gate"
    && provenance?.eval === "tests/evals/waza/engagement-meeting-prep/eval.yaml"
    && exactGateTasks;
  return {
    status: completePass ? "RECORDED" : "FAILED",
    provenance: `waza/${engine ?? "unknown-engine"}`,
    schemaVersion,
    runId: wazaReport.run_id ?? wazaReport.runId ?? wazaReport.eval_id ?? null,
    skill: wazaReport.skill ?? null,
    model: wazaReport.config?.model_id ?? null,
    engine,
    passed,
    total,
    failed,
    errors,
    skipped,
    countsConsistent,
    aggregateScore: wazaReport.summary?.aggregate_score ?? null,
    durationMs: wazaReport.summary?.duration_ms ?? null,
    usage: wazaReport.summary?.usage ?? null,
    gateTaskIds: [...WAZA_GATE_TASK_IDS],
    gatePass,
    runnerProvenance: provenance,
  };
}

function bindGroundingReviews(productReport, reviewRecord) {
  const workflows = productReport.workflows ?? [];
  const expected = {
    productRunId: productReport.runId,
    sourceRevision: productReport.sourceRevision,
    fixtureVersion: productReport.fixture?.fixtureVersion,
    fixtureHash: productReport.fixture?.fixtureHash,
    skillSha256: productReport.skill?.sha256,
  };
  if (!reviewRecord) {
    return {
      binding: { status: "NOT_SUPPLIED", expected },
      reviews: workflows.map((workflow) => ({ id: workflow.id, ...workflow.groundingReview })),
    };
  }
  const reviews = reviewRecord.reviews;
  const uniqueKnownReviews = Array.isArray(reviews)
    && new Set(reviews.map((review) => review?.workflowId)).size === reviews.length
    && reviews.every((review) => MVP_EVAL_MANIFEST.workflowIds.includes(review?.workflowId));
  const bindingMatches = reviewRecord.productRunId === expected.productRunId
    && reviewRecord.sourceRevision === expected.sourceRevision
    && reviewRecord.fixtureVersion === expected.fixtureVersion
    && reviewRecord.fixtureHash === expected.fixtureHash
    && reviewRecord.skillSha256 === expected.skillSha256
    && uniqueKnownReviews;
  if (!bindingMatches) {
    return {
      binding: { status: "MISMATCHED", expected },
      reviews: workflows.map((workflow) => ({ id: workflow.id, ...workflow.groundingReview })),
    };
  }
  const supplied = new Map(reviews.map((review) => [review.workflowId, review]));
  return {
    binding: {
      status: "MATCHED",
      expected,
      reviewer: reviewRecord.reviewer,
      reviewedAt: reviewRecord.reviewedAt,
    },
    reviews: workflows.map((workflow) => {
      const review = supplied.get(workflow.id);
      const valid = review && ["APPROVED", "REJECTED"].includes(review.status)
        && typeof reviewRecord.reviewer === "string" && reviewRecord.reviewer.trim()
        && typeof reviewRecord.reviewedAt === "string" && reviewRecord.reviewedAt.trim();
      return valid ? {
        id: workflow.id,
        status: review.status,
        reviewer: reviewRecord.reviewer,
        reviewedAt: reviewRecord.reviewedAt,
        note: review.note ?? "",
      } : { id: workflow.id, ...workflow.groundingReview };
    }),
  };
}

export function buildMvpScorecard(productReport, wazaReport = null, groundingReviewRecord = null, judgeRecord = null) {
  const atomic = productReport.results ?? [];
  const workflows = productReport.workflows ?? [];
  const fixtureVersion = productReport.fixture?.fixtureVersion;
  const fixtureHash = productReport.fixture?.fixtureHash;
  const fixtureConsistent = typeof fixtureVersion === "string" && !!fixtureVersion
    && typeof fixtureHash === "string" && !!fixtureHash
    && [...atomic, ...workflows].every((item) =>
      item.fixture?.fixtureVersion === fixtureVersion && item.fixture?.fixtureHash === fixtureHash);
  const canonicalAtomicSuite = hasExactCanonicalIds(atomic, MVP_EVAL_MANIFEST.atomicCaseIds);
  const canonicalWorkflowSuite = hasExactCanonicalIds(workflows, MVP_EVAL_MANIFEST.workflowIds);
  const atomicCheckEvidence = checkMetrics(atomic, "atomic");
  const workflowCheckEvidence = checkMetrics(workflows, "workflow");
  const checkEvidence = {
    checks: {
      passed: atomicCheckEvidence.checks.passed + workflowCheckEvidence.checks.passed,
      total: atomicCheckEvidence.checks.total + workflowCheckEvidence.checks.total,
    },
    complete: atomicCheckEvidence.complete && workflowCheckEvidence.complete,
  };
  const canonicalScoringModes = atomic.every((item) => item.checkScore?.mode === atomicScoringMode(item.id)
    && ["primary", "safeNonExecution"].includes(item.checkScore?.path))
    && workflows.every((item) => item.checkScore?.mode === "partial" && item.checkScore?.path === "workflow");
  const productHardGatePass = productReport.scope === "all"
    && fixtureConsistent && canonicalAtomicSuite && canonicalWorkflowSuite && canonicalScoringModes
    && checkEvidence.complete
    && atomic.every((item) => item.pass === true) && workflows.every((item) => item.pass === true);
  const grounding = bindGroundingReviews(productReport, groundingReviewRecord);
  const groundingReviews = grounding.reviews;
  const waza = summarizeWaza(wazaReport);
  const judge = summarizeMvpJudge(judgeRecord, productReport);
  const wazaSkillMatches = waza.status === "RECORDED"
    && waza.skill === productReport.skill?.name
    && waza.runnerProvenance?.skill?.name === productReport.skill?.name
    && waza.runnerProvenance?.skill?.sha256 === productReport.skill?.sha256;
  const wazaSourceMatches = waza.status === "RECORDED"
    && waza.runnerProvenance?.sourceDirtyBefore === false
    && waza.runnerProvenance?.sourceDirtyAfter === false
    && waza.runnerProvenance?.sourceRevision === productReport.sourceRevision
    && waza.runnerProvenance?.sourceRevisionAfter === productReport.sourceRevision;
  const latency = {
    measurement: "end-to-end harness wall-clock",
    unit: "ms",
    gating: false,
    atomic: latencyAggregate(atomic, "Atomic product evidence"),
    workflowTurns: latencyAggregate(workflowTurnLatencyItems(workflows), "Workflow-turn product evidence"),
  };
  return {
    schemaVersion: 3,
    kind: "mvp-eval-scorecard",
    runId: productReport.runId,
    generatedAt: productReport.completedAt ?? new Date().toISOString(),
    sourceRevision: productReport.sourceRevision,
    fixture: productReport.fixture,
    skill: productReport.skill,
    lanes: {
      productRuntime: {
        provenance: `${productReport.harness}/${productReport.model}`,
        environment: productReport.environment,
        scope: productReport.scope ?? "UNSPECIFIED",
        atomic: { passed: countPassed(atomic), total: atomic.length, failed: atomic.filter((item) => item.pass !== true).map((item) => item.id) },
        workflows: { passed: countPassed(workflows), total: workflows.length, failed: workflows.filter((item) => item.pass !== true).map((item) => item.id) },
        checks: checkEvidence.checks,
        latency,
        checkEvidenceComplete: checkEvidence.complete,
        fixtureConsistent,
        canonicalAtomicSuite,
        canonicalWorkflowSuite,
        canonicalScoringModes,
        hardGatePass: productHardGatePass,
        groundingReviewBinding: grounding.binding,
        groundingReviews,
      },
      skillLaboratory: {
        ...waza,
        skillNameMatchesProduct: wazaSkillMatches,
        sourceMatchesProduct: wazaSourceMatches,
      },
      advisoryJudge: judge,
    },
    acceptance: {
      status: productHardGatePass && waza.status === "RECORDED" && waza.gatePass
        && wazaSkillMatches && wazaSourceMatches
        && groundingReviews.every((review) => review.status === "APPROVED") ? "READY_FOR_BASELINE" : "INCOMPLETE",
      baseline: "NOT_ACCEPTED",
      note: "A human accepts a baseline only after hard checks pass and the grounding transcript is reviewed. This file never self-accepts a run.",
    },
  };
}

export function renderMvpScorecard(scorecard) {
  const product = scorecard.lanes.productRuntime;
  const waza = scorecard.lanes.skillLaboratory;
  const judge = scorecard.lanes.advisoryJudge;
  const judgeBinding = judge.binding.expected;
  const markdownCell = (value) => String(value ?? "UNSPECIFIED")
    .replace(/[\r\n]+/g, " ")
    .replaceAll("\\", "\\\\")
    .replaceAll("|", "\\|");
  const judgeProvenance = judge.provenance?.judge
    ? judge.provenance.judge.kind === "human"
      ? `human reviewer=${markdownCell(judge.provenance.judge.reviewer)}`
      : `model provider=${markdownCell(judge.provenance.judge.provider)}; model=${markdownCell(judge.provenance.judge.model)}`
    : "NOT_RECORDED";
  const judgeObservedBinding = judge.binding.observed
    ? `run=${markdownCell(judge.binding.observed.productRunId)}; source=${markdownCell(judge.binding.observed.sourceRevision)}; fixture=${markdownCell(judge.binding.observed.fixtureVersion)}/${markdownCell(judge.binding.observed.fixtureHash)}; skill SHA-256=${markdownCell(judge.binding.observed.skillSha256)}`
    : "NOT_RECORDED";
  const judgeDimensions = (counts) => ["accuracy", "leakage", "tone"].map((dimension) => {
    const value = counts.dimensions[dimension];
    return `${dimension}: ${value.passed} pass / ${value.failed} fail / ${value.unknown} unknown (${value.total} total)`;
  }).join("; ");
  const wazaTokens = waza.usage ? (waza.usage.input_tokens ?? 0) + (waza.usage.output_tokens ?? 0) : null;
  const wazaUsage = waza.usage
    ? `${waza.usage.turns ?? "?"} turns; ${wazaTokens} input+output tokens; ${waza.usage.premium_requests ?? "?"} premium requests`
    : "NOT_RECORDED";
  const reviews = product.groundingReviews.map((review) => `- ${review.id}: ${review.status}`).join("\n") || "- none";
  return `# CSA Workbench evaluation scorecard

| Field | Value |
|---|---|
| Run | ${scorecard.runId} |
| Source revision | ${scorecard.sourceRevision} |
| Product runtime | ${product.provenance} |
| Product environment | ${product.environment} |
| Product scope | ${product.scope} |
| Skill | ${scorecard.skill?.name ?? "UNSPECIFIED"} @ ${scorecard.skill?.sha256 ?? "UNSPECIFIED"} |
| Atomic tasks | ${product.atomic.passed}/${product.atomic.total} |
| Workflow tasks | ${product.workflows.passed}/${product.workflows.total} |
| Credited check pass rate | ${product.checks.passed}/${product.checks.total}${product.checkEvidenceComplete ? "" : " (incomplete evidence)"} |
| Atomic end-to-end harness wall-clock | ${product.latency.atomic.count} turns; ${product.latency.atomic.totalMs} ms total; ${product.latency.atomic.meanMs ?? "N/A"} ms mean (non-gating) |
| Workflow-turn end-to-end harness wall-clock | ${product.latency.workflowTurns.count} turns; ${product.latency.workflowTurns.totalMs} ms total; ${product.latency.workflowTurns.meanMs ?? "N/A"} ms mean (non-gating) |
| Fixture consistency | ${product.fixtureConsistent ? "PASS" : "FAIL"} |
| Canonical atomic suite | ${product.canonicalAtomicSuite ? "PASS" : "FAIL"} |
| Canonical workflow suite | ${product.canonicalWorkflowSuite ? "PASS" : "FAIL"} |
| Product hard gate | ${product.hardGatePass ? "PASS" : "FAIL"} |
| Grounding review binding | ${product.groundingReviewBinding.status} |
| Advisory judge | ${judge.status} (${judge.advisory ? "advisory" : "not advisory"}) |
| Advisory judge binding | ${judge.binding.status} |
| Advisory judge expected binding | run=${markdownCell(judgeBinding.productRunId)}; source=${markdownCell(judgeBinding.sourceRevision)}; fixture=${markdownCell(judgeBinding.fixtureVersion)}/${markdownCell(judgeBinding.fixtureHash)}; skill SHA-256=${markdownCell(judgeBinding.skillSha256)} |
| Advisory judge observed binding | ${judgeObservedBinding} |
| Advisory judge provenance | ${judgeProvenance} |
| Advisory judge timestamp / rubric | ${markdownCell(judge.provenance?.judgedAt ?? "NOT_RECORDED")} / ${markdownCell(judge.provenance?.rubricVersion ?? "NOT_RECORDED")} |
| Advisory judge atomic verdicts | ${judge.atomic.passed} pass / ${judge.atomic.failed} fail / ${judge.atomic.unknown} unknown (${judge.atomic.total} total) |
| Advisory judge atomic dimensions | ${judgeDimensions(judge.atomic)} |
| Advisory judge workflow verdicts | ${judge.workflows.passed} pass / ${judge.workflows.failed} fail / ${judge.workflows.unknown} unknown (${judge.workflows.total} total) |
| Advisory judge workflow dimensions | ${judgeDimensions(judge.workflows)} |
| Advisory judge diagnostic | ${markdownCell(judge.error ?? "VALID_OR_NOT_SUPPLIED")} |
| Waza lane | ${waza.status} (${waza.provenance}) |
| Waza run | ${waza.runId ?? "NOT_RECORDED"} |
| Waza skill | ${waza.skill ?? "UNSPECIFIED"} (${waza.skillNameMatchesProduct ? "matches product" : "does not match product"}) |
| Waza source | ${waza.sourceMatchesProduct ? "matches clean product revision" : "does not match clean product revision"} |
| Waza runtime | ${waza.engine ?? "UNSPECIFIED"} / ${waza.model ?? "UNSPECIFIED"} |
| Waza checks | ${waza.passed ?? 0}/${waza.total ?? 0} |
| Waza gate | ${waza.gatePass ? "PASS" : "FAIL / NOT_RECORDED"} |
| Waza usage | ${wazaUsage} |
| Baseline | ${scorecard.acceptance.baseline} |
| Acceptance | ${scorecard.acceptance.status} |

## Grounding review

${reviews}

Waza skill-laboratory evidence and Deep Agents product-runtime evidence intentionally retain
separate provenance. Neither substitutes for the other.

End-to-end harness wall-clock timing covers POST completion plus trace fetch and parse. It is reported
in milliseconds only and is non-gating; it is not TTFT or model-only latency.
`;
}
