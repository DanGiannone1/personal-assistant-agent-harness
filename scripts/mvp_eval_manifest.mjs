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
  ]),
  workflowIds: Object.freeze([
    "MVP-W1-engagement-meeting-to-action",
  ]),
});

export function hasExactCanonicalIds(items, canonicalIds) {
  if (!Array.isArray(items) || items.length !== canonicalIds.length) return false;
  const actualIds = items.map((item) => item?.id);
  return new Set(actualIds).size === actualIds.length
    && actualIds.every((id) => canonicalIds.includes(id));
}
