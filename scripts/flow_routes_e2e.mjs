// Full route-coverage e2e against the LIVE Cosmos-backed Flow app.
// Walks every route as a real user: Home, To-Do, Calendar, Documents, task detail,
// doc viewer, AI Workbench — first BLANK (fresh Cosmos seed), then POPULATED by the
// agent, then proves persistence across a hard reload. Screenshots at every step.
// Run: node scripts/flow_routes_e2e.mjs
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const APP = "http://localhost:3000", API = "http://localhost:8000";
const OUT = "screenshots/flow-routes"; mkdirSync(OUT, { recursive: true });
const results = [];
const check = (l, c, d = "") => { results.push({ l, c: !!c, d }); console.log(c ? "  ✅" : "  ❌", l, d ? `— ${d}` : ""); };
const shot = (p, n) => p.screenshot({ path: `${OUT}/${n}.png`, fullPage: false });

async function send(page, text) {
  console.log("→", text.slice(0, 78));
  await page.fill("[data-testid=chat-input]", text);
  await page.click("[data-testid=send-button]");
  try { await page.waitForSelector("[data-testid=stop-button]", { timeout: 12000 }); } catch {}
  await page.waitForSelector("[data-testid=send-button]", { timeout: 180000 });
  await page.waitForTimeout(1500);
}
async function nav(page, route, screen) {
  await page.click(`[data-testid=nav-${route.replace(/\//g, "-")}]`);
  await page.waitForSelector(`[data-testid=${screen}]`, { timeout: 20000 });
  await page.waitForTimeout(600);
}
const state = async (sid) => fetch(`${API}/sessions/${sid}/app/state`).then(r => r.json());

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1480, height: 920 } });

// ─── 1. Fresh session — blank Cosmos seed ────────────────────────────────────
console.log("\n[1] Fresh session — every route BLANK");
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=home-screen]", { timeout: 40000 });
const sid = await page.evaluate(() => sessionStorage.getItem("flow_session_id"));
writeFileSync(`${OUT}/sid.txt`, sid || "");
console.log("  session:", sid);
const seed = await state(sid);
check("seed: 0 tasks", (seed.tasks || []).length === 0, `tasks=${(seed.tasks||[]).length}`);
check("seed: 0 events", (seed.events || []).length === 0, `events=${(seed.events||[]).length}`);

await shot(page, "01-home-blank");
check("Home renders", await page.locator("[data-testid=home-screen]").isVisible());

await nav(page, "/todo", "todo-screen"); await shot(page, "02-todo-blank");
check("To-Do empty state", /no tasks yet/i.test(await page.locator("[data-testid=todo-screen]").innerText()));

await nav(page, "/calendar", "calendar-screen"); await shot(page, "03-calendar-blank");
check("Calendar empty state", /nothing scheduled/i.test(await page.locator("[data-testid=calendar-screen]").innerText()));

await nav(page, "/documents", "documents-screen"); await shot(page, "04-documents-blank");
check("Documents empty state", /no generated documents/i.test(await page.locator("[data-testid=documents-screen]").innerText()));

// ─── 2. Agent populates each entity type ─────────────────────────────────────
console.log("\n[2] Agent populates tasks / event / document");
await send(page, "Create a high-priority task 'Submit quarterly report' due 2026-06-24 in the Work group, with two subtasks: 'Gather figures' and 'Write summary'.");
await send(page, "Add a medium-priority task 'Renew software license' due 2026-06-20 in the Personal group.");
await send(page, "Add a calendar event 'Team standup' on 2026-06-24 from 09:00 to 09:30.");
await send(page, "Draft a short document with three bullet points of meeting notes and save it to my documents.");

const pop = await state(sid);
check("2 tasks in Cosmos", (pop.tasks || []).length === 2, `tasks=${(pop.tasks||[]).length}`);
check("1 event in Cosmos", (pop.events || []).length === 1, `events=${(pop.events||[]).length}`);
const repTask = (pop.tasks || []).find(t => /quarterly report/i.test(t.title));
check("task has 2 subtasks", repTask && (repTask.subtasks || []).length === 2, repTask ? `subtasks=${(repTask.subtasks||[]).length}` : "missing");

// ─── 3. Populated routes ─────────────────────────────────────────────────────
console.log("\n[3] Every route POPULATED");
await nav(page, "/home", "home-screen"); await shot(page, "05-home-populated");
check("Home shows overdue table", await page.locator("[data-testid=overdue-table]").isVisible().catch(() => false));
check("Home shows today's events", await page.locator("[data-testid=home-events]").isVisible().catch(() => false));

await nav(page, "/todo", "todo-screen"); await shot(page, "06-todo-populated");
check("To-Do tasks table renders", await page.locator("[data-testid=tasks-table]").first().isVisible());
check("To-Do shows report task", /quarterly report/i.test(await page.locator("[data-testid=todo-screen]").innerText()));

console.log("  → drill into task detail");
await page.locator('[data-testid^="task-row-"]').first().click();
await page.waitForSelector("[data-testid=task-detail]", { timeout: 20000 }); await page.waitForTimeout(500);
await shot(page, "07-task-detail");
check("Task detail shows subtasks", await page.locator("[data-testid=task-subtasks]").isVisible().catch(() => false));

await nav(page, "/calendar", "calendar-screen"); await shot(page, "08-calendar-populated");
check("Calendar shows standup", /standup/i.test(await page.locator("[data-testid=calendar-screen]").innerText()));

await nav(page, "/documents", "documents-screen"); await shot(page, "09-documents-populated");
const docBtn = page.locator('[data-testid^="doc-"]').first();
const hasDoc = await docBtn.count() > 0;
check("Documents shows a generated doc", hasDoc);
if (hasDoc) {
  console.log("  → open doc viewer");
  await docBtn.click();
  await page.waitForSelector("[data-testid=doc-viewer]", { timeout: 20000 }); await page.waitForTimeout(600);
  await shot(page, "10-doc-viewer");
  check("Doc viewer renders content", (await page.locator("[data-testid=doc-viewer]").innerText()).length > 20);
}

console.log("  → AI Workbench (/assistant)");
await page.click("[data-testid=nav-assistant]");
await page.waitForLoadState("domcontentloaded"); await page.waitForTimeout(1500);
await shot(page, "11-assistant-workbench");
check("AI Workbench on /assistant route", page.url().includes("/assistant"), page.url());

// ─── 4. Persistence across hard reload (server-side Cosmos) ───────────────────
console.log("\n[4] Persistence across hard reload");
await page.goto(APP, { waitUntil: "networkidle" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 });
await page.waitForSelector("[data-testid=nav--todo]", { timeout: 20000 });
await page.waitForTimeout(2000); // let React hydrate before clicking nav
const reloadState = await state(sid);
check("Cosmos still has 2 tasks after reload", (reloadState.tasks || []).length === 2, `tasks=${(reloadState.tasks||[]).length}`);
await nav(page, "/todo", "todo-screen"); await page.waitForTimeout(800);
await shot(page, "12-after-reload-todo");
check("tasks persist after reload", /quarterly report/i.test(await page.locator("[data-testid=todo-screen]").innerText()));

await browser.close();
const passed = results.filter(r => r.c).length;
console.log(`\nsession id: ${sid}`);
console.log(`${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 2);
