import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { MVP_EVAL_MANIFEST } from "../scripts/mvp_eval_manifest.mjs";
import { buildMvpScorecard } from "../scripts/mvp_scorecard.mjs";
import {
  buildBaselineAcceptance,
  buildScorecardComparison,
  buildScorecardHistoryRecord,
  canonicalJson,
  renderBaselineAcceptance,
  renderScorecardHistoryRecord,
  sha256Canonical,
  validateBaselineAcceptance,
  validateScorecardComparison,
  validateScorecardHistoryRecord,
  writeBaselineAcceptance,
  writeHistoryRecord,
  writeScorecardComparison,
} from "../scripts/mvp_scorecard_history.mjs";

const skillHash = "a".repeat(64);

function withoutHash(value, key) {
  const copy = structuredClone(value);
  delete copy[key];
  return copy;
}

function rehash(value, key) {
  value[key] = sha256Canonical(withoutHash(value, key));
  return value;
}

function recordedJudgeCandidate(record, runId = "judge-only-candidate") {
  const candidate = structuredClone(record);
  candidate.runId = runId;
  candidate.provenance.advisoryJudge = "RECORDED";
  candidate.gates.advisoryJudgeStatus = "RECORDED";
  candidate.metrics.advisoryJudge.status = "RECORDED";
  candidate.evidence.advisoryJudgeSha256 = "d".repeat(64);
  for (const [lane, total, perDimension] of [["atomic", 27, 9], ["workflows", 3, 1]]) {
    const counts = candidate.metrics.advisoryJudge[lane];
    counts.passed = 0;
    counts.failed = 0;
    counts.unknown = total;
    counts.total = total;
    for (const dimension of Object.values(counts.dimensions)) {
      dimension.passed = 0;
      dimension.failed = 0;
      dimension.unknown = perDimension;
      dimension.total = perDimension;
    }
  }
  return rehash(candidate, "recordHash");
}

function reorder(value) {
  if (Array.isArray(value)) return value.map(reorder);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).reverse().map(([key, item]) => [key, reorder(item)]));
}

function inputs(overrides = {}) {
  const fixture = { fixtureVersion: "mvp-demo-v2", fixtureHash: "b".repeat(64), fixturePath: "/absolute/fixture.json" };
  const product = {
    schemaVersion: 3, kind: "mvp-agent-eval", runId: "product-run", startedAt: "2026-07-22T11:59:00Z", completedAt: "2026-07-22T12:00:00Z", sourceRevision: "c".repeat(40), scope: "all",
    fixture, environment: "local-synthetic", harness: "deepagents", model: "product-model",
    skill: { name: "engagement-meeting-prep", version: "1.0.0", path: "session-container/product-skills/engagement-meeting-prep/SKILL.md", sha256: skillHash },
    api: "http://127.0.0.1:18000",
    results: MVP_EVAL_MANIFEST.atomicCaseIds.map((id) => ({ id, pass: true, fixture })),
    workflows: MVP_EVAL_MANIFEST.workflowIds.map((id) => ({ id, pass: true, fixture, groundingReview: { status: "REVIEW_REQUIRED" } })),
    summary: { atomic: { passed: MVP_EVAL_MANIFEST.atomicCaseIds.length, failed: [] }, workflows: { passed: MVP_EVAL_MANIFEST.workflowIds.length, failed: [] } },
  };
  const waza = {
    schemaVersion: "1.2", eval_id: "waza-run", skill: "engagement-meeting-prep", eval_name: "engagement-meeting-prep-eval", timestamp: "2026-07-22T12:00:00Z",
    config: { runs_per_test: 1, model_id: "copilot-model", engine_type: "copilot-sdk", timeout_sec: 300 },
    summary: { total_tests: 4, succeeded: 4, failed: 0, errors: 0, skipped: 0, aggregate_score: 1, duration_ms: 42 },
    tasks: ["WAZA-MP-1-direct-trigger", "WAZA-MP-2-paraphrased-trigger", "WAZA-MP-3-list-does-not-trigger", "WAZA-MP-4-update-does-not-trigger"].map((test_id) => ({ test_id, status: "passed" })),
    metrics: {},
    csaMvpProvenance: {
      runner: "scripts/waza_eval.sh", wazaVersion: "0.38.3", sourceRevision: product.sourceRevision,
      sourceRevisionAfter: product.sourceRevision, sourceDirtyBefore: false, sourceDirtyAfter: false,
      tag: "gate", eval: "tests/evals/waza/engagement-meeting-prep/eval.yaml", recordedAt: "2026-07-22T12:01:00Z",
      skill: { name: "engagement-meeting-prep", path: "session-container/product-skills/engagement-meeting-prep/SKILL.md", sha256: skillHash },
    },
  };
  const grounding = {
    schemaVersion: 1, kind: "mvp-grounding-review", productRunId: product.runId, sourceRevision: product.sourceRevision,
    fixtureVersion: fixture.fixtureVersion, fixtureHash: fixture.fixtureHash, skillSha256: skillHash,
    reviewer: "A reviewer", reviewedAt: "2026-07-22T12:01:00Z",
    reviews: [{ workflowId: "MVP-W1-engagement-meeting-to-action", status: "APPROVED", note: "Grounded against the recorded product-tool outputs." }],
  };
  Object.assign(product, overrides.product);
  Object.assign(waza, overrides.waza);
  Object.assign(grounding, overrides.grounding);
  const scorecard = buildMvpScorecard(product, waza, grounding, null);
  return { product, waza, grounding, scorecard };
}

function history(overrides = {}) {
  const values = inputs(overrides);
  return { ...values, record: buildScorecardHistoryRecord(values.scorecard, values.product, values.waza, values.grounding) };
}

function decision(record, overrides = {}) {
  return {
    schemaVersion: 1, kind: "mvp-scorecard-baseline-decision", recordHash: record.recordHash,
    reviewer: "  Independent   reviewer ", acceptedAt: "2026-07-22T12:02:00Z", decision: "ACCEPTED",
    rationale: "The independently reviewed evidence meets the baseline criteria.", ...overrides,
  };
}

function accept(values, decisionValue = decision(values.record)) {
  return buildBaselineAcceptance(values.record, decisionValue, values.scorecard, values.product, values.waza, values.grounding);
}

test("canonical JSON hashes key-order variants identically while retaining array order", () => {
  const left = { z: [{ second: 2, first: 1 }, "second"], a: true };
  const right = { a: true, z: [{ first: 1, second: 2 }, "second"] };
  assert.equal(canonicalJson(left), canonicalJson(right));
  assert.equal(sha256Canonical(left), sha256Canonical(right));
  assert.notEqual(sha256Canonical(left), sha256Canonical({ a: true, z: ["second", { first: 1, second: 2 }] }));
  for (const value of [{ missing: undefined }, Number.NaN, Infinity, 1n, () => {}, Symbol("x"), [1, , 3]]) {
    assert.throws(() => canonicalJson(value), /Canonical JSON rejects/);
  }
  const arrayProperty = [1]; arrayProperty.extra = true;
  const arraySymbol = [1]; arraySymbol[Symbol("x")] = true;
  const arrayPrototype = [1]; Object.setPrototypeOf(arrayPrototype, null);
  const hiddenArrayProperty = [1]; Object.defineProperty(hiddenArrayProperty, "hidden", { value: true });
  for (const value of [arrayProperty, arraySymbol, arrayPrototype, hiddenArrayProperty]) assert.throws(() => canonicalJson(value), /Canonical JSON/);
});

test("record rebuilds source binding, hashes it, and stores only a sanitized projection", () => {
  const values = inputs();
  const reordered = { product: reorder(values.product), waza: reorder(values.waza), grounding: reorder(values.grounding) };
  const sameScorecard = buildMvpScorecard(reordered.product, reordered.waza, reordered.grounding, null);
  const record = buildScorecardHistoryRecord(values.scorecard, values.product, values.waza, values.grounding);
  const reorderedRecord = buildScorecardHistoryRecord(sameScorecard, reordered.product, reordered.waza, reordered.grounding);
  assert.equal(record.recordHash, reorderedRecord.recordHash);
  const stored = JSON.stringify(record);
  assert.ok(!stored.includes("/absolute/fixture.json"));
  assert.ok(!stored.includes("DO NOT STORE THIS TRANSCRIPT"));
  assert.equal(record.evidence.productSha256, sha256Canonical(values.product));
  assert.equal(record.gates.scorecardAcceptance, "READY_FOR_BASELINE");
});

test("optional advisory judge evidence is bound and hashed rather than trusted from a supplied digest", () => {
  const values = inputs();
  const judge = { schemaVersion: 1, kind: "mvp-advisory-judge-record", untrustedHash: "0".repeat(64) };
  const scorecard = buildMvpScorecard(values.product, values.waza, values.grounding, judge);
  const record = buildScorecardHistoryRecord(scorecard, values.product, values.waza, values.grounding, judge);
  assert.equal(record.evidence.advisoryJudgeSha256, sha256Canonical(judge));
  assert.equal(record.gates.advisoryJudgeStatus, "INVALID");
});

test("record rejects source mismatch, missing evidence, bad paths, and unsafe run IDs", () => {
  const values = inputs();
  assert.throws(() => buildScorecardHistoryRecord({ ...values.scorecard, runId: "different" }, values.product, values.waza, values.grounding), /Scorecard/);
  assert.throws(() => buildScorecardHistoryRecord(values.scorecard, values.product, values.waza, null), /Grounding-review evidence/);
  const traversal = inputs({ product: { runId: "../outside" } });
  assert.throws(() => buildScorecardHistoryRecord(traversal.scorecard, traversal.product, traversal.waza, traversal.grounding), /safe run ID/);
});

test("strict source envelopes reject truthy product passes and malformed duplicate review or Waza evidence", () => {
  const values = inputs();
  const truthy = structuredClone(values.product);
  truthy.results[0].pass = "true";
  assert.throws(() => buildScorecardHistoryRecord(values.scorecard, truthy, values.waza, values.grounding), /items are invalid/);
  const unknownProduct = structuredClone(values.product);
  unknownProduct.untrusted = true;
  assert.throws(() => buildScorecardHistoryRecord(values.scorecard, unknownProduct, values.waza, values.grounding), /exactly these keys/);
  const duplicateReview = structuredClone(values.grounding);
  duplicateReview.reviews.push(structuredClone(duplicateReview.reviews[0]));
  assert.throws(() => buildScorecardHistoryRecord(values.scorecard, values.product, values.waza, duplicateReview), /workflow IDs/);
  const duplicateWaza = structuredClone(values.waza);
  duplicateWaza.tasks.push(structuredClone(duplicateWaza.tasks[0]));
  assert.throws(() => buildScorecardHistoryRecord(values.scorecard, values.product, duplicateWaza, values.grounding), /task IDs/);
  const malformedWaza = structuredClone(values.waza);
  malformedWaza.csaMvpProvenance.sourceDirtyBefore = "false";
  assert.throws(() => buildScorecardHistoryRecord(values.scorecard, values.product, malformedWaza, values.grounding), /dirty-source/);
});

test("history validation rejects extra keys, altered hashes, and incomplete evidence digests", () => {
  const { record } = history();
  assert.throws(() => validateScorecardHistoryRecord({ ...record, extra: true }), /exactly these keys/);
  const altered = structuredClone(record);
  altered.evidence.productSha256 = "0".repeat(64);
  assert.throws(() => validateScorecardHistoryRecord(altered), /hash does not match/);
  const incomplete = structuredClone(record);
  incomplete.evidence.wazaSha256 = "not-a-hash";
  incomplete.recordHash = sha256Canonical(withoutHash(incomplete, "recordHash"));
  assert.throws(() => validateScorecardHistoryRecord(incomplete), /SHA-256/);
  const malformedWaza = structuredClone(record);
  malformedWaza.gates.scorecardAcceptance = "INCOMPLETE";
  malformedWaza.gates.wazaStatus = "FAILED";
  malformedWaza.gates.wazaGate = false;
  malformedWaza.metrics.skillLaboratory.countsConsistent = false;
  malformedWaza.metrics.skillLaboratory.total = 99;
  rehash(malformedWaza, "recordHash");
  assert.doesNotThrow(() => validateScorecardHistoryRecord(malformedWaza));
});

test("strict timestamps, path-like identifiers, and Markdown cells are safely handled", () => {
  const values = history(); const { record } = values;
  for (const acceptedAt of ["2026-02-31T12:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T12:00:00+24:00", "2026-01-01T12:00:00+01:60"]) {
    assert.throws(() => accept(values, decision(record, { acceptedAt })), /RFC3339/);
  }
  const traversal = structuredClone(record);
  traversal.sourceRevision = "../relative";
  rehash(traversal, "recordHash");
  assert.throws(() => validateScorecardHistoryRecord(traversal), /non-path identifier/);
  const markdown = structuredClone(record);
  markdown.sourceRevision = "revision|\\tag";
  markdown.provenance.productRuntime.provenance = "deepagents/model|\\tag";
  rehash(markdown, "recordHash");
  assert.match(renderScorecardHistoryRecord(markdown), /revision\\\|\\\\tag/);
  const acceptance = accept(values, decision(record, { reviewer: "Reviewer | \\ audit" }));
  assert.match(renderBaselineAcceptance(acceptance, record), /Reviewer \\\| \\\\ audit/);
});

test("history artifacts are create-new immutable and conflict without changing existing files", () => {
  const directory = mkdtempSync(join(tmpdir(), "csa-scorecard-history-"));
  try {
    const { record } = history();
    const paths = writeHistoryRecord(directory, record);
    const first = readFileSync(paths.json, "utf8");
    assert.throws(() => writeHistoryRecord(directory, record), /already exists/);
    assert.equal(readFileSync(paths.json, "utf8"), first);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("human acceptance requires a separately bound exact decision and ready history", () => {
  const values = history(); const { record } = values;
  const acceptance = accept(values);
  assert.equal(acceptance.reviewer, "Independent reviewer");
  assert.equal(acceptance.recordHash, record.recordHash);
  assert.equal(acceptance.evidence.groundingReviewSha256, record.evidence.groundingReviewSha256);
  assert.throws(() => accept(values, decision(record, { recordHash: "0".repeat(64) })), /does not bind/);
  assert.throws(() => accept(values, decision(record, { rationale: "One sentence. Another sentence." })), /one sentence/);
  assert.throws(() => accept(values, decision(record, { acceptedAt: "2026-07-22" })), /RFC3339/);
  assert.throws(() => accept(values, { ...decision(record), unknown: true }), /exactly these keys/);
  const rehashed = accept(values);
  rehashed.reviewer = " Reviewer";
  rehash(rehashed, "acceptanceHash");
  assert.throws(() => validateBaselineAcceptance(rehashed, record), /normalized/);
  const replacedBundle = structuredClone(values);
  replacedBundle.product.model = "different-model";
  assert.throws(() => accept(replacedBundle), /Scorecard/);
});

test("acceptance rejects incomplete records and validates copied audit bindings", () => {
  const values = inputs({ product: { results: MVP_EVAL_MANIFEST.atomicCaseIds.map((id, index) => ({ id, pass: index !== 0, fixture: undefined })) } });
  values.product.results = MVP_EVAL_MANIFEST.atomicCaseIds.map((id, index) => ({ id, pass: index !== 0, fixture: values.product.fixture }));
  values.product.summary.atomic = { passed: MVP_EVAL_MANIFEST.atomicCaseIds.length - 1, failed: [MVP_EVAL_MANIFEST.atomicCaseIds[0]] };
  values.scorecard = buildMvpScorecard(values.product, values.waza, values.grounding, null);
  const record = buildScorecardHistoryRecord(values.scorecard, values.product, values.waza, values.grounding);
  assert.equal(record.gates.scorecardAcceptance, "INCOMPLETE");
  assert.throws(() => buildBaselineAcceptance(record, decision(record), values.scorecard, values.product, values.waza, values.grounding), /not READY_FOR_BASELINE/);
  const ready = history();
  const acceptanceForIncomplete = accept(ready);
  Object.assign(acceptanceForIncomplete, {
    recordHash: record.recordHash, runId: record.runId, sourceRevision: record.sourceRevision,
    fixture: structuredClone(record.fixture), skill: structuredClone(record.skill), evidence: structuredClone(record.evidence),
  });
  rehash(acceptanceForIncomplete, "acceptanceHash");
  assert.throws(() => validateBaselineAcceptance(acceptanceForIncomplete, record), /not READY_FOR_BASELINE/);
  const acceptance = accept(ready);
  const tampered = structuredClone(acceptance);
  tampered.fixture.fixtureHash = "0".repeat(64);
  assert.throws(() => validateBaselineAcceptance(tampered, ready.record), /does not match/);
});

test("rehashed readiness, Waza provenance, review, and judge-binding tampering cannot validate", () => {
  const values = history(); const { record } = values;
  const forgedProduct = structuredClone(record);
  forgedProduct.metrics.productRuntime.atomic.passed -= 1;
  forgedProduct.metrics.productRuntime.atomic.failed = [MVP_EVAL_MANIFEST.atomicCaseIds[0]];
  rehash(forgedProduct, "recordHash");
  assert.throws(() => validateScorecardHistoryRecord(forgedProduct), /product hard gate/);

  const arbitraryReview = structuredClone(record);
  arbitraryReview.gates.groundingReviews[0].id = "MVP-W999-arbitrary";
  rehash(arbitraryReview, "recordHash");
  assert.throws(() => validateScorecardHistoryRecord(arbitraryReview), /grounding-review IDs/);

  const forgedWazaGate = structuredClone(record);
  forgedWazaGate.provenance.skillLaboratory.schemaVersion = "9.9";
  rehash(forgedWazaGate, "recordHash");
  assert.throws(() => validateScorecardHistoryRecord(forgedWazaGate), /Waza gate/);

  const judgeDigestMismatch = structuredClone(record);
  judgeDigestMismatch.evidence.advisoryJudgeSha256 = "e".repeat(64);
  rehash(judgeDigestMismatch, "recordHash");
  assert.throws(() => validateScorecardHistoryRecord(judgeDigestMismatch), /advisory evidence binding/);

  assert.throws(() => accept(values, decision(record, { rationale: "One.Two." })), /one sentence/);
});

test("comparison reports deterministic product and Waza regressions while keeping judge deltas advisory", () => {
  const base = history();
  const acceptance = accept(base);
  const candidateValues = inputs({ product: { runId: "candidate-run" } });
  candidateValues.product.results = MVP_EVAL_MANIFEST.atomicCaseIds.map((id, index) => ({ id, pass: index !== 0, fixture: candidateValues.product.fixture }));
  candidateValues.product.summary.atomic = { passed: MVP_EVAL_MANIFEST.atomicCaseIds.length - 1, failed: [MVP_EVAL_MANIFEST.atomicCaseIds[0]] };
  candidateValues.waza.summary = { ...candidateValues.waza.summary, succeeded: 3, failed: 1 };
  candidateValues.waza.tasks[0].status = "failed";
  candidateValues.scorecard = buildMvpScorecard(candidateValues.product, candidateValues.waza, candidateValues.grounding, null);
  const candidate = buildScorecardHistoryRecord(candidateValues.scorecard, candidateValues.product, candidateValues.waza, candidateValues.grounding);
  const comparison = buildScorecardComparison(base.record, acceptance, candidate);
  assert.equal(comparison.deltas.atomic.passed.delta, -1);
  assert.equal(comparison.deltas.waza.passed.delta, -1);
  assert.equal(comparison.regressions.atomic.passedDecreased, true);
  assert.equal(comparison.regressions.waza.gateRegressed, true);
  assert.equal(comparison.regressions.readinessRegressed, true);
  assert.equal(comparison.regressions.blockingRegression, true);
  assert.equal(comparison.deltas.advisoryJudge.advisory, true);

  const judgeOnly = recordedJudgeCandidate(base.record);
  judgeOnly.metrics.advisoryJudge.atomic.failed += 1;
  judgeOnly.metrics.advisoryJudge.atomic.unknown -= 1;
  judgeOnly.metrics.advisoryJudge.atomic.dimensions.accuracy.failed += 1;
  judgeOnly.metrics.advisoryJudge.atomic.dimensions.accuracy.unknown -= 1;
  rehash(judgeOnly, "recordHash");
  const judgeComparison = buildScorecardComparison(base.record, acceptance, judgeOnly);
  assert.equal(judgeComparison.regressions.blockingRegression, false);
  assert.equal(judgeComparison.regressions.advisoryJudge.atomic.failedIncreased, true);

  const wrongRuntime = structuredClone(base.record);
  wrongRuntime.runId = "different-runtime";
  wrongRuntime.provenance.productRuntime.model = "other-model";
  rehash(wrongRuntime, "recordHash");
  assert.throws(() => buildScorecardComparison(base.record, acceptance, wrongRuntime), /product provenance/);
  const wrongWaza = structuredClone(base.record);
  wrongWaza.runId = "different-waza";
  wrongWaza.provenance.skillLaboratory.engine = "other-engine";
  wrongWaza.gates.wazaGate = false;
  wrongWaza.gates.scorecardAcceptance = "INCOMPLETE";
  rehash(wrongWaza, "recordHash");
  assert.throws(() => buildScorecardComparison(base.record, acceptance, wrongWaza), /Waza provenance/);
  const comparisonTamper = structuredClone(judgeComparison);
  comparisonTamper.deltas.atomic.passed.delta = 99;
  rehash(comparisonTamper, "comparisonHash");
  assert.throws(() => validateScorecardComparison(comparisonTamper), /invalid/);
});

test("CLI records, accepts, compares, and never overwrites immutable history", () => {
  const directory = mkdtempSync(join(tmpdir(), "csa-scorecard-history-cli-"));
  try {
    const base = history();
    const candidate = history({ product: { runId: "candidate-cli" } });
    const files = {
      scorecard: join(directory, "scorecard.json"), product: join(directory, "product.json"), waza: join(directory, "waza.json"), grounding: join(directory, "grounding.json"),
      candidateScorecard: join(directory, "candidate-scorecard.json"), candidateProduct: join(directory, "candidate-product.json"),
      decision: join(directory, "decision.json"), root: join(directory, "history"),
    };
    for (const [name, value] of Object.entries({ scorecard: base.scorecard, product: base.product, waza: base.waza, grounding: base.grounding, candidateScorecard: candidate.scorecard, candidateProduct: candidate.product, decision: decision(base.record) })) {
      writeFileSync(files[name], JSON.stringify(value));
    }
    const run = (args) => execFileSync(process.execPath, ["scripts/mvp_scorecard_history.mjs", ...args], { cwd: process.cwd(), encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    run(["record", files.scorecard, files.product, files.waza, files.grounding, files.root]);
    const baseRecord = join(files.root, "product-run.scorecard-history.json");
    assert.ok(existsSync(baseRecord));
    run(["accept", baseRecord, files.decision, files.scorecard, files.product, files.waza, files.grounding, files.root]);
    run(["record", files.candidateScorecard, files.candidateProduct, files.waza, files.grounding, files.root]);
    run(["compare", baseRecord, join(files.root, "product-run.baseline-acceptance.json"), join(files.root, "candidate-cli.scorecard-history.json"), files.root]);
    const comparison = JSON.parse(readFileSync(join(files.root, "product-run--candidate-cli.scorecard-comparison.json"), "utf8"));
    assert.equal(comparison.regressions.readinessRegressed, true);
    assert.equal(comparison.regressions.blockingRegression, true);
    assert.throws(() => run(["record", files.scorecard, files.product, files.waza, files.grounding, files.root]), /Immutable history output already exists/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("immutable acceptance and comparison writers reject existing artifacts", () => {
  const directory = mkdtempSync(join(tmpdir(), "csa-scorecard-history-writers-"));
  try {
    const base = history();
    const acceptance = accept(base);
    writeBaselineAcceptance(directory, acceptance, base.record);
    assert.throws(() => writeBaselineAcceptance(directory, acceptance, base.record), /already exists/);
    const candidate = history({ product: { runId: "writer-candidate" } });
    const comparison = buildScorecardComparison(base.record, acceptance, candidate.record);
    writeScorecardComparison(directory, comparison);
    assert.throws(() => writeScorecardComparison(directory, comparison), /already exists/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
