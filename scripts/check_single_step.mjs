// Verify the common single-tool-call turn still looks clean with the new timeline CSS.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
const OUT = "screenshots/weekly-review"; mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({ headless: true });
const p = await b.newPage({ viewport: { width: 1480, height: 1000 } });
const errs = []; p.on("pageerror", (e) => errs.push(e.message));
await p.goto("http://localhost:3000", { waitUntil: "networkidle" });
await p.waitForSelector("[data-testid=workbench-app]", { timeout: 30000 });
await p.click("[data-testid=new-chat-button]").catch(() => {});
await p.waitForTimeout(2000);
await p.fill("[data-testid=chat-input]", "take me to my calendar");
await p.click("[data-testid=send-button]");
try { await p.waitForSelector("[data-testid=stop-button]", { timeout: 10000 }); } catch {}
await p.waitForSelector("[data-testid=send-button]", { timeout: 120000 });
await p.waitForTimeout(1500);
await p.locator("[data-testid=tool-trace]").last().screenshot({ path: `${OUT}/single-step-closeup.png` }).catch(() => {});
console.log("pageErrors:", errs.length);
await b.close();
