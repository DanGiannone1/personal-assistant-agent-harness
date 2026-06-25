// Manual CRUD via the real UI — NO assistant involved. Creates uniquely-named records,
// edits them, then deletes them (net-zero on the shared owner doc). Proves the app
// stands on its own without the AI.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const APP = "http://localhost:3000", API = "http://localhost:8000";
const OUT = "screenshots/manual-crud"; mkdirSync(OUT, { recursive: true });
const TAG = "ZZ-crud-" + Date.now().toString().slice(-5);
const results = [];
const check = (l, c, d = "") => { results.push({ l, c: !!c, d }); console.log(c ? "  ✅" : "  ❌", l, d ? `— ${d}` : ""); };
const shot = (p, n) => p.screenshot({ path: `${OUT}/${n}.png` });
const sidOf = (p) => p.evaluate(() => sessionStorage.getItem("flow_session_id"));
const state = (sid) => fetch(`${API}/sessions/${sid}/app/state`).then(r => r.json());
const nav = async (p, route, screen) => { await p.click(`[data-testid=nav-${route.replace(/\//g, "-")}]`); await p.waitForSelector(`[data-testid=${screen}]`, { timeout: 20000 }); await p.waitForTimeout(500); };

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1480, height: 920 } });
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 });
await page.waitForFunction(() => !!sessionStorage.getItem("flow_session_id"), { timeout: 20000 });
await page.waitForTimeout(1500);
const sid = await sidOf(page);
console.log("session:", sid);

// ─── TASKS ───
console.log("\n[Tasks] add → edit status → subtask → delete (no AI)");
await nav(page, "/todo", "todo-screen");
await page.click("[data-testid=add-task-btn]");
await page.fill("[data-testid=task-title-input]", `${TAG} task`);
await page.selectOption("[data-testid=task-priority-select]", "High");
await page.fill("[data-testid=task-due-input]", "2026-07-10");
await page.click("[data-testid=task-save-btn]");
await page.waitForTimeout(1200);
let st = await state(sid); let t = (st.tasks || []).find(x => x.title === `${TAG} task`);
check("task created via UI", !!t, t ? `${t.title}/${t.priority}` : "none");
await shot(page, "01-task-created");

await page.click(`[data-testid=task-row-${t.id}]`);
await page.waitForSelector("[data-testid=task-detail]", { timeout: 20000 }); await page.waitForTimeout(500);
await page.selectOption("[data-testid=edit-status]", "In progress");
await page.waitForTimeout(1000);
st = await state(sid); t = (st.tasks || []).find(x => x.id === t.id);
check("status changed via UI dropdown", t && t.status === "In progress", t?.status);

await page.fill("[data-testid=subtask-input]", "first step");
await page.click("[data-testid=subtask-add-btn]"); await page.waitForTimeout(1000);
await page.click("[data-testid=subtask-0]"); await page.waitForTimeout(1000);  // toggle done
st = await state(sid); t = (st.tasks || []).find(x => x.id === t.id);
check("subtask added + toggled done via UI", t && (t.subtasks || [])[0]?.done === true, JSON.stringify(t?.subtasks));
await shot(page, "02-task-detail-edited");

// Edit title + group via the detail editor (Enter commits on blur)
await page.fill("[data-testid=edit-title]", `${TAG} task RENAMED`);
await page.press("[data-testid=edit-title]", "Enter"); await page.waitForTimeout(1000);
await page.fill("[data-testid=edit-group]", "Personal");
await page.press("[data-testid=edit-group]", "Enter"); await page.waitForTimeout(1000);
st = await state(sid); t = (st.tasks || []).find(x => x.id === t.id);
check("title + group edited via UI", t && t.title === `${TAG} task RENAMED` && t.group === "Personal", `${t?.title} / ${t?.group}`);

// Delete the subtask via its per-row ✕
await page.click("[data-testid=subtask-delete-0]"); await page.waitForTimeout(1000);
st = await state(sid); t = (st.tasks || []).find(x => x.id === t.id);
check("subtask deleted via UI", t && (t.subtasks || []).length === 0, JSON.stringify(t?.subtasks));

await page.click("[data-testid=delete-task-btn]");           // arm
await page.click("[data-testid=delete-task-confirm]");       // confirm
await page.waitForTimeout(1200);
st = await state(sid);
check("task deleted via UI (two-step confirm)", !(st.tasks || []).some(x => x.id === t.id));

// ─── EVENTS ───
console.log("\n[Events] add → delete (no AI)");
await nav(page, "/calendar", "calendar-screen");
await page.click("[data-testid=add-event-btn]");
await page.fill("[data-testid=event-title-input]", `${TAG} event`);
await page.fill("[data-testid=event-date-input]", "2026-07-11");
await page.fill("[data-testid=event-start-input]", "14:00");
await page.click("[data-testid=event-save-btn]"); await page.waitForTimeout(1200);
st = await state(sid); let e = (st.events || []).find(x => x.title === `${TAG} event`);
check("event created via UI", !!e, e ? `${e.date} ${e.start}` : "none");
await shot(page, "03-event-created");
await page.click(`[data-testid=event-delete-${e.id}]`);           // arm
await page.click(`[data-testid=event-delete-${e.id}-confirm]`);   // confirm
await page.waitForTimeout(1200);
st = await state(sid);
check("event deleted via UI (two-step confirm)", !(st.events || []).some(x => x.id === e.id));

// ─── REMINDERS ───
console.log("\n[Reminders] add → pause → delete (no AI)");
await nav(page, "/reminders", "reminders-screen");
await page.click("[data-testid=add-reminder-btn]");
await page.fill("[data-testid=reminder-title-input]", `${TAG} reminder`);
await page.fill("[data-testid=reminder-prompt-input]", "summarize my open tasks");
await page.fill("[data-testid=reminder-time-input]", "09:00");
await page.click("[data-testid=reminder-save-btn]"); await page.waitForTimeout(1200);
st = await state(sid); let s = (st.schedules || []).find(x => x.title === `${TAG} reminder`);
check("reminder created via UI", !!s && s.frequency === "daily", s ? `${s.frequency} ${s.time} ${s.timezone}` : "none");
await shot(page, "04-reminder-created");
await page.click(`[data-testid=reminder-toggle-${s.id}]`); await page.waitForTimeout(1000);
st = await state(sid); s = (st.schedules || []).find(x => x.id === s.id);
check("reminder paused via UI", s && s.enabled === false, `enabled=${s?.enabled}`);
await page.click(`[data-testid=reminder-delete-${s.id}]`);           // arm
await page.click(`[data-testid=reminder-delete-${s.id}-confirm]`);   // confirm
await page.waitForTimeout(1200);
st = await state(sid);
check("reminder deleted via UI (two-step confirm)", !(st.schedules || []).some(x => x.id === s.id));

await browser.close();
const passed = results.filter(r => r.c).length;
console.log(`\n${passed}/${results.length} checks passed`);
process.exit(passed === results.length ? 0 : 2);
