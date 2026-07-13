// Engagements UI journey: list + detail render from committed state, manual CRUD
// (engagement, action item), the amber-needs-a-why guard, and two-step delete.
// Validates each step against the rendered UI AND /app/state. Assumes the stack
// is already running (defaults below match dev.py; override via env for custom ports).
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const APP = process.env.APP_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://localhost:8000";
const OUT = "screenshots/engagements-ui"; mkdirSync(OUT, { recursive: true });
const results = [];
const check = (l, c, d = "") => { results.push({ l, c: !!c, d }); console.log(c ? "  ✅" : "  ❌", l, d ? `— ${d}` : ""); };
const state = (sid) => fetch(`${API}/sessions/${sid}/app/state`).then(r => r.json());

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1480, height: 920 } });
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 60000 });
await page.waitForFunction(() => !!sessionStorage.getItem("flow_session_id"), { timeout: 20000 });
const sid = await page.evaluate(() => sessionStorage.getItem("flow_session_id"));
console.log("session:", sid);

// Self-cleaning: purge engagements left behind by earlier (possibly aborted) runs,
// and use a per-run title so concurrent/stale rows can never alias this run's row.
const pre = await state(sid);
for (const g of (pre.engagements || []).filter(g => g.title.startsWith("UI Smoke Test"))) {
  await fetch(`${API}/sessions/${sid}/engagements/${g.id}`, { method: "DELETE" });
  console.log("cleaned leftover:", g.id, g.title);
}
const RUN_TITLE = `UI Smoke Test ${Date.now().toString(36)}`;
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 60000 });

// ── 1. Nav entry + list screen ──────────────────────────────────────────────
await page.click("[data-testid=nav--engagements]");
await page.waitForSelector("[data-testid=engagements-screen]", { timeout: 15000 });
await page.screenshot({ path: `${OUT}/01-list.png`, fullPage: true });
const nwRow = page.locator("[data-testid^=engagement-row-]", { hasText: "Northwind Analytics Platform" });
check("list shows Northwind row", await nwRow.count() === 1);
check("Northwind shows red badge", await nwRow.locator(".tw-badge-red").count() >= 1);
check("stat tiles render", await page.locator("[data-testid=engagements-screen] .tw-stat").count() >= 3);

// ── 2. Detail renders committed items ───────────────────────────────────────
await nwRow.first().click();
await page.waitForSelector("[data-testid=engagement-detail]", { timeout: 15000 });
await page.screenshot({ path: `${OUT}/02-detail.png`, fullPage: true });
check("health note visible", (await page.locator("[data-testid=engagement-detail]").innerText()).includes("security team rejected"));
check("milestone row renders", await page.locator("[data-testid^=eng-milestone-row-]", { hasText: "revised design approved" }).count() === 1);
const riskRow = page.locator("[data-testid^=eng-risk-row-]", { hasText: "network design rework" });
check("risk row renders (High, Dan)", await riskRow.count() === 1 && (await riskRow.innerText()).includes("Dan"));

// ── 3. Manual create engagement ─────────────────────────────────────────────
await page.click(".tw-back");
await page.waitForSelector("[data-testid=engagements-screen]");
await page.click("[data-testid=add-engagement-btn]");
await page.fill("[data-testid=engagement-title-input]", RUN_TITLE);
await page.fill("[data-testid=engagement-customer-input]", "Tailwind");
await page.click("[data-testid=engagement-save-btn]");
const uiRow = page.locator("[data-testid^=engagement-row-]", { hasText: RUN_TITLE });
await uiRow.waitFor({ timeout: 20000 });
await page.screenshot({ path: `${OUT}/03-created.png`, fullPage: true });
check("UI Smoke Test row appears", await uiRow.count() === 1);
check("new engagement green", await uiRow.locator(".tw-badge-green").count() >= 1);
let st = await state(sid);
let ui = (st.engagements || []).find(g => g.title === RUN_TITLE);
check("state has UI Smoke Test (green, Tailwind, Discovery)", ui && ui.health === "green" && ui.customer === "Tailwind" && ui.stage === "Discovery");

// ── 4. Add an action item on the detail page ────────────────────────────────
await uiRow.first().click();
await page.waitForSelector("[data-testid=engagement-detail]");
await page.click("[data-testid=add-action-btn]");
await page.fill("[data-testid=action-title-input]", "send recap email");
await page.fill("[data-testid=action-owner-input]", "Dan");
await page.click("[data-testid=action-save-btn]");
const actRow = page.locator("[data-testid^=eng-action-row-]", { hasText: "send recap email" });
await actRow.waitFor({ timeout: 20000 });
await page.screenshot({ path: `${OUT}/04-action.png`, fullPage: true });
check("action row renders", await actRow.count() === 1 && (await actRow.innerText()).includes("Dan"));

// ── 5. Amber without a why is blocked client-side ───────────────────────────
await page.selectOption("[data-testid=eng-edit-health]", "amber");
await page.waitForTimeout(800);
const guardText = await page.locator("[data-testid=engagement-edit]").innerText();
check("amber blocked without note", guardText.includes("Add a health note explaining why"));
st = await state(sid);
ui = (st.engagements || []).find(g => g.title === RUN_TITLE);
check("state still green (guard held the write)", ui && ui.health === "green");
await page.screenshot({ path: `${OUT}/05-amber-blocked.png`, fullPage: true });

// ── 6. Note supplied → amber commits ────────────────────────────────────────
await page.fill("[data-testid=eng-edit-health-note]", "waiting on budget approval");
await page.locator("[data-testid=eng-edit-health-note]").blur();
await page.waitForFunction(async () => true, {}, { timeout: 100 }).catch(() => {});
await page.waitForTimeout(2500); // auto-save round-trip + state refresh
st = await state(sid);
ui = (st.engagements || []).find(g => g.title === RUN_TITLE);
check("state amber with why", ui && ui.health === "amber" && ui.healthNote === "waiting on budget approval");
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 60000 });
await page.click("[data-testid=nav--engagements]");
const uiRow2 = page.locator("[data-testid^=engagement-row-]", { hasText: RUN_TITLE });
await uiRow2.waitFor({ timeout: 20000 });
check("amber badge renders after reload", await uiRow2.locator(".tw-badge-orange").count() >= 1);
await page.screenshot({ path: `${OUT}/06-amber-saved.png`, fullPage: true });

// ── 7. Two-step delete ──────────────────────────────────────────────────────
await uiRow2.locator("[data-testid^=engagement-delete-]").click();
await uiRow2.locator("[data-testid$=-confirm]").click();
await page.waitForTimeout(2000);
check("row gone after delete", await page.locator("[data-testid^=engagement-row-]", { hasText: RUN_TITLE }).count() === 0);
st = await state(sid);
check("state: UI Smoke Test deleted, Northwind intact",
  !(st.engagements || []).some(g => g.title === RUN_TITLE) &&
  (st.engagements || []).some(g => g.title.includes("Northwind") && g.health === "red"));
await page.screenshot({ path: `${OUT}/07-deleted.png`, fullPage: true });

await browser.close();
const fails = results.filter(r => !r.c);
console.log(`\n${results.length - fails.length}/${results.length} checks passed`);
if (fails.length) { console.log("FAILURES:", fails.map(f => f.l)); process.exit(1); }
console.log("ENGAGEMENTS UI E2E: ALL PASS");
