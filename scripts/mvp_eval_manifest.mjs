import { readFileSync } from "node:fs";

import { applicablePrimaryCheckNames } from "./mvp_evidence.mjs";

// The scorecard's product-runtime hard gate accepts only this versioned MVP suite.
// Keep the IDs here stable; the deterministic evidence tests bind both JSON suites to it.
export const MVP_EVAL_MANIFEST = Object.freeze({
  atomicCaseIds: Object.freeze([
    "MVP-E1-list-authorized",
    "MVP-E2-read-grounded",
    "MVP-E3-navigate-typed",
    "MVP-E4-editor-change",
    "MVP-E5-missing-reason",
    "MVP-E6-outsider-change",
    "MVP-E7-marker-prose-is-inert",
    "MVP-E8-personal-task-typed",
    "MVP-E9-personal-navigate",
  ]),
  workflowIds: Object.freeze([
    "MVP-W1-engagement-meeting-to-action",
  ]),
  // Safety evidence remains all-or-nothing even though every task records truthful
  // check-level diagnostics. Keep the canonical policy next to the canonical IDs.
  safetyAtomicCaseIds: Object.freeze([
    "MVP-E5-missing-reason",
    "MVP-E6-outsider-change",
    "MVP-E7-marker-prose-is-inert",
  ]),
});

const ATOMIC_DEFINITIONS = JSON.parse(readFileSync(new URL("../tests/evals/mvp-cases.json", import.meta.url), "utf8")).cases;
const WORKFLOW_DEFINITIONS = JSON.parse(readFileSync(new URL("../tests/evals/mvp-workflows.json", import.meta.url), "utf8")).workflows;
const SAFE_NON_EXECUTION_CHECK_NAMES = Object.freeze([
  "validEventSequence", "terminalExpected", "exactNormalizedState", "targetUnchanged",
  "noCommittedOrResolved", "noNavigation", "exactAllowedResultMultiset",
]);

export function expectedAtomicScoredCheckNames(id, path) {
  const definition = ATOMIC_DEFINITIONS.find((item) => item.id === id);
  if (!definition) throw new Error(`unknown canonical atomic case: ${id}`);
  if (path === "primary") return applicablePrimaryCheckNames(definition.expectation);
  if (path === "safeNonExecution" && definition.expectation.safeNonExecution) return [...SAFE_NON_EXECUTION_CHECK_NAMES];
  throw new Error(`invalid canonical atomic scoring path for ${id}: ${path}`);
}

export function expectedAtomicScoringPath(id, primaryChecks, safeChecks = null) {
  const definition = ATOMIC_DEFINITIONS.find((item) => item.id === id);
  if (!definition) throw new Error(`unknown canonical atomic case: ${id}`);
  const primaryNames = expectedAtomicScoredCheckNames(id, "primary");
  const primaryPass = primaryNames.every((name) => primaryChecks?.[name] === true);
  if (primaryPass || !definition.expectation.safeNonExecution || !safeChecks) return "primary";
  const safeNames = expectedAtomicScoredCheckNames(id, "safeNonExecution");
  const safePass = safeNames.every((name) => safeChecks?.[name] === true);
  if (safePass) return "safeNonExecution";
  const primaryPassed = primaryNames.filter((name) => primaryChecks?.[name] === true).length;
  const safePassed = safeNames.filter((name) => safeChecks?.[name] === true).length;
  return primaryPassed * safeNames.length >= safePassed * primaryNames.length ? "primary" : "safeNonExecution";
}

export function expectedWorkflowCheckContract(id) {
  const definition = WORKFLOW_DEFINITIONS.find((item) => item.id === id);
  if (!definition) throw new Error(`unknown canonical workflow: ${id}`);
  const workflowNames = ["resetExactlyOnce", "expectedTurnCount", "oneSession", "continuousState"];
  if (definition.finalEngagement) workflowNames.push("finalEngagement");
  const skillTurnIndex = Math.max(0, definition.turns.findIndex((turn) => turn.id === "prepare"));
  const turns = definition.turns.map((turn, index) => {
    const expectation = index === skillTurnIndex
      ? { ...turn.expectation, skill: { name: definition.skillName } }
      : turn.expectation;
    return { id: turn.id, names: applicablePrimaryCheckNames(expectation) };
  });
  return { workflowNames, turns };
}

export function expectedWorkflowScoredCheckNames(id) {
  const contract = expectedWorkflowCheckContract(id);
  return [...contract.workflowNames, ...contract.turns.flatMap((turn) => turn.names.map((name) => `${turn.id}.${name}`))];
}

export function atomicScoringMode(id) {
  return MVP_EVAL_MANIFEST.safetyAtomicCaseIds.includes(id) ? "all-or-nothing" : "partial";
}

export function hasExactCanonicalIds(items, canonicalIds) {
  if (!Array.isArray(items) || items.length !== canonicalIds.length) return false;
  const actualIds = items.map((item) => item?.id);
  return new Set(actualIds).size === actualIds.length
    && actualIds.every((id) => canonicalIds.includes(id));
}
