// Skeptical end-user + visual UX review of Flow. Drives the real frontend as a
// fresh user and captures screenshots to screenshots/review-ux/.
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const APP = process.env.APP_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://localhost:8000";
const OUT = "screenshots/review-ux";
mkdirSync(OUT, { recursive: true });

const log = (...a) => console.log(...a);
const shot = async (page, name) => { await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false }); log("  shot", name); };

async function send(page, text) {
  log("→", text.slice(0, 70).replace(/\n/g, " "));
  await page.fill("[data-testid=chat-input]", text);
  await page.click("[data-testid=send-button]");
  try { await page.waitForSelector("[data-testid=stop-button]", { timeout: 10000 }); } catch {}
  await page.waitForSelector("[data-testid=send-button]", { timeout: 180000 });
  await page.waitForTimeout(1500);
}
const lastAssistant = async (page) =>
  (await page.locator(".message-row-assistant, [data-testid=assistant-message]").last().innerText().catch(() => "")) || "";
async function getSid(page) { return await page.evaluate(() => sessionStorage.getItem("flow_session_id")); }

async function main() {
  const browser = await chromium.launch({ headless: true });

  // ---------- 1480px wide context (desktop) ----------
  const page = await browser.newPage({ viewport: { width: 1480, height: 900 } });
  page.on("pageerror", (e) => log("  PAGEERROR:", e.message));
  page.on("console", (m) => { if (m.type() === "error") log("  CONSOLE-ERR:", m.text().slice(0,140)); });

  log("\n[1] First load / landing");
  const t0 = Date.now();
  await page.goto(APP, { waitUntil: "domcontentloaded" });
  await shot(page, "00-initial-paint"); // capture immediate paint for loading-state assessment
  await page.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 }).catch(()=>{});
  await page.waitForSelector("[data-testid=home-screen]", { timeout: 40000 }).catch(()=>{});
  log("  time to home-screen:", Date.now()-t0, "ms");
  await page.waitForTimeout(800);
  await shot(page, "01-home-loaded");

  // Capture document title and any obvious "what is this" affordances
  log("  document.title =", await page.title());

  // Is there a dock launcher / co-pilot visible?
  const dockVisible = await page.locator("[data-testid=copilot-dock]").isVisible().catch(()=>false);
  const launcherVisible = await page.locator("[data-testid=dock-launcher]").isVisible().catch(()=>false);
  log("  copilot-dock visible:", dockVisible, " dock-launcher visible:", launcherVisible);

  log("\n[2] Nav across all 5 surfaces (client-side)");
  const navs = [
    ["nav--home", "home-screen", "02a-home"],
    ["nav--todo", "todo-screen", "02b-todo"],
    ["nav--calendar", "calendar-screen", "02c-calendar"],
    ["nav--documents", "documents-screen", "02d-documents"],
    ["nav-assistant", "artifact-viewer", "02e-assistant"],
  ];
  for (const [testid, screen, name] of navs) {
    const tn = Date.now();
    await page.click(`[data-testid=${testid}]`).catch(()=>log("  CLICK FAIL", testid));
    const ok = await page.waitForSelector(`[data-testid=${screen}]`, { timeout: 8000 }).then(()=>true).catch(()=>false);
    await page.waitForTimeout(500);
    await shot(page, name);
    log(`  ${testid} → ${screen}: ${ok ? "ok" : "NOT FOUND"} (${Date.now()-tn}ms)`);
  }

  log("\n[3] AI Workbench empty state look");
  // already on assistant; capture the empty/initial assistant pane
  await shot(page, "03-assistant-empty");

  log("\n[4] Co-pilot dock on a host surface");
  await page.click("[data-testid=nav--home]"); await page.waitForTimeout(600);
  // try to open dock if collapsed
  if (await page.locator("[data-testid=dock-launcher]").isVisible().catch(()=>false)) {
    await page.click("[data-testid=dock-launcher]"); await page.waitForTimeout(400);
  }
  await shot(page, "04-home-with-dock");

  log("\n[5] Real flow: ask assistant to add a task, watch UI update");
  // Make sure chat input present (dock or workbench)
  const haveInput = await page.locator("[data-testid=chat-input]").first().isVisible().catch(()=>false);
  log("  chat-input visible on home:", haveInput);
  if (!haveInput) {
    await page.click("[data-testid=nav-assistant]").catch(()=>{});
    await page.waitForTimeout(600);
  }
  const sid = await getSid(page);
  log("  session id:", sid);

  // perceived latency: capture during the run
  await page.fill("[data-testid=chat-input]", "Add a high-priority task 'Renew passport' due 2026-07-01 in Personal.");
  const tSend = Date.now();
  await page.click("[data-testid=send-button]");
  // capture progress indicator quickly
  await page.waitForTimeout(700);
  await shot(page, "05a-mid-turn-progress");
  try { await page.waitForSelector("[data-testid=stop-button]", { timeout: 8000 }); } catch {}
  await page.waitForSelector("[data-testid=send-button]", { timeout: 180000 });
  log("  task turn took", Date.now()-tSend, "ms");
  await page.waitForTimeout(1500);
  await shot(page, "05b-after-add-task");

  // go to todo to see it
  await page.click("[data-testid=nav--todo]").catch(()=>{}); await page.waitForTimeout(800);
  await shot(page, "05c-todo-after-add");
  const taskVisible = await page.getByText("Renew passport").first().isVisible().catch(()=>false);
  log("  'Renew passport' visible in To-Do:", taskVisible);
  // verify state
  let state = {};
  try { state = await (await fetch(`${API}/sessions/${sid}/app/state`)).json(); } catch(e){ log("  state fetch fail", e.message); }
  const created = (state.tasks||[]).find(t=>/renew passport/i.test(t.title));
  log("  task in /app/state:", created ? `${created.title}/${created.priority}/${created.group}/due ${created.dueDate}` : "NOT FOUND");

  log("\n[6] Open a document");
  await page.click("[data-testid=nav--documents]").catch(()=>{}); await page.waitForTimeout(700);
  await shot(page, "06a-documents-list");
  // try clicking the first document card/row
  const docCard = page.locator("[data-testid=documents-screen] [role=button], [data-testid=documents-screen] button, [data-testid=documents-screen] li, [data-testid=documents-screen] a").first();
  const docCount = await page.locator("[data-testid=documents-screen]").innerText().catch(()=>"");
  log("  documents-screen text (first 200):", docCount.slice(0,200).replace(/\n/g," | "));
  // attempt to open something
  const clickable = page.locator("[data-testid=documents-screen]").locator("button, [role=button], a, li").first();
  if (await clickable.count()) {
    await clickable.click().catch(()=>{});
    await page.waitForTimeout(900);
    await shot(page, "06b-document-opened");
  }

  log("\n[7] Empty/ambiguous input handling in chat");
  await page.click("[data-testid=nav-assistant]").catch(()=>{});
  await page.waitForTimeout(500);
  // empty submit
  await page.fill("[data-testid=chat-input]", "");
  const sendDisabledOnEmpty = await page.locator("[data-testid=send-button]").isDisabled().catch(()=>null);
  log("  send-button disabled on empty input:", sendDisabledOnEmpty);
  await shot(page, "07a-empty-input");

  log("\n[8] Fail-loud unknown destination");
  await send(page, "take me to the crypto mining dashboard");
  await shot(page, "08-unknown-dest");
  log("  assistant said:", (await lastAssistant(page)).replace(/\n/g," ").slice(0,160));

  await page.close();

  // ---------- narrow viewport ~900px ----------
  log("\n[9] Narrow viewport (900px) responsiveness");
  const np = await browser.newPage({ viewport: { width: 900, height: 880 } });
  np.on("pageerror", (e) => log("  PAGEERROR(narrow):", e.message));
  await np.goto(APP, { waitUntil: "domcontentloaded" });
  await np.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 }).catch(()=>{});
  await np.waitForTimeout(1000);
  await shot(np, "09a-narrow-home");
  const dockNarrow = await np.locator("[data-testid=copilot-dock]").isVisible().catch(()=>false);
  const launcherNarrow = await np.locator("[data-testid=dock-launcher]").isVisible().catch(()=>false);
  log("  narrow: dock visible:", dockNarrow, " launcher visible:", launcherNarrow);
  // nav each surface narrow
  for (const [testid, screen, name] of [
    ["nav--todo","todo-screen","09b-narrow-todo"],
    ["nav--calendar","calendar-screen","09c-narrow-calendar"],
    ["nav--documents","documents-screen","09d-narrow-documents"],
    ["nav-assistant","artifact-viewer","09e-narrow-assistant"],
  ]) {
    await np.click(`[data-testid=${testid}]`).catch(()=>{});
    await np.waitForSelector(`[data-testid=${screen}]`, { timeout: 8000 }).catch(()=>{});
    await np.waitForTimeout(500);
    await shot(np, name);
  }
  await np.close();

  // ---------- very narrow ~700 to stress dock collapse ----------
  log("\n[10] Very narrow (700px)");
  const vp = await browser.newPage({ viewport: { width: 700, height: 820 } });
  await vp.goto(APP, { waitUntil: "domcontentloaded" });
  await vp.waitForSelector("[data-testid=workbench-app]", { timeout: 40000 }).catch(()=>{});
  await vp.waitForTimeout(1000);
  await shot(vp, "10-verynarrow-home");
  await vp.close();

  await browser.close();
  log("\nDONE");
}
main().catch((e)=>{ console.error("FATAL", e); process.exit(1); });
