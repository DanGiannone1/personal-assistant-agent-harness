import { readFileSync } from "node:fs";

import { MVP_EVAL_MANIFEST, hasExactCanonicalIds } from "./mvp_eval_manifest.mjs";

const RUBRIC_PATH = new URL("../tests/evals/judge-rubrics.json", import.meta.url);
const BINDING_FIELDS = Object.freeze([
  "productRunId",
  "sourceRevision",
  "fixtureVersion",
  "fixtureHash",
  "skillSha256",
]);
const DIMENSIONS = Object.freeze(["accuracy", "leakage", "tone"]);

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requireObject(value, label) {
  if (!isObject(value)) throw new Error(`${label} must be an object`);
  return value;
}

function requireExactKeys(value, keys, label) {
  const actual = Object.keys(requireObject(value, label));
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key))) {
    throw new Error(`${label} contains unknown or missing fields`);
  }
}

function requireString(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} must be a nonempty string`);
  return value;
}

function requireTrimmedString(value, label) {
  return requireString(value, label).trim();
}

function requireExactIds(entries, ids, idKey, label) {
  if (!Array.isArray(entries) || entries.length !== ids.length) {
    throw new Error(`${label} must contain exactly the canonical IDs`);
  }
  const actual = entries.map((entry) => requireObject(entry, `${label} entry`)[idKey]);
  if (new Set(actual).size !== actual.length || actual.some((id) => !ids.includes(id))) {
    throw new Error(`${label} must contain exactly the canonical IDs`);
  }
}

function requireQuestions(entry, idKey, label) {
  requireExactKeys(entry, [idKey, "questions"], label);
  const id = requireString(entry[idKey], `${label}.${idKey}`);
  if (!Array.isArray(entry.questions) || entry.questions.length !== DIMENSIONS.length) {
    throw new Error(`${label}.${id} must contain exactly one question for each dimension`);
  }
  const dimensions = new Set();
  const questions = entry.questions.map((item, index) => {
    const questionLabel = `${label}.${id}.questions[${index}]`;
    requireExactKeys(item, ["dimension", "question"], questionLabel);
    const dimension = requireString(item.dimension, `${questionLabel}.dimension`);
    if (!DIMENSIONS.includes(dimension) || dimensions.has(dimension)) {
      throw new Error(`${questionLabel}.dimension must be a unique supported dimension`);
    }
    dimensions.add(dimension);
    return { dimension, question: requireString(item.question, `${questionLabel}.question`) };
  });
  if (dimensions.size !== DIMENSIONS.length) throw new Error(`${label}.${id} must cover every dimension`);
  return { id, questions };
}

function requireOneSentence(reason, label) {
  const normalized = requireTrimmedString(reason, label);
  if (/\r|\n/.test(normalized) || !/^[^.!?]+[.!?]$/.test(normalized)) {
    throw new Error(`${label} must be one sentence ending in punctuation`);
  }
  return normalized;
}

function requireRfc3339(value, label) {
  requireString(value, label);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match || Number.isNaN(Date.parse(value))) {
    throw new Error(`${label} must be a valid RFC3339 timestamp`);
  }
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const calendar = new Date(Date.UTC(year, month - 1, day));
  if (month < 1 || month > 12 || day < 1 || calendar.getUTCFullYear() !== year
    || calendar.getUTCMonth() !== month - 1 || calendar.getUTCDate() !== day
    || hour > 23 || minute > 59 || second > 59) {
    throw new Error(`${label} must be a valid RFC3339 timestamp`);
  }
}

function validateJudgeProvenance(judge, productReport) {
  requireObject(judge, "Judge record.judge");
  if (judge.kind === "human") {
    requireExactKeys(judge, ["kind", "reviewer"], "Judge record.judge");
    return { kind: "human", reviewer: requireTrimmedString(judge.reviewer, "Judge record.judge.reviewer") };
  }
  if (judge.kind === "model") {
    requireExactKeys(judge, ["kind", "provider", "model"], "Judge record.judge");
    const provenance = {
      kind: "model",
      provider: requireTrimmedString(judge.provider, "Judge record.judge.provider"),
      model: requireTrimmedString(judge.model, "Judge record.judge.model"),
    };
    const productModel = typeof productReport.model === "string" && productReport.model.trim()
      ? productReport.model.trim()
      : null;
    if (productModel && provenance.model === productModel) throw new Error("Judge record model must differ from the product report model");
    return provenance;
  }
  throw new Error("Judge record.judge.kind must be human or model");
}

function requireCanonicalProductSuite(productReport) {
  const fixtureVersion = productReport.fixture?.fixtureVersion;
  const fixtureHash = productReport.fixture?.fixtureHash;
  const evidence = [...(productReport.results ?? []), ...(productReport.workflows ?? [])];
  if (productReport.scope !== "all"
    || !hasExactCanonicalIds(productReport.results ?? [], MVP_EVAL_MANIFEST.atomicCaseIds)
    || !hasExactCanonicalIds(productReport.workflows ?? [], MVP_EVAL_MANIFEST.workflowIds)
    || typeof fixtureVersion !== "string" || !fixtureVersion
    || typeof fixtureHash !== "string" || !fixtureHash
    || !evidence.every((item) => item.fixture?.fixtureVersion === fixtureVersion && item.fixture?.fixtureHash === fixtureHash)) {
    throw new Error("Judge records require the all-scope canonical suites with fixture-consistent evidence");
  }
}

export function expectedJudgeBinding(productReport) {
  return {
    productRunId: productReport.runId,
    sourceRevision: productReport.sourceRevision,
    fixtureVersion: productReport.fixture?.fixtureVersion,
    fixtureHash: productReport.fixture?.fixtureHash,
    skillSha256: productReport.skill?.sha256,
  };
}

export function loadMvpJudgeRubric() {
  return JSON.parse(readFileSync(RUBRIC_PATH, "utf8"));
}

export function validateMvpJudgeRubric(rubric = loadMvpJudgeRubric()) {
  requireExactKeys(rubric, ["version", "notes", "rubrics", "workflows"], "Judge rubric");
  if (rubric.version !== 1) throw new Error("Judge rubric version must be 1");
  requireString(rubric.notes, "Judge rubric.notes");
  requireExactIds(rubric.rubrics, MVP_EVAL_MANIFEST.atomicCaseIds, "caseId", "Judge atomic rubrics");
  requireExactIds(rubric.workflows, MVP_EVAL_MANIFEST.workflowIds, "workflowId", "Judge workflow rubrics");
  return {
    version: rubric.version,
    atomic: rubric.rubrics.map((entry) => requireQuestions(entry, "caseId", "Judge atomic rubric")),
    workflows: rubric.workflows.map((entry) => requireQuestions(entry, "workflowId", "Judge workflow rubric")),
  };
}

function validateJudgments(judgments, rubricEntries, idKey, label) {
  if (!Array.isArray(judgments)) throw new Error(`${label} must be an array`);
  const expected = new Map();
  for (const entry of rubricEntries) {
    for (const { dimension, question } of entry.questions) expected.set(`${entry.id}\u0000${dimension}\u0000${question}`, true);
  }
  if (judgments.length !== expected.size) throw new Error(`${label} must answer every expected question exactly once`);
  const seen = new Set();
  return judgments.map((judgment, index) => {
    const itemLabel = `${label}[${index}]`;
    requireExactKeys(judgment, [idKey, "dimension", "question", "reason", "verdict"], itemLabel);
    const id = requireString(judgment[idKey], `${itemLabel}.${idKey}`);
    const dimension = requireString(judgment.dimension, `${itemLabel}.dimension`);
    const question = requireString(judgment.question, `${itemLabel}.question`);
    const key = `${id}\u0000${dimension}\u0000${question}`;
    if (!expected.has(key)) throw new Error(`${itemLabel} names an unknown case, workflow, dimension, or question`);
    if (seen.has(key)) throw new Error(`${itemLabel} duplicates a question`);
    if (!["pass", "fail", "unknown"].includes(judgment.verdict)) {
      throw new Error(`${itemLabel}.verdict must be pass, fail, or unknown`);
    }
    const reason = requireOneSentence(judgment.reason, `${itemLabel}.reason`);
    seen.add(key);
    return { [idKey]: id, dimension, question, reason, verdict: judgment.verdict };
  });
}

export function validateMvpJudgeRecord(judgeRecord, productReport, rubric = loadMvpJudgeRubric()) {
  requireExactKeys(judgeRecord, [
    "schemaVersion", "kind", ...BINDING_FIELDS, "rubricVersion", "judge", "judgedAt", "atomicJudgments", "workflowJudgments",
  ], "Judge record");
  if (judgeRecord.schemaVersion !== 1 || judgeRecord.kind !== "mvp-advisory-judge-record") {
    throw new Error("Judge record must be schemaVersion 1 and kind mvp-advisory-judge-record");
  }
  requireCanonicalProductSuite(productReport);
  const expected = expectedJudgeBinding(productReport);
  for (const field of BINDING_FIELDS) {
    requireString(judgeRecord[field], `Judge record.${field}`);
    if (judgeRecord[field] !== expected[field]) throw new Error(`Judge record ${field} does not match the product report`);
  }
  const canonicalRubric = validateMvpJudgeRubric(rubric);
  if (judgeRecord.rubricVersion !== canonicalRubric.version) throw new Error("Judge record rubricVersion does not match the rubric");
  const judge = validateJudgeProvenance(judgeRecord.judge, productReport);
  requireRfc3339(judgeRecord.judgedAt, "Judge record.judgedAt");
  return {
    binding: expected,
    rubricVersion: canonicalRubric.version,
    judge,
    judgedAt: judgeRecord.judgedAt,
    atomicJudgments: validateJudgments(judgeRecord.atomicJudgments, canonicalRubric.atomic, "caseId", "Judge atomic judgments"),
    workflowJudgments: validateJudgments(judgeRecord.workflowJudgments, canonicalRubric.workflows, "workflowId", "Judge workflow judgments"),
  };
}

function verdictCounts(judgments, total) {
  const count = (items) => ({
    passed: items.filter((judgment) => judgment.verdict === "pass").length,
    failed: items.filter((judgment) => judgment.verdict === "fail").length,
    unknown: items.filter((judgment) => judgment.verdict === "unknown").length,
    total: items.length,
  });
  return {
    ...count(judgments),
    total,
    dimensions: Object.fromEntries(DIMENSIONS.map((dimension) => [dimension, count(judgments.filter((judgment) => judgment.dimension === dimension))])),
  };
}

function observedBinding(judgeRecord) {
  if (!isObject(judgeRecord)) return null;
  return Object.fromEntries(BINDING_FIELDS.map((field) => [field, judgeRecord[field] ?? null]));
}

function suppliedProvenance(judgeRecord) {
  if (!isObject(judgeRecord)) return null;
  return {
    rubricVersion: judgeRecord.rubricVersion ?? null,
    judge: isObject(judgeRecord.judge) ? { ...judgeRecord.judge } : null,
    judgedAt: judgeRecord.judgedAt ?? null,
  };
}

export function summarizeMvpJudge(judgeRecord, productReport, rubric = loadMvpJudgeRubric()) {
  const expected = expectedJudgeBinding(productReport);
  const canonicalRubric = validateMvpJudgeRubric(rubric);
  const totalAtomic = canonicalRubric.atomic.reduce((total, entry) => total + entry.questions.length, 0);
  const totalWorkflows = canonicalRubric.workflows.reduce((total, entry) => total + entry.questions.length, 0);
  if (!judgeRecord) {
    return {
      status: "NOT_SUPPLIED",
      advisory: true,
      binding: { status: "NOT_SUPPLIED", expected },
      provenance: null,
      atomic: verdictCounts([], totalAtomic),
      workflows: verdictCounts([], totalWorkflows),
      note: "Judge evidence is advisory only and cannot override deterministic product or Waza gates.",
    };
  }
  try {
    const validated = validateMvpJudgeRecord(judgeRecord, productReport, rubric);
    return {
      status: "RECORDED",
      advisory: true,
      binding: { status: "MATCHED", expected },
      provenance: { rubricVersion: validated.rubricVersion, judge: validated.judge, judgedAt: validated.judgedAt },
      atomic: { ...verdictCounts(validated.atomicJudgments, totalAtomic), judgments: validated.atomicJudgments },
      workflows: { ...verdictCounts(validated.workflowJudgments, totalWorkflows), judgments: validated.workflowJudgments },
      note: "Judge evidence is advisory only and cannot override deterministic product or Waza gates.",
    };
  } catch (error) {
    const observed = observedBinding(judgeRecord);
    const mismatched = observed && BINDING_FIELDS.some((field) => observed[field] !== null && observed[field] !== expected[field]);
    return {
      status: "INVALID",
      advisory: true,
      binding: { status: mismatched ? "MISMATCHED" : "INVALID", expected, observed },
      provenance: suppliedProvenance(judgeRecord),
      atomic: verdictCounts([], totalAtomic),
      workflows: verdictCounts([], totalWorkflows),
      error: error.message,
      note: "Judge evidence is advisory only and cannot override deterministic product or Waza gates.",
    };
  }
}
