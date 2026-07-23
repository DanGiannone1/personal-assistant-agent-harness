import { MVP_EVAL_MANIFEST, hasExactCanonicalIds } from "./mvp_eval_manifest.mjs";

function countPassed(items = []) {
  return items.filter((item) => item.pass).length;
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
  const gatePass = countsConsistent
    && schemaVersion === "1.2"
    && engine === "copilot-sdk"
    && provenance?.runner === "scripts/waza_eval.sh"
    && provenance?.wazaVersion === "0.38.3"
    && WAZA_GATE_TASK_IDS.every((id) => taskStatus.get(id) === "passed");
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
  const bindingMatches = reviewRecord.productRunId === expected.productRunId
    && reviewRecord.sourceRevision === expected.sourceRevision
    && reviewRecord.fixtureVersion === expected.fixtureVersion
    && reviewRecord.fixtureHash === expected.fixtureHash
    && reviewRecord.skillSha256 === expected.skillSha256;
  if (!bindingMatches) {
    return {
      binding: { status: "MISMATCHED", expected },
      reviews: workflows.map((workflow) => ({ id: workflow.id, ...workflow.groundingReview })),
    };
  }
  const supplied = new Map((reviewRecord.reviews ?? []).map((review) => [review.workflowId, review]));
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

export function buildMvpScorecard(productReport, wazaReport = null, groundingReviewRecord = null) {
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
  const productHardGatePass = productReport.scope === "all"
    && fixtureConsistent && canonicalAtomicSuite && canonicalWorkflowSuite
    && atomic.every((item) => item.pass) && workflows.every((item) => item.pass);
  const grounding = bindGroundingReviews(productReport, groundingReviewRecord);
  const groundingReviews = grounding.reviews;
  const waza = summarizeWaza(wazaReport);
  const wazaSkillMatches = waza.status === "RECORDED"
    && waza.skill === productReport.skill?.name
    && waza.runnerProvenance?.skill?.name === productReport.skill?.name
    && waza.runnerProvenance?.skill?.sha256 === productReport.skill?.sha256;
  const wazaSourceMatches = waza.status === "RECORDED"
    && waza.runnerProvenance?.sourceDirtyBefore === false
    && waza.runnerProvenance?.sourceDirtyAfter === false
    && waza.runnerProvenance?.sourceRevision === productReport.sourceRevision
    && waza.runnerProvenance?.sourceRevisionAfter === productReport.sourceRevision;
  return {
    schemaVersion: 1,
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
        atomic: { passed: countPassed(atomic), total: atomic.length, failed: atomic.filter((item) => !item.pass).map((item) => item.id) },
        workflows: { passed: countPassed(workflows), total: workflows.length, failed: workflows.filter((item) => !item.pass).map((item) => item.id) },
        fixtureConsistent,
        canonicalAtomicSuite,
        canonicalWorkflowSuite,
        hardGatePass: productHardGatePass,
        groundingReviewBinding: grounding.binding,
        groundingReviews,
      },
      skillLaboratory: {
        ...waza,
        skillNameMatchesProduct: wazaSkillMatches,
        sourceMatchesProduct: wazaSourceMatches,
      },
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
| Atomic checks | ${product.atomic.passed}/${product.atomic.total} |
| Workflow checks | ${product.workflows.passed}/${product.workflows.total} |
| Fixture consistency | ${product.fixtureConsistent ? "PASS" : "FAIL"} |
| Canonical atomic suite | ${product.canonicalAtomicSuite ? "PASS" : "FAIL"} |
| Canonical workflow suite | ${product.canonicalWorkflowSuite ? "PASS" : "FAIL"} |
| Product hard gate | ${product.hardGatePass ? "PASS" : "FAIL"} |
| Grounding review binding | ${product.groundingReviewBinding.status} |
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
`;
}
