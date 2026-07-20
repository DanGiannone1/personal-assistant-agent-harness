import { readFileSync, writeFileSync } from "node:fs";
import { buildMvpScorecard, renderMvpScorecard } from "./mvp_scorecard.mjs";

const [productPath, wazaPath, outputPrefix, groundingReviewPath] = process.argv.slice(2);
if (!productPath || !wazaPath || !outputPrefix) {
  throw new Error("Usage: node scripts/mvp_scorecard_merge.mjs <product-results.json> <waza-results.json> <output-prefix> [grounding-review.json]");
}
const product = JSON.parse(readFileSync(productPath, "utf8"));
const waza = JSON.parse(readFileSync(wazaPath, "utf8"));
const groundingReview = groundingReviewPath ? JSON.parse(readFileSync(groundingReviewPath, "utf8")) : null;
const scorecard = buildMvpScorecard(product, waza, groundingReview);
writeFileSync(`${outputPrefix}.json`, JSON.stringify(scorecard, null, 2));
writeFileSync(`${outputPrefix}.md`, renderMvpScorecard(scorecard));
console.log(JSON.stringify({ json: `${outputPrefix}.json`, markdown: `${outputPrefix}.md`, acceptance: scorecard.acceptance.status }, null, 2));
