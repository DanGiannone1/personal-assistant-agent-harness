import { readFileSync, writeFileSync } from "node:fs";
import { buildMvpScorecard, renderMvpScorecard } from "./mvp_scorecard.mjs";

const [productPath, wazaPath, outputPrefix, groundingReviewPath, judgeRecordPath] = process.argv.slice(2);
if (!productPath || !wazaPath || !outputPrefix) {
  throw new Error("Usage: node scripts/mvp_scorecard_merge.mjs <product-results.json> <waza-results.json> <output-prefix> [grounding-review.json] [judge-record.json]");
}
const product = JSON.parse(readFileSync(productPath, "utf8"));
const waza = JSON.parse(readFileSync(wazaPath, "utf8"));
const groundingReview = groundingReviewPath ? JSON.parse(readFileSync(groundingReviewPath, "utf8")) : null;
const judgeRecord = judgeRecordPath ? JSON.parse(readFileSync(judgeRecordPath, "utf8")) : null;
const scorecard = buildMvpScorecard(product, waza, groundingReview, judgeRecord);
writeFileSync(`${outputPrefix}.json`, JSON.stringify(scorecard, null, 2));
writeFileSync(`${outputPrefix}.md`, renderMvpScorecard(scorecard));
console.log(JSON.stringify({ json: `${outputPrefix}.json`, markdown: `${outputPrefix}.md`, acceptance: scorecard.acceptance.status }, null, 2));
