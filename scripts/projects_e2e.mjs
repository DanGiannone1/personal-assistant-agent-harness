// Full-journey validation for docs/projects-spec.md M1–M5 — real frontend, real users,
// screenshots at every checkpoint. Run with the dev stack up (uv run dev.py) against
// the Cosmos emulator. Usage: node scripts/projects_e2e.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const APP = "http://localhost:3000";
const OUT = "screenshots/projects-e2e";
mkdirSync(OUT, { recursive: true });

const b = await chromium.launch({ headless: true });
let failures = 0;
const ok = (name, cond, extra = "") => {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${extra ? ` — ${extra}` : ""}`);
  if (!cond) failures++;
};

async function fresh() {
  const ctx = await b.newContext({ viewport: { width: 1480, height: 1000 } });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => console.log("  [pageerror]", String(e.message).slice(0, 120)));
  return { ctx, p };
}

async function signIn(p, user) {
  await p.goto(APP, { waitUntil: "networkidle" });
  await p.locator('[data-testid="signin-username"]').fill(user);
  await p.locator('[data-testid="signin-password"]').fill("demo1234");
  await p.locator('[data-testid="signin-submit"]').click();
  await p.waitForSelector('[data-testid="workbench-app"]', { timeout: 20000 });
  await p.waitForTimeout(2500); // session init + first state fetch
}

async function agentTurn(p, msg, maxMs = 90000) {
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

// ── M1: sign-in, isolation, wrong password ───────────────────────────────────
{
  const { ctx, p } = await fresh();
  await p.goto(APP, { waitUntil: "networkidle" });
  ok("M1 sign-in screen gates the app", await p.locator('[data-testid="signin-form"]').count() === 1);
  await p.locator('[data-testid="signin-username"]').fill("dan");
  await p.locator('[data-testid="signin-password"]').fill("wrong");
  await p.locator('[data-testid="signin-submit"]').click();
  await p.waitForSelector('[data-testid="signin-error"]', { timeout: 10000 });
  ok("M1 wrong password fails loud", true);
  await p.screenshot({ path: `${OUT}/m1-signin-error.png` });

  await signIn(p, "dan");
  const chip = await p.locator('[data-testid="user-chip-name"]').innerText();
  ok("M1 dan signed in", chip.includes("Dan"), chip);
  await p.screenshot({ path: `${OUT}/m1-dan-home.png` });
  await ctx.close();

  const { ctx: c2, p: p2 } = await fresh();
  await signIn(p2, "ava");
  const chip2 = await p2.locator('[data-testid="user-chip-name"]').innerText();
  ok("M1 ava signed in separately", chip2.includes("Ava"), chip2);
  await p2.screenshot({ path: `${OUT}/m1-ava-home.png` });
  await c2.close();
}

// ── M2: projects, roles, viewer can't mutate ────────────────────────────────
{
  const { ctx, p } = await fresh();
  await signIn(p, "dan");
  await p.locator('[data-testid="nav--projects"]').click();
  await p.waitForTimeout(800);
  await p.screenshot({ path: `${OUT}/m2-dan-projects.png` });
  ok("M2 dan sees Website Launch", await p.locator('[data-testid="project-row-proj-website-launch"]').count() === 1);
  ok("M2 dan sees Product Launch", await p.locator('[data-testid="project-row-proj-product-launch"]').count() === 1);
  ok("M2 dan does NOT see Q3 Budget", await p.locator('[data-testid="project-row-proj-q3-budget"]').count() === 0);

  // Editor adds a task in Product Launch
  await p.locator('[data-testid="project-row-proj-product-launch"]').click();
  await p.waitForTimeout(700);
  await p.locator('[data-testid="project-tab-tasks"]').click();
  await p.waitForTimeout(500);
  await p.locator('[data-testid="project-add-task-btn"]').click();
  await p.locator('[data-testid="project-task-title-input"]').fill("E2E editor task");
  await p.locator('[data-testid="project-task-save-btn"]').click();
  await p.waitForTimeout(1500);
  ok("M2 editor created project task", await p.getByText("E2E editor task").count() >= 1);
  await p.screenshot({ path: `${OUT}/m2-editor-task.png` });
  await ctx.close();

  // sam is viewer on Website Launch: no add button, viewer note shown
  const { ctx: c2, p: p2 } = await fresh();
  await signIn(p2, "sam");
  await p2.locator('[data-testid="nav--projects"]').click();
  await p2.waitForTimeout(700);
  ok("M2 sam sees Website Launch (viewer)", await p2.locator('[data-testid="project-row-proj-website-launch"]').count() === 1);
  ok("M2 sam does NOT see Product Launch", await p2.locator('[data-testid="project-row-proj-product-launch"]').count() === 0);
  await p2.locator('[data-testid="project-row-proj-website-launch"]').click();
  await p2.waitForTimeout(600);
  await p2.locator('[data-testid="project-tab-tasks"]').click();
  await p2.waitForTimeout(500);
  ok("M2 viewer has no add-task button", await p2.locator('[data-testid="project-add-task-btn"]').count() === 0);
  ok("M2 viewer sees view-only note", await p2.locator('[data-testid="viewer-note"]').count() === 1);
  await p2.screenshot({ path: `${OUT}/m2-sam-viewer.png` });
  await c2.close();
}

// ── M3: the money demo — same utterance, different user, different landing ──
{
  // dan builds recency in Website Launch (clicks), then asks ambiguously.
  const { ctx, p } = await fresh();
  await signIn(p, "dan");
  await p.locator('[data-testid="nav--projects"]').click();
  await p.waitForTimeout(500);
  await p.locator('[data-testid="project-row-proj-website-launch"]').click();
  await p.waitForTimeout(600);
  await p.locator('[data-testid="project-tab-tasks"]').click();
  await p.waitForTimeout(800); // visits recorded

  await agentTurn(p, "take me to the launch tasks");
  const crumb = await p.locator('[data-testid="breadcrumb"]').innerText();
  ok("M3 dan lands in Website Launch tasks (recency)", crumb.includes("Website Launch"), crumb);
  await p.screenshot({ path: `${OUT}/m3-dan-landing.png` });

  // Quick links reflect the visit log
  await p.locator('[data-testid="nav--home"]').click();
  await p.waitForTimeout(1200);
  const ql = await p.locator('[data-testid="home-quicklinks"]').innerText().catch(() => "");
  ok("M3 dan quick links show Website Launch", ql.includes("Website Launch"), ql.slice(0, 80));
  await ctx.close();

  // ava's recency is Product Launch → same words, different landing.
  const { ctx: c2, p: p2 } = await fresh();
  await signIn(p2, "ava");
  await p2.locator('[data-testid="nav--projects"]').click();
  await p2.waitForTimeout(500);
  await p2.locator('[data-testid="project-row-proj-product-launch"]').click();
  await p2.waitForTimeout(600);
  await p2.locator('[data-testid="project-tab-tasks"]').click();
  await p2.waitForTimeout(800);

  await agentTurn(p2, "take me to the launch tasks");
  const crumb2 = await p2.locator('[data-testid="breadcrumb"]').innerText();
  ok("M3 ava lands in Product Launch tasks (recency)", crumb2.includes("Product Launch"), crumb2);
  await p2.screenshot({ path: `${OUT}/m3-ava-landing.png` });
  await c2.close();
}

// ── M4: confirm-first delete + card, standing approvals ─────────────────────
{
  const { ctx, p } = await fresh();
  await signIn(p, "dan");
  // Create a throwaway personal task via the agent (also checks the record card).
  await agentTurn(p, "create a task called Disposable e2e probe");
  ok("M4 record card rendered on create", await p.locator('[data-testid="record-card"]').count() >= 1);
  // Ask to delete → PENDING_CONFIRM card, nothing deleted yet.
  await agentTurn(p, "delete the task Disposable e2e probe");
  ok("M4 confirm card shown", await p.locator('[data-testid="confirm-card"]').count() >= 1);
  await p.locator('[data-testid="nav--todo"]').click();
  await p.waitForTimeout(800);
  ok("M4 task still exists before confirm", await p.getByText("Disposable e2e probe").count() >= 1);
  await p.screenshot({ path: `${OUT}/m4-confirm-pending.png` });
  // Confirm via the card button.
  await p.locator('[data-testid="confirm-card-yes"]').last().click();
  await p.waitForTimeout(15000); // agent re-calls with confirmed=true
  await p.locator('[data-testid="nav--todo"]').click();
  await p.waitForTimeout(1000);
  ok("M4 task deleted after confirm", await p.getByText("Disposable e2e probe").count() === 0);
  await p.screenshot({ path: `${OUT}/m4-after-confirm.png` });
  await ctx.close();
}

// ── M5: persona/memory/conventions + inspector ──────────────────────────────
{
  const { ctx, p } = await fresh();
  await signIn(p, "dan");
  await p.locator('[data-testid="nav--settings"]').click();
  await p.waitForTimeout(700);
  ok("M5 settings screen renders", await p.locator('[data-testid="settings-screen"]').count() === 1);
  await p.locator('[data-testid="memory-input"]').fill("Weekly reviews happen on Fridays");
  await p.locator('[data-testid="memory-add"]').click();
  await p.waitForTimeout(1200);
  ok("M5 manual memory saved + listed", (await p.locator('[data-testid="memory-list"]').innerText()).includes("Fridays"));
  await p.screenshot({ path: `${OUT}/m5-settings.png` });

  // Turn in a French-convention project: inspector shows convention + precedence.
  await p.locator('[data-testid="nav--projects"]').click();
  await p.waitForTimeout(500);
  await p.locator('[data-testid="project-row-proj-product-launch"]').click();
  await p.waitForTimeout(700);
  await agentTurn(p, "what tasks are in this project?");
  const insp = await p.locator('[data-testid="context-inspector"]').innerText().catch(() => "");
  ok("M5 inspector shows the French convention", insp.includes("French"), insp.slice(0, 100));
  ok("M5 inspector shows memory", insp.includes("Fridays"));
  ok("M5 inspector states precedence", insp.toLowerCase().includes("precedence") || insp.includes("›"));
  await p.locator('[data-testid="context-inspector"] summary').click();
  await p.screenshot({ path: `${OUT}/m5-inspector.png` });
  await ctx.close();
}

await b.close();
console.log(failures === 0 ? "\nALL CHECKPOINTS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
