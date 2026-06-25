// Save to Library — Part 1: two-tier Documents UI, upload a PDF (CU conversion),
// promote it to the persistent Library. Real frontend, dummy PDF.
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

async function nav(page, route, screen) {
  await page.click(`[data-testid=nav-${route.replace(/\//g, "-")}]`);
  await page.waitForSelector(`[data-testid=${screen}]`, { timeout: 20000 });
  await page.waitForTimeout(500);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1480, height: 920 } });
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 });
await page.waitForFunction(() => !!sessionStorage.getItem("flow_session_id"), { timeout: 20000 });
await page.waitForTimeout(1500); // let React hydrate before driving nav
const sid = await sidOf(page);
console.log("session:", sid);

console.log("\n[1] Documents — Library (persistent) seeded; This session empty");
await nav(page, "/documents", "documents-screen");
await shot(page, "01-documents-initial");
const lib0 = (await state(sid)).library || [];
check("Library pre-loaded with reference docs", lib0.length >= 5, `library=${lib0.length}`);
check("Library group rendered", await page.locator("[data-testid=library-group]").isVisible());
check("Uploaded-this-session empty", /no uploads this session/i.test(await page.locator("[data-testid=uploaded-group]").innerText()));

console.log("\n[2] Upload a dummy PDF (Content Understanding converts it)");
await page.setInputFiles("[data-testid=upload-doc-input]", `${PDFS}/acme-standard-nda.pdf`);
// CU conversion: wait (up to 90s) for the converted .md session file to appear.
await page.waitForSelector("[data-testid=doc-acme-standard-nda\\.md]", { timeout: 90000 });
await page.waitForTimeout(800);
await shot(page, "02-uploaded-session-file");
check("converted .md appears as a session file", await page.locator("[data-testid=doc-acme-standard-nda\\.md]").isVisible());
check("not yet in Library", !(await state(sid)).library.some(d => d.filename === "acme-standard-nda.md"));

console.log("\n[3] Save to Library (the promotion)");
await page.click("[data-testid=save-lib-acme-standard-nda\\.md]");
// Wait until it appears in the Library group (refetch-driven).
await page.waitForSelector("[data-testid=lib-acme-standard-nda\\.md]", { timeout: 30000 });
await page.waitForTimeout(800);
await shot(page, "03-after-save-to-library");
const libAfter = (await state(sid)).library || [];
check("now in Library (Cosmos)", libAfter.some(d => d.filename === "acme-standard-nda.md"), `library=${libAfter.length}`);
check("rendered in Library group", await page.locator("[data-testid=lib-acme-standard-nda\\.md]").isVisible());
check("removed from This session (promoted)", !(await page.locator("[data-testid=doc-acme-standard-nda\\.md]").isVisible().catch(() => false)));

console.log("\n[4] Open the Library doc (content served from the index)");
await page.click("[data-testid=lib-acme-standard-nda\\.md] button");
await page.waitForSelector("[data-testid=doc-viewer]", { timeout: 20000 });
await page.waitForTimeout(600);
await shot(page, "04-library-doc-viewer");
const viewerText = await page.locator("[data-testid=doc-viewer]").innerText();
check("Library doc content renders (NDA term)", /three \(3\) years|delaware/i.test(viewerText), viewerText.slice(0, 80).replace(/\n/g, " "));

await browser.close();
const passed = results.filter(r => r.c).length;
console.log(`\nsession: ${sid}`);
console.log(`${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 2);
