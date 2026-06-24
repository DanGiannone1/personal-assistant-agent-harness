// Verifies the Cosmos-backed store: a fresh session is BLANK (to-do + calendar empty),
// the agent can create a task, and it renders + lands in /app/state (which now reads
// from Cosmos). Writes the session id to screens/sid.txt so a follow-up step can prove
// the document physically lives in Cosmos. Run: node scripts/flow_cosmos_e2e.mjs
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const APP = "http://localhost:3000", API = "http://localhost:8000";
const OUT = "screenshots/flow-cosmos"; mkdirSync(OUT, { recursive: true });
const results = [];
const check = (l, c, d = "") => { results.push({ l, c: !!c, d }); console.log(c ? "  ✅" : "  ❌", l, d ? `— ${d}` : ""); };
const shot = (p, n) => p.screenshot({ path: `${OUT}/${n}.png` });

async function send(page, text) {
  console.log("→", text.slice(0, 80));
  await page.fill("[data-testid=chat-input]", text);
  await page.click("[data-testid=send-button]");
  try { await page.waitForSelector("[data-testid=stop-button]", { timeout: 10000 }); } catch {}
  await page.waitForSelector("[data-testid=send-button]", { timeout: 180000 });
  await page.waitForTimeout(1800);
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1480, height: 920 } });

console.log("\n[1] Fresh session is blank");
await page.goto(APP, { waitUntil: "networkidle" });
await page.waitForSelector("[data-testid=home-screen]", { timeout: 40000 });
const sid = await page.evaluate(() => sessionStorage.getItem("flow_session_id"));
writeFileSync(`${OUT}/sid.txt`, sid || "");
const seed = await fetch(`${API}/sessions/${sid}/app/state`).then(r => r.json());
check("fresh session: 0 tasks", (seed.tasks || []).length === 0, `tasks=${(seed.tasks||[]).length}`);
check("fresh session: 0 events", (seed.events || []).length === 0, `events=${(seed.events||[]).length}`);
await page.click("[data-testid=nav--todo]"); await page.waitForSelector("[data-testid=todo-screen]"); await page.waitForTimeout(500);
await shot(page, "01-todo-blank");
check("To-Do shows empty state", /no tasks/i.test(await page.locator("[data-testid=todo-screen]").innerText()));
await page.click("[data-testid=nav--calendar]"); await page.waitForSelector("[data-testid=calendar-screen]"); await page.waitForTimeout(500);
await shot(page, "02-calendar-blank");

console.log("\n[2] Agent creates a task → renders + persists to Cosmos");
await send(page, "Add a high-priority task called 'Buy groceries' due 2026-06-30 in the Personal group.");
const after = await fetch(`${API}/sessions/${sid}/app/state`).then(r => r.json());
const t = (after.tasks || []).find(x => /buy groceries/i.test(x.title));
check("task in /app/state (served from Cosmos)", !!t, t ? `${t.title}/${t.status}/${t.priority}/${t.group}/${t.dueDate}` : "missing");
await page.click("[data-testid=nav--todo]"); await page.waitForTimeout(800);
await shot(page, "03-task-created");
check("task rendered in To-Do", await page.getByText("Buy groceries").first().isVisible().catch(() => false));

console.log("\n[3] Persists across reload (state is server-side, in Cosmos)");
await page.goto(APP, { waitUntil: "networkidle" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 });
await page.click("[data-testid=nav--todo]"); await page.waitForSelector("[data-testid=todo-screen]"); await page.waitForTimeout(800);
await shot(page, "04-after-reload");
check("task persists after reload", await page.getByText("Buy groceries").first().isVisible().catch(() => false));

await browser.close();
console.log(`\nsession id: ${sid}`);
const passed = results.filter(r => r.c).length;
console.log(`\n${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 2);
