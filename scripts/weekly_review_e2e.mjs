// Exercise the weekly-review complex skill: populate state (incl. overdue tasks),
// run the multi-step routine, and capture the rich trace + deliverable + state changes.
// This is the fixture for the complex-UI work. Run: node scripts/weekly_review_e2e.mjs
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
const API = "http://localhost:8000";
const OUT = "screenshots/weekly-review"; mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 1480, height: 1000 } });
const errs = []; p.on("pageerror", (e) => errs.push(e.message));
let n = 0; const shot = (name) => p.screenshot({ path: `${OUT}/${String(++n).padStart(2,"0")}-${name}.png`, fullPage: true });
let fails = 0; const ck = (l, ok, d = "") => { console.log(`${ok ? "PASS" : "FAIL"}  ${l}${d ? ` — ${String(d).replace(/\n/g," ").slice(0,160)}` : ""}`); if (!ok) fails++; };

async function send(text) {
  await p.fill("[data-testid=chat-input]", text);
  await p.click("[data-testid=send-button]");
  try { await p.waitForSelector("[data-testid=stop-button]", { timeout: 12000 }); } catch {}
  await p.waitForSelector("[data-testid=send-button]", { timeout: 240000 });
  await p.waitForTimeout(1200);
}
let sessionId = null;
const readSession = async () => (await p.evaluate(() => Object.values(sessionStorage).find(v => /^[0-9a-f]{16}$/.test(v)))) || null;
const appState = async () => { try { const r = await fetch(`${API}/sessions/${sessionId}/app/state`); return r.ok ? r.json() : { _e: r.status }; } catch (e) { return { _e: String(e) }; } };
const files = async () => { try { const r = await fetch(`${API}/sessions/${sessionId}/files`); return r.ok ? r.json() : { _e: r.status }; } catch (e) { return { _e: String(e) }; } };

await p.goto("http://localhost:3000", { waitUntil: "networkidle" });
await p.waitForSelector("[data-testid=workbench-app]", { timeout: 30000 });
await p.click("[data-testid=new-chat-button]").catch(() => {});
await p.waitForTimeout(2500);
sessionId = await readSession();
ck("session created", !!sessionId, sessionId || "none");

// State is pre-populated deterministically by scripts/reset_demo_state.py (owner-keyed
// Cosmos persists across sessions, so this isolates the fixture from prior runs).
const before = await appState();
writeFileSync(`${OUT}/state-before.json`, JSON.stringify(before, null, 2));
ck("demo state present (5 tasks, 2 overdue)", (before.tasks || []).length === 5, `tasks=${(before.tasks||[]).length}`);

// ── Run the complex routine ──────────────────────────────────────────────────
await send("Run my full weekly review now and complete every step before replying: review all my tasks, reschedule each overdue task to a new due date, check the calendar and add a 90-minute focus block, mark my top three tasks High priority, then write the status-update document.");
await shot("weekly-review-trace");
await p.locator("[data-testid=tool-trace]").last().screenshot({ path: `${OUT}/trace-closeup.png` }).catch(() => {});
await p.locator(".message-row-assistant").last().screenshot({ path: `${OUT}/assistant-message.png` }).catch(() => {});
const proseStyle = await p.evaluate(() => {
  const el = [...document.querySelectorAll(".message-row-assistant .prose-message")].pop();
  if (!el) return null;
  const s = getComputedStyle(el);
  return { bg: s.backgroundColor, font: s.fontFamily.slice(0, 40), parentBg: getComputedStyle(el.parentElement).backgroundColor };
});
console.log("PROBE prose-message:", JSON.stringify(proseStyle));
const after = await appState();
writeFileSync(`${OUT}/state-after.json`, JSON.stringify(after, null, 2));

// tool-call count from the last turn's meta
const meta = (await p.locator("[data-testid=turn-meta]").last().innerText().catch(() => "")) || "";
const nTools = parseInt((meta.match(/(\d+)\s+tool call/) || [])[1] || "0", 10);
ck("review was genuinely multi-step (>= 5 tool calls)", nTools >= 5, `meta="${meta}"`);

// state changes
const overdueRemaining = (after.tasks || []).filter(t => t.dueDate && t.dueDate < "2026-06-25" && t.status !== "Done");
ck("no task left silently overdue (rescheduled)", overdueRemaining.length === 0, `still overdue: ${overdueRemaining.map(t=>t.title).join(", ") || "none"}`);
const highs = (after.tasks || []).filter(t => t.priority === "High");
ck("top-three raised to High priority", highs.length >= 3, `High=${highs.length}`);
const focus = (after.events || []).find(e => /focus/i.test(e.title) || /focus/i.test(e.type));
ck("a Focus block was added to the calendar", !!focus, focus ? `${focus.title} ${focus.date}` : "none");
const fl = await files();
const reviewDoc = (fl.files || []).find(f => /weekly-review-\d{4}/i.test(f.filename));
ck("status-update document was written", !!reviewDoc, reviewDoc ? reviewDoc.filename : JSON.stringify((fl.files||[]).map(f=>f.filename)));

// open the deliverable in the canvas
await p.click("[data-testid=dock-expand]").catch(() => {});
await p.waitForTimeout(1200);
await shot("weekly-review-artifact");
const art = (await p.locator("[data-testid=artifact-viewer]").innerText().catch(() => "")) || "";
ck("deliverable has Moved/Blocked/Next sections", /moved/i.test(art) && /next/i.test(art), art.replace(/\n/g," ").slice(0,160));

// Proof capture: the full-screen AI Workbench rendering the same conversation.
await p.click("[data-testid=nav-assistant]").catch(() => {});
await p.waitForTimeout(2500);
await p.screenshot({ path: `${OUT}/workbench-proof.png`, fullPage: false });

console.log(`\nsession=${sessionId}  review tool calls=${nTools}`);
console.log(`${fails === 0 ? "ALL PASSED" : fails + " FAILED"} | pageErrors=${errs.length}`);
errs.forEach(e => console.log("  pageerror:", e));
await b.close();
process.exit(fails > 0 || errs.length > 0 ? 1 : 0);
