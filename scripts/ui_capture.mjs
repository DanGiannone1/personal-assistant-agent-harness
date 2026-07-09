// Capture every screen + state of the real UI for review. No mocking — drives the live app.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const APP = "http://localhost:3000";
const OUT = "screenshots/ui-review"; mkdirSync(OUT, { recursive: true });
const W = process.env.NARROW ? 1040 : 1480, H = 940;
const SUF = process.env.NARROW ? "-narrow" : "";
const shot = async (p, n) => { await p.waitForTimeout(700); await p.screenshot({ path: `${OUT}/${n}${SUF}.png`, fullPage: false }); console.log("  📸", n + SUF); };
const nav = async (p, route, screen) => { await p.click(`[data-testid=nav--${route}]`); await p.waitForSelector(`[data-testid=${screen}]`, { timeout: 20000 }); await p.waitForTimeout(500); };

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: W, height: H } });
await page.goto(APP, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 });
await page.waitForFunction(() => !!sessionStorage.getItem("flow_session_id"), { timeout: 20000 });
await page.waitForTimeout(1800);

// Home
await nav(page, "home", "home-screen"); await shot(page, "01-home");
// To-Do list
await nav(page, "todo", "todo-screen"); await shot(page, "02-todo-list");
// To-Do add form
await page.click("[data-testid=add-task-btn]"); await shot(page, "03-todo-add-form");
await page.keyboard.press("Escape").catch(() => {});
// To-Do detail (first task row)
const firstTask = await page.evaluate(() => { const r = document.querySelector("[data-testid^=task-row-]"); return r?.getAttribute("data-testid")?.replace("task-row-", ""); });
if (firstTask) { await page.click(`[data-testid=task-row-${firstTask}]`); await page.waitForSelector("[data-testid=task-detail]"); await shot(page, "04-todo-detail"); }
// Calendar
await nav(page, "calendar", "calendar-screen"); await shot(page, "05-calendar");
await page.click("[data-testid=add-event-btn]"); await shot(page, "06-calendar-add-form");
// Documents
await nav(page, "documents", "documents-screen"); await shot(page, "07-documents");
// Reminders
await nav(page, "reminders", "reminders-screen"); await shot(page, "08-reminders");
await page.click("[data-testid=add-reminder-btn]"); await shot(page, "09-reminders-add-form");
// Dock collapsed (launcher) — only meaningful at desktop
if (!process.env.NARROW) {
  await nav(page, "home", "home-screen");
  const collapse = await page.$("[data-testid=copilot-dock] button[aria-label], [data-testid=copilot-dock] button");
  // find a collapse control inside the dock
  await page.evaluate(() => { const d = document.querySelector("[data-testid=copilot-dock]"); const btns = d?.querySelectorAll("button"); /* click last-ish chevron */ });
}
await browser.close();
console.log("done");
