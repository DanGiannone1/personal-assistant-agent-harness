// CSA-perspective adherence audit — signs in as a demo user, sweeps every nav surface,
// exercises agent CRUD + orientation, and attempts transcript uploads (.vtt + .md).
// Run: DEMO_PASSWORD=... node scripts/csa_audit.mjs   (stack must be up)
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

const APP = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "screenshots/csa-audit";
mkdirSync(OUT, { recursive: true });

const VTT = "/tmp/2026-07-16-contoso-aks-call.vtt";
writeFileSync(
  VTT,
  `WEBVTT

00:00:01.000 --> 00:00:06.000
Dan (Microsoft): Thanks for joining the Contoso AKS design session.

00:00:07.000 --> 00:00:15.000
Priya (Contoso): Before our security review on Friday we need a cost estimate for private endpoints.

00:00:16.000 --> 00:00:24.000
Marcus (Contoso): Decision from our side - we are standardizing on workload identity.

00:00:25.000 --> 00:00:33.000
Dan (Microsoft): One risk to flag: your hub firewall SKU may not support the egress rules AKS needs.
`
);
const MD = "/tmp/2026-07-16-contoso-aks-call.md";
writeFileSync(
  MD,
  `# Contoso AKS design session — 2026-07-16

Attendees: Dan (Microsoft), Priya (Contoso), Marcus (Contoso)

- ASK: cost estimate for private endpoints before Friday security review (Priya)
- DECISION: Contoso standardizes on workload identity (no pod-managed identity)
- RISK: hub firewall SKU may not support required AKS egress rules
`
);

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1480, height: 1000 } });
const p = await ctx.newPage();
p.on("pageerror", (e) => console.log("  [pageerror]", String(e.message).slice(0, 140)));

const shot = async (n) => {
  await p.waitForTimeout(600);
  await p.screenshot({ path: `${OUT}/${n}.png` });
  console.log("  📸", n);
};

// ── sign in
await p.goto(APP, { waitUntil: "networkidle" });
await shot("00-signin");
await p.locator('[data-testid="signin-username"]').fill("dan");
const demoPassword = process.env.DEMO_PASSWORD;
if (!demoPassword) throw new Error("DEMO_PASSWORD required");
await p.locator('[data-testid="signin-password"]').fill(demoPassword);
await p.locator('[data-testid="signin-submit"]').click();
await p.waitForSelector('[data-testid="workbench-app"]', { timeout: 20000 });
await p.waitForTimeout(2500);

// ── discover surfaces
const navIds = await p.$$eval("[data-testid^=nav--]", (els) =>
  els.map((e) => e.getAttribute("data-testid"))
);
console.log("NAV:", JSON.stringify(navIds));
const engIds = await p.$$eval("[data-testid*=engagement]", (els) =>
  els.slice(0, 15).map((e) => e.getAttribute("data-testid"))
);
console.log("ENGAGEMENT-TESTIDS:", JSON.stringify(engIds));

// ── sweep every nav surface
let i = 1;
for (const id of navIds) {
  const name = id.replace("nav--", "");
  await p.click(`[data-testid=${id}]`).catch(() => {});
  await p.waitForTimeout(1200);
  await shot(`${String(i).padStart(2, "0")}-surface-${name}`);
  i++;
}

// ── home detail: body text for the report
await p.click(`[data-testid=${navIds[0]}]`).catch(() => {});
await p.waitForTimeout(800);
const homeText = await p.evaluate(() => document.body.innerText.slice(0, 1200));
console.log("HOME-TEXT:", JSON.stringify(homeText));

// ── agent turn helper
async function agentTurn(msg, maxMs = 170000) {
  console.log("→ agent:", msg.slice(0, 90));
  const before = await p.locator('[data-testid="turn-meta"]').count();
  await p.locator('[data-testid="chat-input"]').fill(msg);
  await p.locator('[data-testid="send-button"]').click();
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    await p.waitForTimeout(1500);
    if ((await p.locator('[data-testid="turn-meta"]').count()) > before) break;
  }
  await p.waitForTimeout(1200);
}

// ── journeys
await agentTurn(
  "Add a high-priority task 'Send private-endpoint cost estimate to Contoso' due Friday"
);
await shot("20-agent-task-created");

await agentTurn("what needs my attention today?");
await shot("21-agent-orient-answer");

// ── uploads: go to the documents-ish surface
const docNav = navIds.find((n) => /doc/i.test(n)) || navIds[0];
await p.click(`[data-testid=${docNav}]`).catch(() => {});
await p.waitForTimeout(1000);
const fi = await p.$("input[type=file]");
if (fi) {
  await fi.setInputFiles(VTT);
  await p.waitForTimeout(4000);
  await shot("22-after-vtt-upload");
  await fi.setInputFiles(MD).catch(async () => {
    const fi2 = await p.$("input[type=file]");
    if (fi2) await fi2.setInputFiles(MD);
  });
  await p.waitForTimeout(4000);
  await shot("23-after-md-upload");
} else {
  console.log("  ⚠ no file input found on", docNav);
  await shot("22-no-file-input");
}

await agentTurn(
  "Read the Contoso meeting notes I uploaded and tell me: what did the customer ask for, what did they decide, and what risk was flagged?"
);
await shot("24-meeting-grounded-answer");

const sid = await p.evaluate(() => sessionStorage.getItem("flow_session_id"));
console.log("SESSION:", sid);
await ctx.close();
await b.close();
console.log("done");
