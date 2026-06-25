// Save to Library — Part 2: a NEW session still sees the promoted doc (persistence),
// and the agent can RAG-search its content (proving it's in the persistent KB).
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const APP = "http://localhost:3000", API = "http://localhost:8000";
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

// Fresh session (clear storage) — proves the Library survives a new session.
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.evaluate(() => sessionStorage.clear());
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 });
await page.waitForFunction(() => !!sessionStorage.getItem("flow_session_id"), { timeout: 20000 });
await page.waitForTimeout(1500);
const sid = await sidOf(page);
console.log("NEW session:", sid);

console.log("\n[1] Promoted doc persists into a brand-new session");
const lib = (await state(sid)).library || [];
check("new session sees acme-standard-nda.md in Library", lib.some(d => d.filename === "acme-standard-nda.md"), `library=${lib.length}`);
await page.click("[data-testid=nav--documents]");
await page.waitForSelector("[data-testid=documents-screen]", { timeout: 20000 });
await page.waitForTimeout(600);
check("rendered in Library group (new session)", await page.locator("[data-testid=lib-acme-standard-nda\\.md]").isVisible());

console.log("\n[2] RAG: agent searches the Library for the promoted doc's content");
await send(page, "Search my library: what is the confidentiality term in the ACME standard NDA, and which state's law governs it?");
await shot(page, "05-rag-answer");
const chatText = await page.locator("[data-testid=copilot-dock]").innerText();
check("agent answers from the saved doc (term = 3 years)", /three|3 years|3-year/i.test(chatText), "");
check("agent cites governing law (Delaware)", /delaware/i.test(chatText), "");

await browser.close();
const passed = results.filter(r => r.c).length;
console.log(`\nsession: ${sid}`);
console.log(`${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 2);
