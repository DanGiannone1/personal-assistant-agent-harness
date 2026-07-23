import { createHash } from "node:crypto";
import { closeSync, existsSync, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, unlinkSync, writeFileSync } from "node:fs";
import { basename, isAbsolute, relative, resolve } from "node:path";

import { buildMvpScorecard, WAZA_GATE_TASK_IDS } from "./mvp_scorecard.mjs";
import { MVP_EVAL_MANIFEST } from "./mvp_eval_manifest.mjs";

const HASH = /^[a-f0-9]{64}$/;
const SAFE_RUN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

const HISTORY_KEYS = [
  "schemaVersion", "kind", "runId", "sourceRevision", "fixture", "skill", "provenance", "gates", "metrics", "evidence", "recordHash",
];
const DECISION_KEYS = ["schemaVersion", "kind", "recordHash", "reviewer", "acceptedAt", "decision", "rationale"];
const ACCEPTANCE_KEYS = [
  "schemaVersion", "kind", "recordHash", "runId", "sourceRevision", "fixture", "skill", "evidence", "reviewer", "acceptedAt", "decision", "rationale", "acceptanceHash",
];
const COMPARISON_KEYS = [
  "schemaVersion", "kind", "baseline", "candidate", "deltas", "regressions", "comparisonHash",
];

export function canonicalJson(value) {
  const ancestors = new Set();
  const encode = (item) => {
    if (item === null || typeof item === "string" || typeof item === "boolean") return JSON.stringify(item);
    if (typeof item === "number") {
      if (!Number.isFinite(item)) throw new Error("Canonical JSON rejects non-finite numbers");
      return JSON.stringify(item);
    }
    if (typeof item !== "object") throw new Error(`Canonical JSON rejects ${typeof item}`);
    if (ancestors.has(item)) throw new Error("Canonical JSON rejects cycles");
    ancestors.add(item);
    let encoded;
    if (Array.isArray(item)) {
      if (Object.getPrototypeOf(item) !== Array.prototype || Object.getOwnPropertySymbols(item).length) throw new Error("Canonical JSON accepts only standard arrays");
      for (let index = 0; index < item.length; index += 1) {
        if (!Object.hasOwn(item, index)) throw new Error("Canonical JSON rejects sparse arrays");
      }
      if (Object.getOwnPropertyNames(item).some((key) => key !== "length" && (!/^(0|[1-9]\d*)$/.test(key) || Number(key) >= item.length))) throw new Error("Canonical JSON rejects array properties");
      encoded = `[${item.map(encode).join(",")}]`;
    } else {
      const prototype = Object.getPrototypeOf(item);
      if (prototype !== Object.prototype && prototype !== null || Object.getOwnPropertySymbols(item).length) {
        throw new Error("Canonical JSON accepts only plain JSON objects");
      }
      encoded = `{${Object.keys(item).sort().map((key) => `${JSON.stringify(key)}:${encode(item[key])}`).join(",")}}`;
    }
    ancestors.delete(item);
    return encoded;
  };
  return encode(value);
}

export function sha256Canonical(value) {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function exactKeys(value, keys, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} must be an object`);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error(`${label} must contain exactly these keys: ${keys.join(", ")}`);
  }
}

function normalizedHuman(value, label) {
  if (typeof value !== "string") throw new Error(`${label} must be a string`);
  const normalized = value.trim().replace(/\s+/g, " ");
  if (!normalized || /[\u0000-\u001f\u007f]/.test(normalized)) throw new Error(`${label} must be non-empty plain text`);
  return normalized;
}

function requireNormalizedHuman(value, label) {
  const normalized = normalizedHuman(value, label);
  if (value !== normalized) throw new Error(`${label} must be normalized`);
  return value;
}

function requireOneSentence(value, label) {
  const normalized = requireNormalizedHuman(value, label);
  if (!/^[^.!?]+[.!?]$/.test(normalized)) throw new Error(`${label} must be one sentence`);
  return normalized;
}

function requireRfc3339(value, label) {
  if (typeof value !== "string") throw new Error(`${label} must be a strict RFC3339 timestamp`);
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$/);
  if (!match) {
    throw new Error(`${label} must be a strict RFC3339 timestamp`);
  }
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, zone, , offsetHourText, offsetMinuteText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  const daysInMonth = [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const offsetHour = zone === "Z" ? 0 : Number(offsetHourText);
  const offsetMinute = zone === "Z" ? 0 : Number(offsetMinuteText);
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth[month - 1] || hour > 23 || minute > 59 || second > 59 || offsetHour > 23 || offsetMinute > 59) {
    throw new Error(`${label} must be a strict RFC3339 timestamp`);
  }
  return value;
}

function requireHash(value, label) {
  if (typeof value !== "string" || !HASH.test(value)) throw new Error(`${label} must be a lowercase SHA-256 hex digest`);
  return value;
}

function requireRunId(value, label = "runId") {
  if (typeof value !== "string" || !SAFE_RUN_ID.test(value) || value === "." || value === ".." || value.includes("..")) {
    throw new Error(`${label} must be a safe run ID`);
  }
  return value;
}

function requireSafeIdentifier(value, label) {
  if (typeof value !== "string" || !value || value !== value.trim() || /[\u0000-\u001f\u007f]/.test(value) || isAbsolute(value)
    || value.includes("..") || /^[\\/]|^[A-Za-z]:[\\/]|(?:^|[\\/])\.{1,2}(?:[\\/]|$)/.test(value)) {
    throw new Error(`${label} must be a non-path identifier`);
  }
  return value;
}

function requireSafeProvenance(value, label) {
  if (typeof value !== "string" || !value || value !== value.trim() || /[\u0000-\u001f\u007f]/.test(value)
    || value.includes("..") || isAbsolute(value) || /^[A-Za-z]:[\\/]|(?:^|[\\/])(?:\/|[A-Za-z]:[\\/])/.test(value)) {
    throw new Error(`${label} must be safe provenance`);
  }
  return value;
}

function requireExactValue(actual, expected, label) {
  if (canonicalJson(actual) !== canonicalJson(expected)) throw new Error(`${label} does not match its rebuilt evidence`);
}

function numberOrNull(value, label) {
  if (value !== null && (typeof value !== "number" || !Number.isFinite(value))) throw new Error(`${label} must be a finite number or null`);
  return value;
}

function countMetrics(counts, label) {
  exactKeys(counts, ["passed", "total", "failed"], label);
  if (!counts || typeof counts !== "object") throw new Error(`${label} is missing`);
  for (const key of ["passed", "total"]) {
    if (!Number.isInteger(counts[key]) || counts[key] < 0) throw new Error(`${label}.${key} must be a non-negative integer`);
  }
  if (!Array.isArray(counts.failed) || !counts.failed.every((id) => {
    requireSafeIdentifier(id, `${label}.failed ID`);
    return true;
  })) throw new Error(`${label}.failed must be an ID array`);
  if (counts.passed + counts.failed.length !== counts.total) throw new Error(`${label} counts are inconsistent`);
  return { passed: counts.passed, total: counts.total, failed: [...counts.failed] };
}

function judgeMetrics(counts, label, status) {
  exactKeys(counts, ["passed", "failed", "unknown", "total", "dimensions"], label);
  for (const key of ["failed", "unknown"]) {
    if (!Number.isInteger(counts[key]) || counts[key] < 0) throw new Error(`${label}.${key} must be a non-negative integer`);
  }
  if (![counts.passed, counts.total].every((count) => Number.isInteger(count) && count >= 0)) throw new Error(`${label} counts are invalid`);
  const result = { passed: counts.passed, total: counts.total };
  const dimensions = {};
  let dimensionPassed = 0;
  let dimensionFailed = 0;
  let dimensionUnknown = 0;
  let dimensionTotal = 0;
  for (const dimension of ["accuracy", "leakage", "tone"]) {
    const value = counts?.dimensions?.[dimension];
    exactKeys(value, ["passed", "failed", "unknown", "total"], `${label}.dimensions.${dimension}`);
    if (!value || !["passed", "failed", "unknown", "total"].every((key) => Number.isInteger(value[key]) && value[key] >= 0)) {
      throw new Error(`${label}.dimensions.${dimension} is missing`);
    }
    if (value.passed + value.failed + value.unknown !== value.total) throw new Error(`${label}.dimensions.${dimension} counts are inconsistent`);
    dimensionPassed += value.passed;
    dimensionFailed += value.failed;
    dimensionUnknown += value.unknown;
    dimensionTotal += value.total;
    dimensions[dimension] = { passed: value.passed, failed: value.failed, unknown: value.unknown, total: value.total };
  }
  if (status === "RECORDED" && (result.total !== dimensionTotal || result.passed + counts.failed + counts.unknown !== result.total || result.passed !== dimensionPassed || counts.failed !== dimensionFailed || counts.unknown !== dimensionUnknown)) {
    throw new Error(`${label} counts are inconsistent`);
  }
  if (status !== "RECORDED" && (result.passed !== 0 || counts.failed !== 0 || counts.unknown !== 0 || dimensionPassed !== 0 || dimensionFailed !== 0 || dimensionUnknown !== 0)) {
    throw new Error(`${label} must have zero observed verdicts when not recorded`);
  }
  return { passed: result.passed, failed: counts.failed, unknown: counts.unknown, total: result.total, dimensions };
}

function sourceEvidence(scorecard, product, waza, groundingReview, judgeRecord) {
  return {
    scorecardSha256: sha256Canonical(scorecard),
    productSha256: sha256Canonical(product),
    wazaSha256: sha256Canonical(waza),
    groundingReviewSha256: sha256Canonical(groundingReview),
    advisoryJudgeSha256: judgeRecord === null ? null : sha256Canonical(judgeRecord),
  };
}

function recordWithoutHash(record) {
  const { recordHash, ...withoutHash } = record;
  return withoutHash;
}

function isOneOf(value, values, label) {
  if (!values.includes(value)) throw new Error(`${label} is invalid`);
  return value;
}

export function isReadyForBaseline(record) {
  const gates = record.gates;
  const waza = record.metrics.skillLaboratory;
  return gates.productHardGate && gates.groundingReviewBinding === "MATCHED"
    && gates.groundingReviews.length === MVP_EVAL_MANIFEST.workflowIds.length
    && new Set(gates.groundingReviews.map((review) => review.id)).size === gates.groundingReviews.length
    && gates.groundingReviews.every((review) => MVP_EVAL_MANIFEST.workflowIds.includes(review.id) && review.status === "APPROVED")
    && gates.wazaStatus === "RECORDED" && gates.wazaGate && gates.wazaSkillMatchesProduct && gates.wazaSourceMatchesProduct
    && waza.countsConsistent === true;
}

function acceptanceWithoutHash(acceptance) {
  const { acceptanceHash, ...withoutHash } = acceptance;
  return withoutHash;
}

function comparisonWithoutHash(comparison) {
  const { comparisonHash, ...withoutHash } = comparison;
  return withoutHash;
}

const PRODUCT_KEYS = ["schemaVersion", "kind", "runId", "sourceRevision", "scope", "fixture", "environment", "harness", "model", "skill", "api", "startedAt", "completedAt", "results", "workflows", "summary"];
const GROUNDING_KEYS = ["schemaVersion", "kind", "productRunId", "sourceRevision", "fixtureVersion", "fixtureHash", "skillSha256", "reviewer", "reviewedAt", "reviews"];
const WAZA_KEYS = ["schemaVersion", "eval_id", "skill", "eval_name", "timestamp", "config", "summary", "metrics", "tasks", "csaMvpProvenance"];

function requireFixtureBinding(fixture, label) {
  if (!fixture || typeof fixture !== "object" || Array.isArray(fixture)) throw new Error(`${label} is invalid`);
  requireSafeIdentifier(fixture.fixtureVersion, `${label}.fixtureVersion`);
  requireHash(fixture.fixtureHash, `${label}.fixtureHash`);
}

function validateSummary(summary, items, label) {
  exactKeys(summary, ["passed", "failed"], label);
  if (!Number.isInteger(summary.passed) || summary.passed < 0 || !Array.isArray(summary.failed) || !summary.failed.every((id) => typeof id === "string")) throw new Error(`${label} is invalid`);
  const failed = items.filter((item) => item.pass === false).map((item) => item.id);
  if (summary.passed !== items.filter((item) => item.pass === true).length || canonicalJson(summary.failed) !== canonicalJson(failed)) throw new Error(`${label} does not match evidence`);
}

export function validateProductEvidence(product) {
  exactKeys(product, PRODUCT_KEYS, "Product evidence");
  if (product.schemaVersion !== 3 || product.kind !== "mvp-agent-eval") throw new Error("Product evidence has an unsupported schema");
  requireRunId(product.runId, "Product evidence.runId");
  if (typeof product.sourceRevision !== "string" || !/^[a-f0-9]{7,64}$/.test(product.sourceRevision)) throw new Error("Product evidence.sourceRevision must be a lowercase Git revision");
  isOneOf(product.scope, ["all", "atomic", "workflow"], "Product evidence.scope");
  requireFixtureBinding(product.fixture, "Product evidence.fixture");
  for (const key of ["environment", "harness", "model"]) requireSafeIdentifier(product[key], `Product evidence.${key}`);
  exactKeys(product.skill, ["name", "version", "path", "sha256"], "Product evidence.skill");
  requireSafeIdentifier(product.skill.name, "Product evidence.skill.name");
  requireSafeIdentifier(product.skill.version, "Product evidence.skill.version");
  if (product.skill.path !== "session-container/product-skills/engagement-meeting-prep/SKILL.md") throw new Error("Product evidence.skill.path is invalid");
  requireHash(product.skill.sha256, "Product evidence.skill.sha256");
  if (typeof product.api !== "string" || !/^https?:\/\//.test(product.api) || /[\u0000-\u001f\u007f]/.test(product.api)) throw new Error("Product evidence.api is invalid");
  requireRfc3339(product.startedAt, "Product evidence.startedAt");
  requireRfc3339(product.completedAt, "Product evidence.completedAt");
  if (Date.parse(product.completedAt) < Date.parse(product.startedAt)) throw new Error("Product evidence timestamps are invalid");
  if (!Array.isArray(product.results) || !Array.isArray(product.workflows)) throw new Error("Product evidence suites are invalid");
  const validateItems = (items, canonicalIds, label) => {
    if (!items.every((item) => item && typeof item === "object" && typeof item.id === "string" && typeof item.pass === "boolean")) throw new Error(`${label} items are invalid`);
    if (!items.every((item) => canonicalIds.includes(item.id))) throw new Error(`${label} IDs are invalid`);
    if (new Set(items.map((item) => item.id)).size !== items.length) throw new Error(`${label} IDs are duplicated`);
    for (const item of items) requireFixtureBinding(item.fixture, `${label}.${item.id}.fixture`);
  };
  validateItems(product.results, MVP_EVAL_MANIFEST.atomicCaseIds, "Product evidence atomic");
  validateItems(product.workflows, MVP_EVAL_MANIFEST.workflowIds, "Product evidence workflow");
  const expectedAtomic = product.scope === "workflow" ? [] : MVP_EVAL_MANIFEST.atomicCaseIds;
  const expectedWorkflows = product.scope === "atomic" ? [] : MVP_EVAL_MANIFEST.workflowIds;
  if (product.results.length !== expectedAtomic.length || product.workflows.length !== expectedWorkflows.length
    || !expectedAtomic.every((id) => product.results.some((item) => item.id === id))
    || !expectedWorkflows.every((id) => product.workflows.some((item) => item.id === id))) throw new Error("Product evidence scope suite is incomplete");
  if (![...product.results, ...product.workflows].every((item) => item.fixture.fixtureVersion === product.fixture.fixtureVersion && item.fixture.fixtureHash === product.fixture.fixtureHash)) throw new Error("Product evidence fixture binding is inconsistent");
  exactKeys(product.summary, ["atomic", "workflows"], "Product evidence.summary");
  validateSummary(product.summary.atomic, product.results, "Product evidence.summary.atomic");
  validateSummary(product.summary.workflows, product.workflows, "Product evidence.summary.workflows");
  return structuredClone(product);
}

export function validateGroundingReviewEvidence(review) {
  exactKeys(review, GROUNDING_KEYS, "Grounding review");
  if (review.schemaVersion !== 1 || review.kind !== "mvp-grounding-review") throw new Error("Grounding review has an unsupported schema");
  requireRunId(review.productRunId, "Grounding review.productRunId");
  if (typeof review.sourceRevision !== "string" || !/^[a-f0-9]{7,64}$/.test(review.sourceRevision)) throw new Error("Grounding review.sourceRevision must be a lowercase Git revision");
  requireSafeIdentifier(review.fixtureVersion, "Grounding review.fixtureVersion");
  requireHash(review.fixtureHash, "Grounding review.fixtureHash");
  requireHash(review.skillSha256, "Grounding review.skillSha256");
  requireNormalizedHuman(review.reviewer, "Grounding review.reviewer");
  requireRfc3339(review.reviewedAt, "Grounding review.reviewedAt");
  if (!Array.isArray(review.reviews) || new Set(review.reviews.map((entry) => entry?.workflowId)).size !== review.reviews.length) throw new Error("Grounding review workflow IDs are invalid");
  for (const entry of review.reviews) {
    exactKeys(entry, ["workflowId", "status", "note"], "Grounding review entry");
    if (!MVP_EVAL_MANIFEST.workflowIds.includes(entry.workflowId)) throw new Error("Grounding review workflow ID is invalid");
    isOneOf(entry.status, ["APPROVED", "REJECTED"], "Grounding review status");
    if (typeof entry.note !== "string" || entry.note !== entry.note.trim().replace(/\s+/g, " ") || /[\u0000-\u001f\u007f]/.test(entry.note)) throw new Error("Grounding review note is invalid");
  }
  return structuredClone(review);
}

export function validateWazaEvidence(waza) {
  exactKeys(waza, WAZA_KEYS, "Waza evidence");
  if (waza.schemaVersion !== "1.2") throw new Error("Waza evidence has an unsupported schema");
  for (const key of ["eval_id", "skill", "eval_name"]) requireSafeIdentifier(waza[key], `Waza evidence.${key}`);
  requireRfc3339(waza.timestamp, "Waza evidence.timestamp");
  exactKeys(waza.config, ["runs_per_test", "model_id", "engine_type", "timeout_sec"], "Waza evidence.config");
  if (!Number.isInteger(waza.config.runs_per_test) || waza.config.runs_per_test < 1 || !Number.isInteger(waza.config.timeout_sec) || waza.config.timeout_sec < 1) throw new Error("Waza evidence.config is invalid");
  requireSafeIdentifier(waza.config.model_id, "Waza evidence.config.model_id");
  requireSafeIdentifier(waza.config.engine_type, "Waza evidence.config.engine_type");
  if (!waza.summary || typeof waza.summary !== "object" || Array.isArray(waza.summary)) throw new Error("Waza evidence.summary is invalid");
  for (const key of ["total_tests", "succeeded", "failed", "errors", "skipped"]) if (!Number.isInteger(waza.summary[key]) || waza.summary[key] < 0) throw new Error("Waza evidence summary counts are invalid");
  if (!waza.metrics || typeof waza.metrics !== "object" || Array.isArray(waza.metrics)) throw new Error("Waza evidence.metrics is invalid");
  if (!Array.isArray(waza.tasks) || new Set(waza.tasks.map((task) => task?.test_id)).size !== waza.tasks.length) throw new Error("Waza evidence task IDs are invalid");
  if (!waza.tasks.every((task) => task && typeof task === "object" && typeof task.test_id === "string" && ["passed", "failed", "error", "skipped"].includes(task.status))) throw new Error("Waza evidence tasks are invalid");
  exactKeys(waza.csaMvpProvenance, ["runner", "wazaVersion", "sourceRevision", "sourceRevisionAfter", "sourceDirtyBefore", "sourceDirtyAfter", "tag", "skill", "eval", "recordedAt"], "Waza evidence provenance");
  const provenance = waza.csaMvpProvenance;
  if (provenance.runner !== "scripts/waza_eval.sh" || provenance.wazaVersion !== "0.38.3" || provenance.eval !== "tests/evals/waza/engagement-meeting-prep/eval.yaml") throw new Error("Waza evidence provenance is invalid");
  for (const key of ["sourceRevision", "sourceRevisionAfter"]) if (typeof provenance[key] !== "string" || !/^[a-f0-9]{7,64}$/.test(provenance[key])) throw new Error("Waza evidence source revision is invalid");
  if (typeof provenance.sourceDirtyBefore !== "boolean" || typeof provenance.sourceDirtyAfter !== "boolean") throw new Error("Waza evidence dirty-source binding is invalid");
  isOneOf(provenance.tag, ["gate", "advisory", "all"], "Waza evidence provenance.tag");
  exactKeys(provenance.skill, ["name", "path", "sha256"], "Waza evidence provenance.skill");
  if (provenance.skill.name !== "engagement-meeting-prep" || provenance.skill.path !== "session-container/product-skills/engagement-meeting-prep/SKILL.md") throw new Error("Waza evidence skill provenance is invalid");
  requireHash(provenance.skill.sha256, "Waza evidence skill hash");
  requireRfc3339(provenance.recordedAt, "Waza evidence recordedAt");
  return structuredClone(waza);
}

export function buildScorecardHistoryRecord(scorecard, product, waza, groundingReview, judgeRecord = null) {
  if (!product || typeof product !== "object" || !product.completedAt) {
    throw new Error("Product evidence must include completedAt so scorecard reconstruction is deterministic");
  }
  if (!waza || typeof waza !== "object") throw new Error("Waza evidence is required");
  if (!groundingReview || typeof groundingReview !== "object") throw new Error("Grounding-review evidence is required");
  if (judgeRecord !== null && (!judgeRecord || typeof judgeRecord !== "object")) throw new Error("Advisory judge evidence must be an object when supplied");
  validateProductEvidence(product);
  validateWazaEvidence(waza);
  validateGroundingReviewEvidence(groundingReview);

  const rebuilt = buildMvpScorecard(product, waza, groundingReview, judgeRecord);
  requireExactValue(scorecard, rebuilt, "Scorecard");
  if (scorecard.kind !== "mvp-eval-scorecard" || scorecard.schemaVersion !== 1) throw new Error("Scorecard has an unsupported schema");

  const productLane = scorecard.lanes?.productRuntime;
  const wazaLane = scorecard.lanes?.skillLaboratory;
  const judgeLane = scorecard.lanes?.advisoryJudge;
  requireRunId(scorecard.runId);
  requireSafeIdentifier(scorecard.sourceRevision, "sourceRevision");
  if (!scorecard.fixture || typeof scorecard.fixture.fixtureVersion !== "string" || typeof scorecard.fixture.fixtureHash !== "string") {
    throw new Error("Scorecard fixture binding is required");
  }
  if (!scorecard.skill || typeof scorecard.skill.name !== "string" || typeof scorecard.skill.sha256 !== "string") throw new Error("Scorecard skill binding is required");
  requireHash(scorecard.skill.sha256, "scorecard.skill.sha256");
  if (!productLane || !wazaLane || !judgeLane) throw new Error("Scorecard lanes are required");

  const record = {
    schemaVersion: 1,
    kind: "mvp-scorecard-history-record",
    runId: scorecard.runId,
    sourceRevision: scorecard.sourceRevision,
    fixture: { fixtureVersion: scorecard.fixture.fixtureVersion, fixtureHash: scorecard.fixture.fixtureHash },
    skill: { name: scorecard.skill.name, sha256: scorecard.skill.sha256 },
    provenance: {
      productRuntime: {
        harness: product.harness,
        model: product.model,
        environment: productLane.environment,
        provenance: productLane.provenance,
      },
      skillLaboratory: {
        provenance: wazaLane.provenance,
        engine: wazaLane.engine,
        model: wazaLane.model,
        schemaVersion: wazaLane.schemaVersion,
        runner: wazaLane.runnerProvenance?.runner ?? null,
        wazaVersion: wazaLane.runnerProvenance?.wazaVersion ?? null,
        gateTaskIds: [...(wazaLane.gateTaskIds ?? [])],
      },
      advisoryJudge: judgeLane.status,
    },
    gates: {
      scorecardAcceptance: scorecard.acceptance?.status,
      scope: productLane.scope,
      fixtureConsistent: productLane.fixtureConsistent,
      canonicalAtomicSuite: productLane.canonicalAtomicSuite,
      canonicalWorkflowSuite: productLane.canonicalWorkflowSuite,
      productHardGate: productLane.hardGatePass,
      groundingReviewBinding: productLane.groundingReviewBinding?.status,
      groundingReviews: productLane.groundingReviews.map((review) => ({ id: review.id, status: review.status })),
      wazaStatus: wazaLane.status,
      wazaGate: wazaLane.gatePass,
      wazaSkillMatchesProduct: wazaLane.skillNameMatchesProduct,
      wazaSourceMatchesProduct: wazaLane.sourceMatchesProduct,
      advisoryJudgeStatus: judgeLane.status,
      advisoryJudgeAdvisory: judgeLane.advisory,
    },
    metrics: {
      productRuntime: {
        atomic: countMetrics(productLane.atomic, "productRuntime.atomic"),
        workflows: countMetrics(productLane.workflows, "productRuntime.workflows"),
      },
      skillLaboratory: {
        passed: wazaLane.passed,
        total: wazaLane.total,
        failed: [...(wazaLane.failed ?? [])],
        errors: wazaLane.errors,
        skipped: wazaLane.skipped,
        countsConsistent: wazaLane.countsConsistent,
        aggregateScore: numberOrNull(wazaLane.aggregateScore, "skillLaboratory.aggregateScore"),
        durationMs: numberOrNull(wazaLane.durationMs, "skillLaboratory.durationMs"),
      },
      advisoryJudge: {
        status: judgeLane.status,
        atomic: judgeMetrics(judgeLane.atomic, "advisoryJudge.atomic", judgeLane.status),
        workflows: judgeMetrics(judgeLane.workflows, "advisoryJudge.workflows", judgeLane.status),
      },
    },
    evidence: sourceEvidence(scorecard, product, waza, groundingReview, judgeRecord),
  };
  record.recordHash = sha256Canonical(record);
  return validateScorecardHistoryRecord(record);
}

export function validateScorecardHistoryRecord(record) {
  exactKeys(record, HISTORY_KEYS, "History record");
  if (record.schemaVersion !== 1 || record.kind !== "mvp-scorecard-history-record") throw new Error("History record has an unsupported schema");
  requireRunId(record.runId);
  requireSafeIdentifier(record.sourceRevision, "History record.sourceRevision");
  if (!record.fixture || typeof record.fixture.fixtureVersion !== "string" || typeof record.fixture.fixtureHash !== "string") throw new Error("History record fixture is invalid");
  exactKeys(record.fixture, ["fixtureVersion", "fixtureHash"], "History record.fixture");
  requireSafeIdentifier(record.fixture.fixtureVersion, "History record.fixture.fixtureVersion");
  requireHash(record.fixture.fixtureHash, "History record.fixture.fixtureHash");
  if (!record.skill || typeof record.skill.name !== "string") throw new Error("History record skill is invalid");
  exactKeys(record.skill, ["name", "sha256"], "History record.skill");
  requireSafeIdentifier(record.skill.name, "History record.skill.name");
  requireHash(record.skill.sha256, "History record.skill.sha256");
  exactKeys(record.provenance, ["productRuntime", "skillLaboratory", "advisoryJudge"], "History record.provenance");
  exactKeys(record.provenance.productRuntime, ["harness", "model", "environment", "provenance"], "History record product provenance");
  exactKeys(record.provenance.skillLaboratory, ["provenance", "engine", "model", "schemaVersion", "runner", "wazaVersion", "gateTaskIds"], "History record Waza provenance");
  for (const key of ["harness", "model", "environment"]) requireSafeIdentifier(record.provenance.productRuntime[key], `History record product provenance.${key}`);
  requireSafeProvenance(record.provenance.productRuntime.provenance, "History record product provenance.provenance");
  requireSafeProvenance(record.provenance.skillLaboratory.provenance, "History record Waza provenance.provenance");
  for (const key of ["engine", "model"]) {
    if (record.provenance.skillLaboratory[key] !== null) requireSafeIdentifier(record.provenance.skillLaboratory[key], `History record Waza provenance.${key}`);
  }
  for (const key of ["schemaVersion", "runner", "wazaVersion"]) {
    if (record.provenance.skillLaboratory[key] !== null) requireSafeIdentifier(record.provenance.skillLaboratory[key], `History record Waza provenance.${key}`);
  }
  if (!Array.isArray(record.provenance.skillLaboratory.gateTaskIds) || !record.provenance.skillLaboratory.gateTaskIds.every((id) => {
    requireSafeIdentifier(id, "History record Waza gate task ID");
    return true;
  })) throw new Error("History record Waza gate task IDs are invalid");
  isOneOf(record.provenance.advisoryJudge, ["NOT_SUPPLIED", "RECORDED", "INVALID"], "History record advisory provenance");
  exactKeys(record.gates, ["scorecardAcceptance", "scope", "fixtureConsistent", "canonicalAtomicSuite", "canonicalWorkflowSuite", "productHardGate", "groundingReviewBinding", "groundingReviews", "wazaStatus", "wazaGate", "wazaSkillMatchesProduct", "wazaSourceMatchesProduct", "advisoryJudgeStatus", "advisoryJudgeAdvisory"], "History record.gates");
  isOneOf(record.gates.scorecardAcceptance, ["READY_FOR_BASELINE", "INCOMPLETE"], "History record scorecard acceptance");
  isOneOf(record.gates.scope, ["all", "atomic", "workflow", "UNSPECIFIED"], "History record product scope");
  isOneOf(record.gates.groundingReviewBinding, ["MATCHED", "MISMATCHED", "NOT_SUPPLIED"], "History record grounding binding");
  isOneOf(record.gates.wazaStatus, ["RECORDED", "FAILED", "NOT_RUN"], "History record Waza status");
  isOneOf(record.gates.advisoryJudgeStatus, ["NOT_SUPPLIED", "RECORDED", "INVALID"], "History record advisory status");
  for (const key of ["fixtureConsistent", "canonicalAtomicSuite", "canonicalWorkflowSuite", "productHardGate", "wazaGate", "wazaSkillMatchesProduct", "wazaSourceMatchesProduct", "advisoryJudgeAdvisory"]) {
    if (typeof record.gates[key] !== "boolean") throw new Error(`History record.gates.${key} must be boolean`);
  }
  if (!Array.isArray(record.gates.groundingReviews) || !record.gates.groundingReviews.every((review) => {
    exactKeys(review, ["id", "status"], "History record grounding review");
    return review && requireSafeIdentifier(review.id, "History record grounding review.id") && isOneOf(review.status, ["APPROVED", "REJECTED", "REVIEW_REQUIRED"], "History record grounding review.status");
  })) {
    throw new Error("History record grounding-review status is invalid");
  }
  if (new Set(record.gates.groundingReviews.map((review) => review.id)).size !== record.gates.groundingReviews.length || !record.gates.groundingReviews.every((review) => MVP_EVAL_MANIFEST.workflowIds.includes(review.id))) {
    throw new Error("History record grounding-review IDs are invalid");
  }
  exactKeys(record.metrics, ["productRuntime", "skillLaboratory", "advisoryJudge"], "History record.metrics");
  exactKeys(record.metrics?.productRuntime, ["atomic", "workflows"], "History record product metrics");
  countMetrics(record.metrics.productRuntime.atomic, "History record atomic metrics");
  countMetrics(record.metrics.productRuntime.workflows, "History record workflow metrics");
  const product = record.metrics.productRuntime;
  if (record.gates.scope === "all" && record.gates.canonicalAtomicSuite) {
    if (product.atomic.total !== MVP_EVAL_MANIFEST.atomicCaseIds.length || new Set(product.atomic.failed).size !== product.atomic.failed.length || !product.atomic.failed.every((id) => MVP_EVAL_MANIFEST.atomicCaseIds.includes(id))) throw new Error("History record canonical atomic metrics are invalid");
  }
  if (record.gates.scope === "all" && record.gates.canonicalWorkflowSuite) {
    if (product.workflows.total !== MVP_EVAL_MANIFEST.workflowIds.length || new Set(product.workflows.failed).size !== product.workflows.failed.length || !product.workflows.failed.every((id) => MVP_EVAL_MANIFEST.workflowIds.includes(id))) throw new Error("History record canonical workflow metrics are invalid");
  }
  const derivedProductHardGate = record.gates.scope === "all" && record.gates.fixtureConsistent && record.gates.canonicalAtomicSuite && record.gates.canonicalWorkflowSuite
    && product.atomic.passed === product.atomic.total && product.workflows.passed === product.workflows.total;
  if (record.gates.productHardGate !== derivedProductHardGate) throw new Error("History record product hard gate is inconsistent");
  const waza = record.metrics?.skillLaboratory;
  exactKeys(waza, ["passed", "total", "failed", "errors", "skipped", "countsConsistent", "aggregateScore", "durationMs"], "History record Waza metrics");
  if (!waza || !Number.isInteger(waza.passed) || !Number.isInteger(waza.total) || !Number.isInteger(waza.errors) || !Number.isInteger(waza.skipped)
    || [waza.passed, waza.total, waza.errors, waza.skipped].some((count) => count < 0)
    || !Array.isArray(waza.failed) || !waza.failed.every((id) => {
      requireSafeIdentifier(id, "History record Waza failed ID");
      return true;
    }) || typeof waza.countsConsistent !== "boolean") throw new Error("History record Waza metrics are invalid");
  if (waza.countsConsistent && (waza.passed + waza.failed.length + waza.skipped !== waza.total || waza.errors > waza.failed.length)) throw new Error("History record Waza counts are inconsistent");
  const completeWazaPass = waza.countsConsistent && waza.total > 0 && waza.passed === waza.total && waza.failed.length === 0 && waza.errors === 0 && waza.skipped === 0;
  if ((record.gates.wazaStatus === "RECORDED") !== completeWazaPass) throw new Error("History record Waza status is inconsistent");
  numberOrNull(waza.aggregateScore, "History record Waza aggregateScore");
  numberOrNull(waza.durationMs, "History record Waza durationMs");
  const judge = record.metrics?.advisoryJudge;
  exactKeys(judge, ["status", "atomic", "workflows"], "History record advisory judge metrics");
  if (!judge) throw new Error("History record advisory judge metrics are invalid");
  isOneOf(judge.status, ["NOT_SUPPLIED", "RECORDED", "INVALID"], "History record advisory metrics.status");
  if (judge.status !== record.gates.advisoryJudgeStatus || judge.status !== record.provenance.advisoryJudge) throw new Error("History record advisory status is inconsistent");
  if (record.gates.advisoryJudgeAdvisory !== true) throw new Error("History record advisory judge must be advisory");
  judgeMetrics(judge.atomic, "History record advisory atomic metrics", judge.status);
  judgeMetrics(judge.workflows, "History record advisory workflow metrics", judge.status);
  exactKeys(record.evidence, ["scorecardSha256", "productSha256", "wazaSha256", "groundingReviewSha256", "advisoryJudgeSha256"], "History record.evidence");
  for (const key of ["scorecardSha256", "productSha256", "wazaSha256", "groundingReviewSha256"]) requireHash(record.evidence[key], `History record evidence.${key}`);
  if (record.evidence.advisoryJudgeSha256 !== null) requireHash(record.evidence.advisoryJudgeSha256, "History record evidence.advisoryJudgeSha256");
  const wazaGateProvenance = record.provenance.skillLaboratory;
  const exactWazaGateIds = wazaGateProvenance.gateTaskIds.length === WAZA_GATE_TASK_IDS.length
    && wazaGateProvenance.gateTaskIds.every((id, index) => id === WAZA_GATE_TASK_IDS[index]);
  const derivedWazaGate = record.gates.wazaStatus === "RECORDED" && waza.countsConsistent
    && wazaGateProvenance.schemaVersion === "1.2" && wazaGateProvenance.engine === "copilot-sdk"
    && wazaGateProvenance.runner === "scripts/waza_eval.sh" && wazaGateProvenance.wazaVersion === "0.38.3" && exactWazaGateIds;
  if (record.gates.wazaGate !== derivedWazaGate) throw new Error("History record Waza gate is inconsistent");
  if ((record.gates.advisoryJudgeStatus === "NOT_SUPPLIED") !== (record.evidence.advisoryJudgeSha256 === null)) throw new Error("History record advisory evidence binding is inconsistent");
  const ready = isReadyForBaseline(record);
  if ((record.gates.scorecardAcceptance === "READY_FOR_BASELINE") !== ready) throw new Error("History record readiness is inconsistent");
  requireHash(record.recordHash, "History record.recordHash");
  if (sha256Canonical(recordWithoutHash(record)) !== record.recordHash) throw new Error("History record hash does not match its contents");
  return structuredClone(record);
}

export function renderScorecardHistoryRecord(record) {
  const validated = validateScorecardHistoryRecord(record);
  const { productRuntime: product, skillLaboratory: waza, advisoryJudge: judge } = validated.metrics;
  const cell = (value) => String(value).replace(/[\r\n]+/g, " ").replaceAll("\\", "\\\\").replaceAll("|", "\\|");
  return `# CSA Workbench scorecard history\n\n| Field | Value |\n|---|---|\n| Run | ${cell(validated.runId)} |\n| Record SHA-256 | ${cell(validated.recordHash)} |\n| Source revision | ${cell(validated.sourceRevision)} |\n| Fixture | ${cell(validated.fixture.fixtureVersion)} / ${cell(validated.fixture.fixtureHash)} |\n| Skill | ${cell(validated.skill.name)} @ ${cell(validated.skill.sha256)} |\n| Product runtime | ${cell(validated.provenance.productRuntime.provenance)}; ${cell(validated.provenance.productRuntime.environment)} |\n| Waza runtime | ${cell(validated.provenance.skillLaboratory.provenance)}; ${cell(validated.provenance.skillLaboratory.engine ?? "NOT_RECORDED")} / ${cell(validated.provenance.skillLaboratory.model ?? "NOT_RECORDED")} |\n| Scorecard acceptance | ${cell(validated.gates.scorecardAcceptance)} |\n| Product hard gate | ${validated.gates.productHardGate ? "PASS" : "FAIL"} |\n| Atomic | ${product.atomic.passed}/${product.atomic.total} |\n| Workflow | ${product.workflows.passed}/${product.workflows.total} |\n| Waza | ${waza.passed}/${waza.total}; gate ${validated.gates.wazaGate ? "PASS" : "FAIL"} |\n| Advisory judge | ${cell(judge.status)}; ${judge.atomic.passed}/${judge.atomic.total} atomic, ${judge.workflows.passed}/${judge.workflows.total} workflow |\n\nThis sanitized history contains evidence digests, not transcripts, fixture paths, or product data.\n`;
}

function validateDecision(decision) {
  exactKeys(decision, DECISION_KEYS, "Baseline decision");
  if (decision.schemaVersion !== 1 || decision.kind !== "mvp-scorecard-baseline-decision") throw new Error("Baseline decision has an unsupported schema");
  const reviewer = normalizedHuman(decision.reviewer, "Baseline decision.reviewer");
  const rationale = normalizedHuman(decision.rationale, "Baseline decision.rationale");
  if (!/^[^.!?]+[.!?]$/.test(rationale)) throw new Error("Baseline decision.rationale must be one sentence");
  if (decision.decision !== "ACCEPTED") throw new Error("Baseline decision must be ACCEPTED");
  return { ...decision, recordHash: requireHash(decision.recordHash, "Baseline decision.recordHash"), reviewer, acceptedAt: requireRfc3339(decision.acceptedAt, "Baseline decision.acceptedAt"), rationale };
}

export function buildBaselineAcceptance(record, decision, scorecard, product, waza, groundingReview, judgeRecord = null) {
  const history = validateScorecardHistoryRecord(record);
  const rebuilt = buildScorecardHistoryRecord(scorecard, product, waza, groundingReview, judgeRecord);
  requireExactValue(history, rebuilt, "History record");
  const humanDecision = validateDecision(decision);
  if (history.gates.scorecardAcceptance !== "READY_FOR_BASELINE" || !isReadyForBaseline(history)) {
    throw new Error("History record is not READY_FOR_BASELINE");
  }
  if (humanDecision.recordHash !== history.recordHash) throw new Error("Baseline decision does not bind this history record");
  const acceptance = {
    schemaVersion: 1,
    kind: "mvp-scorecard-baseline-acceptance",
    recordHash: history.recordHash,
    runId: history.runId,
    sourceRevision: history.sourceRevision,
    fixture: structuredClone(history.fixture),
    skill: structuredClone(history.skill),
    evidence: structuredClone(history.evidence),
    reviewer: humanDecision.reviewer,
    acceptedAt: humanDecision.acceptedAt,
    decision: humanDecision.decision,
    rationale: humanDecision.rationale,
  };
  acceptance.acceptanceHash = sha256Canonical(acceptance);
  return validateBaselineAcceptance(acceptance, history);
}

export function validateBaselineAcceptance(acceptance, record) {
  exactKeys(acceptance, ACCEPTANCE_KEYS, "Baseline acceptance");
  if (acceptance.schemaVersion !== 1 || acceptance.kind !== "mvp-scorecard-baseline-acceptance" || acceptance.decision !== "ACCEPTED") {
    throw new Error("Baseline acceptance has an unsupported schema");
  }
  const history = validateScorecardHistoryRecord(record);
  if (history.gates.scorecardAcceptance !== "READY_FOR_BASELINE" || !isReadyForBaseline(history)) throw new Error("History record is not READY_FOR_BASELINE");
  requireHash(acceptance.recordHash, "Baseline acceptance.recordHash");
  requireHash(acceptance.acceptanceHash, "Baseline acceptance.acceptanceHash");
  requireRfc3339(acceptance.acceptedAt, "Baseline acceptance.acceptedAt");
  requireNormalizedHuman(acceptance.reviewer, "Baseline acceptance.reviewer");
  requireOneSentence(acceptance.rationale, "Baseline acceptance.rationale");
  exactKeys(acceptance.fixture, ["fixtureVersion", "fixtureHash"], "Baseline acceptance.fixture");
  exactKeys(acceptance.skill, ["name", "sha256"], "Baseline acceptance.skill");
  exactKeys(acceptance.evidence, ["scorecardSha256", "productSha256", "wazaSha256", "groundingReviewSha256", "advisoryJudgeSha256"], "Baseline acceptance.evidence");
  if (acceptance.recordHash !== history.recordHash) throw new Error("Baseline acceptance does not bind this history record");
  for (const key of ["runId", "sourceRevision", "fixture", "skill", "evidence"]) requireExactValue(acceptance[key], history[key], `Baseline acceptance.${key}`);
  if (sha256Canonical(acceptanceWithoutHash(acceptance)) !== acceptance.acceptanceHash) throw new Error("Baseline acceptance hash does not match its contents");
  return structuredClone(acceptance);
}

export function renderBaselineAcceptance(acceptance, record) {
  const validated = validateBaselineAcceptance(acceptance, record);
  const cell = (value) => String(value).replace(/[\r\n]+/g, " ").replaceAll("\\", "\\\\").replaceAll("|", "\\|");
  return `# CSA Workbench baseline acceptance\n\n| Field | Value |\n|---|---|\n| Run | ${cell(validated.runId)} |\n| History record SHA-256 | ${cell(validated.recordHash)} |\n| Acceptance SHA-256 | ${cell(validated.acceptanceHash)} |\n| Reviewer | ${cell(validated.reviewer)} |\n| Accepted at | ${cell(validated.acceptedAt)} |\n| Decision | ${cell(validated.decision)} |\n\n${cell(validated.rationale)}\n`;
}

function delta(baseline, candidate) {
  return { baseline, candidate, delta: candidate - baseline };
}

function regression(baseline, candidate, baselineGate = null, candidateGate = null) {
  const failedCount = (metrics) => Array.isArray(metrics.failed) ? metrics.failed.length : metrics.failed;
  return {
    passedDecreased: candidate.passed < baseline.passed,
    totalChanged: candidate.total !== baseline.total,
    failedIncreased: failedCount(candidate) > failedCount(baseline),
    gateRegressed: baselineGate === true && candidateGate === false,
  };
}

export function buildScorecardComparison(baselineRecord, baselineAcceptance, candidateRecord) {
  const baseline = validateScorecardHistoryRecord(baselineRecord);
  const candidate = validateScorecardHistoryRecord(candidateRecord);
  const acceptance = validateBaselineAcceptance(baselineAcceptance, baseline);
  if (baseline.runId === candidate.runId) throw new Error("Baseline and candidate run IDs must differ");
  requireExactValue(candidate.fixture, baseline.fixture, "Candidate fixture");
  requireExactValue(candidate.skill, baseline.skill, "Candidate skill");
  requireExactValue(candidate.provenance.productRuntime, baseline.provenance.productRuntime, "Candidate product provenance");
  requireExactValue(candidate.provenance.skillLaboratory, baseline.provenance.skillLaboratory, "Candidate Waza provenance");

  const baseProduct = baseline.metrics.productRuntime;
  const candidateProduct = candidate.metrics.productRuntime;
  const baseWaza = baseline.metrics.skillLaboratory;
  const candidateWaza = candidate.metrics.skillLaboratory;
  const atomicRegression = regression(baseProduct.atomic, candidateProduct.atomic, baseline.gates.productHardGate, candidate.gates.productHardGate);
  const workflowRegression = regression(baseProduct.workflows, candidateProduct.workflows, baseline.gates.productHardGate, candidate.gates.productHardGate);
  const wazaRegression = regression(baseWaza, candidateWaza, baseline.gates.wazaGate, candidate.gates.wazaGate);
  const judgeAtomic = regression(baseline.metrics.advisoryJudge.atomic, candidate.metrics.advisoryJudge.atomic);
  const judgeWorkflow = regression(baseline.metrics.advisoryJudge.workflows, candidate.metrics.advisoryJudge.workflows);
  const readinessRegressed = baseline.gates.scorecardAcceptance === "READY_FOR_BASELINE" && candidate.gates.scorecardAcceptance !== "READY_FOR_BASELINE";
  const blockingRegression = readinessRegressed || Object.values(atomicRegression).some(Boolean) || Object.values(workflowRegression).some(Boolean) || Object.values(wazaRegression).some(Boolean);
  const comparison = {
    schemaVersion: 1,
    kind: "mvp-scorecard-comparison",
    baseline: { runId: baseline.runId, recordHash: baseline.recordHash, acceptanceHash: acceptance.acceptanceHash, productHardGate: baseline.gates.productHardGate, wazaGate: baseline.gates.wazaGate },
    candidate: { runId: candidate.runId, recordHash: candidate.recordHash, readyForBaseline: candidate.gates.scorecardAcceptance === "READY_FOR_BASELINE", productHardGate: candidate.gates.productHardGate, wazaGate: candidate.gates.wazaGate },
    deltas: {
      atomic: { passed: delta(baseProduct.atomic.passed, candidateProduct.atomic.passed), total: delta(baseProduct.atomic.total, candidateProduct.atomic.total), failed: delta(baseProduct.atomic.failed.length, candidateProduct.atomic.failed.length) },
      workflows: { passed: delta(baseProduct.workflows.passed, candidateProduct.workflows.passed), total: delta(baseProduct.workflows.total, candidateProduct.workflows.total), failed: delta(baseProduct.workflows.failed.length, candidateProduct.workflows.failed.length) },
      waza: { passed: delta(baseWaza.passed, candidateWaza.passed), total: delta(baseWaza.total, candidateWaza.total), failed: delta(baseWaza.failed.length, candidateWaza.failed.length), errors: delta(baseWaza.errors, candidateWaza.errors), skipped: delta(baseWaza.skipped, candidateWaza.skipped), aggregateScore: baseWaza.aggregateScore === null || candidateWaza.aggregateScore === null ? null : delta(baseWaza.aggregateScore, candidateWaza.aggregateScore), durationMs: baseWaza.durationMs === null || candidateWaza.durationMs === null ? null : delta(baseWaza.durationMs, candidateWaza.durationMs) },
      advisoryJudge: {
        advisory: true,
        atomic: { passed: delta(baseline.metrics.advisoryJudge.atomic.passed, candidate.metrics.advisoryJudge.atomic.passed), failed: delta(baseline.metrics.advisoryJudge.atomic.failed, candidate.metrics.advisoryJudge.atomic.failed), unknown: delta(baseline.metrics.advisoryJudge.atomic.unknown, candidate.metrics.advisoryJudge.atomic.unknown) },
        workflows: { passed: delta(baseline.metrics.advisoryJudge.workflows.passed, candidate.metrics.advisoryJudge.workflows.passed), failed: delta(baseline.metrics.advisoryJudge.workflows.failed, candidate.metrics.advisoryJudge.workflows.failed), unknown: delta(baseline.metrics.advisoryJudge.workflows.unknown, candidate.metrics.advisoryJudge.workflows.unknown) },
      },
    },
    regressions: {
      atomic: atomicRegression,
      workflows: workflowRegression,
      waza: wazaRegression,
      advisoryJudge: { advisory: true, atomic: judgeAtomic, workflows: judgeWorkflow },
      readinessRegressed,
      blockingRegression,
      note: "Advisory judge deltas are reported but never change blocking regression or baseline acceptance.",
    },
  };
  comparison.comparisonHash = sha256Canonical(comparison);
  return validateScorecardComparison(comparison);
}

export function validateScorecardComparison(comparison) {
  exactKeys(comparison, COMPARISON_KEYS, "Scorecard comparison");
  if (comparison.schemaVersion !== 1 || comparison.kind !== "mvp-scorecard-comparison") throw new Error("Scorecard comparison has an unsupported schema");
  exactKeys(comparison.baseline, ["runId", "recordHash", "acceptanceHash", "productHardGate", "wazaGate"], "Scorecard comparison.baseline");
  exactKeys(comparison.candidate, ["runId", "recordHash", "readyForBaseline", "productHardGate", "wazaGate"], "Scorecard comparison.candidate");
  requireRunId(comparison.baseline.runId, "Baseline runId");
  requireRunId(comparison.candidate?.runId, "Candidate runId");
  requireHash(comparison.baseline?.recordHash, "Baseline recordHash");
  requireHash(comparison.baseline?.acceptanceHash, "Baseline acceptanceHash");
  requireHash(comparison.candidate?.recordHash, "Candidate recordHash");
  if (![comparison.baseline.productHardGate, comparison.baseline.wazaGate, comparison.candidate.readyForBaseline, comparison.candidate.productHardGate, comparison.candidate.wazaGate].every((value) => typeof value === "boolean")) throw new Error("Scorecard comparison candidate readiness is invalid");
  if (!comparison.baseline.productHardGate || !comparison.baseline.wazaGate) throw new Error("Scorecard comparison baseline must be ready");
  if (comparison.candidate.readyForBaseline && (!comparison.candidate.productHardGate || !comparison.candidate.wazaGate)) throw new Error("Scorecard comparison candidate readiness is inconsistent");
  exactKeys(comparison.deltas, ["atomic", "workflows", "waza", "advisoryJudge"], "Scorecard comparison.deltas");
  const validateDelta = (value, label) => {
    exactKeys(value, ["baseline", "candidate", "delta"], label);
    if (![value.baseline, value.candidate, value.delta].every((item) => typeof item === "number" && Number.isFinite(item)) || value.delta !== value.candidate - value.baseline) throw new Error(`${label} is invalid`);
  };
  for (const [name, keys] of [["atomic", ["passed", "total", "failed"]], ["workflows", ["passed", "total", "failed"]]]) {
    exactKeys(comparison.deltas[name], keys, `Scorecard comparison.deltas.${name}`);
    for (const key of keys) validateDelta(comparison.deltas[name][key], `Scorecard comparison.deltas.${name}.${key}`);
  }
  exactKeys(comparison.deltas.waza, ["passed", "total", "failed", "errors", "skipped", "aggregateScore", "durationMs"], "Scorecard comparison.deltas.waza");
  for (const key of ["passed", "total", "failed", "errors", "skipped"]) validateDelta(comparison.deltas.waza[key], `Scorecard comparison.deltas.waza.${key}`);
  for (const key of ["aggregateScore", "durationMs"]) {
    if (comparison.deltas.waza[key] !== null) validateDelta(comparison.deltas.waza[key], `Scorecard comparison.deltas.waza.${key}`);
  }
  exactKeys(comparison.deltas.advisoryJudge, ["advisory", "atomic", "workflows"], "Scorecard comparison.deltas.advisoryJudge");
  if (comparison.deltas.advisoryJudge.advisory !== true) throw new Error("Scorecard comparison must label judge deltas advisory");
  for (const name of ["atomic", "workflows"]) {
    exactKeys(comparison.deltas.advisoryJudge[name], ["passed", "failed", "unknown"], `Scorecard comparison advisory ${name} deltas`);
    for (const key of ["passed", "failed", "unknown"]) validateDelta(comparison.deltas.advisoryJudge[name][key], `Scorecard comparison advisory ${name}.${key}`);
  }
  exactKeys(comparison.regressions, ["atomic", "workflows", "waza", "advisoryJudge", "readinessRegressed", "blockingRegression", "note"], "Scorecard comparison.regressions");
  const validateRegression = (value, deltaGroup, label, advisory = false) => {
    exactKeys(value, ["passedDecreased", "totalChanged", "failedIncreased", "gateRegressed"], label);
    if (!Object.values(value).every((item) => typeof item === "boolean")) throw new Error(`${label} is invalid`);
    if (value.passedDecreased !== (deltaGroup.passed.delta < 0) || value.totalChanged !== (deltaGroup.total ? deltaGroup.total.delta !== 0 : false) || value.failedIncreased !== (deltaGroup.failed.delta > 0) || advisory && value.gateRegressed !== false) {
      throw new Error(`${label} does not match its deltas`);
    }
  };
  for (const key of ["atomic", "workflows", "waza"]) validateRegression(comparison.regressions[key], comparison.deltas[key], `Scorecard comparison.regressions.${key}`);
  for (const key of ["atomic", "workflows"]) {
    if (comparison.regressions[key].gateRegressed !== (comparison.baseline.productHardGate && !comparison.candidate.productHardGate)) throw new Error(`Scorecard comparison.regressions.${key} gate is invalid`);
  }
  if (comparison.regressions.waza.gateRegressed !== (comparison.baseline.wazaGate && !comparison.candidate.wazaGate)) throw new Error("Scorecard comparison.regressions.waza gate is invalid");
  exactKeys(comparison.regressions.advisoryJudge, ["advisory", "atomic", "workflows"], "Scorecard comparison advisory regressions");
  if (comparison.regressions.advisoryJudge.advisory !== true) throw new Error("Scorecard comparison must label judge regressions advisory");
  for (const key of ["atomic", "workflows"]) validateRegression(comparison.regressions.advisoryJudge[key], comparison.deltas.advisoryJudge[key], `Scorecard comparison advisory ${key} regressions`, true);
  if (typeof comparison.regressions.readinessRegressed !== "boolean" || typeof comparison.regressions.blockingRegression !== "boolean" || typeof comparison.regressions.note !== "string") throw new Error("Scorecard comparison status is invalid");
  if (comparison.regressions.readinessRegressed !== !comparison.candidate.readyForBaseline) throw new Error("Scorecard comparison readiness regression is invalid");
  const expectedBlocking = comparison.regressions.readinessRegressed || ["atomic", "workflows", "waza"].some((key) => Object.values(comparison.regressions[key]).some(Boolean));
  if (comparison.regressions.blockingRegression !== expectedBlocking) throw new Error("Scorecard comparison blocking regression is invalid");
  requireHash(comparison.comparisonHash, "Scorecard comparison.comparisonHash");
  if (sha256Canonical(comparisonWithoutHash(comparison)) !== comparison.comparisonHash) throw new Error("Scorecard comparison hash does not match its contents");
  return structuredClone(comparison);
}

export function renderScorecardComparison(comparison) {
  const validated = validateScorecardComparison(comparison);
  const line = (name, value) => `| ${name} | ${value.baseline} | ${value.candidate} | ${value.delta >= 0 ? "+" : ""}${value.delta} |`;
  return `# CSA Workbench scorecard comparison\n\n| Metric | Baseline | Candidate | Delta |\n|---|---:|---:|---:|\n${line("Atomic passed", validated.deltas.atomic.passed)}\n${line("Workflow passed", validated.deltas.workflows.passed)}\n${line("Waza passed", validated.deltas.waza.passed)}\n\n- Blocking regression: ${validated.regressions.blockingRegression ? "YES" : "NO"}
- Advisory judge deltas are non-gating and cannot alter baseline acceptance.\n`;
}

function historyRoot(root) {
  if (typeof root !== "string" || !root.trim()) throw new Error("History root is required");
  mkdirSync(root, { recursive: true });
  const realRoot = realpathSync(root);
  if (!lstatSync(realRoot).isDirectory()) throw new Error("History root must be a directory");
  return realRoot;
}

function safeOutputPath(root, name) {
  if (basename(name) !== name || name.includes("..")) throw new Error("History output name is unsafe");
  const path = resolve(root, name);
  if (relative(root, path).startsWith("..") || relative(root, path) === "") throw new Error("History output path escapes its root");
  return path;
}

function writeNewPair(root, prefix, json, markdown) {
  const jsonPath = safeOutputPath(root, `${prefix}.json`);
  const markdownPath = safeOutputPath(root, `${prefix}.md`);
  if (existsSync(jsonPath) || existsSync(markdownPath)) throw new Error("Immutable history output already exists");
  let jsonFd;
  let markdownFd;
  let jsonCreated = false;
  let markdownCreated = false;
  let jsonIdentity;
  let markdownIdentity;
  try {
    jsonFd = openSync(jsonPath, "wx");
    jsonCreated = true;
    jsonIdentity = fstatSync(jsonFd);
    markdownFd = openSync(markdownPath, "wx");
    markdownCreated = true;
    markdownIdentity = fstatSync(markdownFd);
    writeFileSync(jsonFd, `${JSON.stringify(json, null, 2)}\n`);
    writeFileSync(markdownFd, markdown);
  } catch (error) {
    if (jsonFd !== undefined) closeSync(jsonFd);
    if (markdownFd !== undefined) closeSync(markdownFd);
    const unlinkOwned = (path, identity) => {
      if (!identity) return;
      try {
        const current = lstatSync(path);
        if (current.dev === identity.dev && current.ino === identity.ino) unlinkSync(path);
      } catch { /* The path disappeared or was replaced before cleanup. */ }
    };
    if (jsonCreated) unlinkOwned(jsonPath, jsonIdentity);
    if (markdownCreated) unlinkOwned(markdownPath, markdownIdentity);
    throw error;
  }
  closeSync(jsonFd);
  closeSync(markdownFd);
  return { json: jsonPath, markdown: markdownPath };
}

export function writeHistoryRecord(historyRootPath, record) {
  const history = validateScorecardHistoryRecord(record);
  return writeNewPair(historyRoot(historyRootPath), `${history.runId}.scorecard-history`, history, renderScorecardHistoryRecord(history));
}

export function writeBaselineAcceptance(historyRootPath, acceptance, record) {
  const validated = validateBaselineAcceptance(acceptance, record);
  return writeNewPair(historyRoot(historyRootPath), `${validated.runId}.baseline-acceptance`, validated, renderBaselineAcceptance(validated, record));
}

export function writeScorecardComparison(historyRootPath, comparison) {
  const validated = validateScorecardComparison(comparison);
  return writeNewPair(historyRoot(historyRootPath), `${validated.baseline.runId}--${validated.candidate.runId}.scorecard-comparison`, validated, renderScorecardComparison(validated));
}

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function usage() {
  throw new Error("Usage: node scripts/mvp_scorecard_history.mjs <record|accept|compare> ...");
}

function main(argv) {
  const [command, ...args] = argv;
  if (command === "record") {
    const [scorecardPath, productPath, wazaPath, groundingPath, root, judgePath] = args;
    if (!scorecardPath || !productPath || !wazaPath || !groundingPath || !root || args.length > 6) usage();
    const record = buildScorecardHistoryRecord(readJson(scorecardPath), readJson(productPath), readJson(wazaPath), readJson(groundingPath), judgePath ? readJson(judgePath) : null);
    console.log(JSON.stringify(writeHistoryRecord(root, record), null, 2));
    return;
  }
  if (command === "accept") {
    const [recordPath, decisionPath, scorecardPath, productPath, wazaPath, groundingPath, root, judgePath] = args;
    if (!recordPath || !decisionPath || !scorecardPath || !productPath || !wazaPath || !groundingPath || !root || args.length < 7 || args.length > 8) usage();
    const record = readJson(recordPath);
    const acceptance = buildBaselineAcceptance(record, readJson(decisionPath), readJson(scorecardPath), readJson(productPath), readJson(wazaPath), readJson(groundingPath), judgePath ? readJson(judgePath) : null);
    console.log(JSON.stringify(writeBaselineAcceptance(root, acceptance, record), null, 2));
    return;
  }
  if (command === "compare") {
    const [baselinePath, acceptancePath, candidatePath, root] = args;
    if (!baselinePath || !acceptancePath || !candidatePath || !root || args.length !== 4) usage();
    const comparison = buildScorecardComparison(readJson(baselinePath), readJson(acceptancePath), readJson(candidatePath));
    console.log(JSON.stringify(writeScorecardComparison(root, comparison), null, 2));
    return;
  }
  usage();
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname)) main(process.argv.slice(2));
