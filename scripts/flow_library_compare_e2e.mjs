// Save to Library — Part 3: upload a SESSION file (not promoted), ask the agent to
// compare it against the persistent Library. Proves both tiers working together:
// direct read of the session file + RAG over the Library.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const APP = "http://localhost:3000", API = "http://localhost:8000";
const PDFS = "/tmp/claude-1000/-home-dan-projects-flow/8e6a7271-9259-47cb-9c77-d2d465db6c7f/scratchpad/pdfs";
const OUT = "screenshots/flow-library"; mkdirSync(OUT, { recursive: true });
const results = [];
const check = (l, c, d = "") => { results.push({ l, c: !!c, d }); console.log(c ? "  ✅" : "  ❌", l, d ? `— ${d}` : ""); };
const shot = (p, n) => p.screenshot({ path: `${OUT}/${n}.png` });
const sidOf = (p) => p.evaluate(() => sessionStorage.getItem("flow_session_id"));
const state = (sid) => fetch(`${API}/sessions/${sid}/app/state`).then(r => r.json());

async function send(page, text) {
  console.log("→", text.slice(0, 78));
  await page.fill("[data-testid=chat-input]", text);
  await page.click("[data-testid=send-button]");
  try { await page.waitForSelector("[data-testid=stop-button]", { timeout: 12000 }); } catch {}
  await page.waitForSelector("[data-testid=send-button]", { timeout: 180000 });
  await page.waitForTimeout(1500);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1480, height: 920 } });
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.evaluate(() => sessionStorage.clear());
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 });
await page.waitForFunction(() => !!sessionStorage.getItem("flow_session_id"), { timeout: 20000 });
await page.waitForTimeout(1500);
const sid = await sidOf(page);
console.log("session:", sid);

console.log("\n[1] Upload a vendor contract as a SESSION file (NOT saved to Library)");
await page.click("[data-testid=nav--documents]");
await page.waitForSelector("[data-testid=documents-screen]", { timeout: 20000 });
await page.waitForTimeout(500);
await page.setInputFiles("[data-testid=upload-doc-input]", `${PDFS}/vendor-xyz-contract.pdf`);
await page.waitForSelector("[data-testid=doc-vendor-xyz-contract\\.md]", { timeout: 90000 });
await page.waitForTimeout(600);
check("vendor contract is a session file", await page.locator("[data-testid=doc-vendor-xyz-contract\\.md]").isVisible());
check("vendor contract NOT in Library", !(await state(sid)).library.some(d => d.filename === "vendor-xyz-contract.md"));

console.log("\n[2] Ask the agent to compare the session file against the Library");
await send(page, "I just uploaded vendor-xyz-contract.md. Compare its confidentiality/survival term against my standard ACME NDA in the library. How do the two differ on duration and governing law?");
await shot(page, "06-compare-contrast");
const chat = await page.locator("[data-testid=copilot-dock]").innerText();
check("mentions vendor term (5 years)", /five|5 years|5-year/i.test(chat), "");
check("mentions library NDA term (3 years)", /three|3 years|3-year/i.test(chat), "");
check("contrasts governing law (California vs Delaware)", /california/i.test(chat) && /delaware/i.test(chat), "");

await browser.close();
const passed = results.filter(r => r.c).length;
console.log(`\nsession: ${sid}`);
console.log(`${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 2);
