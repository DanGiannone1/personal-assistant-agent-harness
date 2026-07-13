// Full-journey validation for docs/projects-spec.md M1–M5 — real frontend, real users,
// screenshots at every checkpoint. Run with the dev stack up (uv run dev.py) against
// the Cosmos emulator. Usage: node scripts/engagements_e2e.mjs
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const APP = "http://localhost:3000";
const OUT = "screenshots/engagements-e2e";
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

async function agentTurn(p, msg, maxMs = 150000) {
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

// ── M2: engagements, roles, viewer can't mutate ────────────────────────────────
{
  const { ctx, p } = await fresh();
  await signIn(p, "dan");
  await p.locator('[data-testid="nav--engagements"]').click();
  await p.waitForTimeout(800);
  await p.screenshot({ path: `${OUT}/m2-dan-engagements.png` });
  ok("M2 dan sees Website Launch", await p.locator('[data-testid="engagement-row-eng-website-launch"]').count() === 1);
  ok("M2 dan sees Product Launch", await p.locator('[data-testid="engagement-row-eng-product-launch"]').count() === 1);
  ok("M2 dan does NOT see Q3 Budget", await p.locator('[data-testid="engagement-row-eng-q3-budget"]').count() === 0);

  // Editor adds a task in Product Launch
  await p.locator('[data-testid="engagement-row-eng-product-launch"]').click();
  await p.waitForTimeout(700);
  await p.locator('[data-testid="engagement-tab-tasks"]').click();
  await p.waitForTimeout(500);
  await p.locator('[data-testid="engagement-add-task-btn"]').click();
  await p.locator('[data-testid="engagement-task-title-input"]').fill("E2E editor task");
  await p.locator('[data-testid="engagement-task-save-btn"]').click();
  await p.waitForTimeout(1500);
  ok("M2 editor created engagement task", await p.locator('[data-testid^="engagement-task-row-"]').filter({ hasText: "E2E editor task" }).count() >= 1);
  await p.screenshot({ path: `${OUT}/m2-editor-task.png` });
  // Cleanup: remove the probe task (armed two-click delete) so reruns stay net-zero.
  const row = p.locator('[data-testid^="engagement-task-row-"]').filter({ hasText: "E2E editor task" }).first();
  const delBtn = row.locator('[data-testid^="engagement-task-delete-"]');
  const delId = await delBtn.getAttribute("data-testid").catch(() => null);
  if (delId) {
    await delBtn.click();
    await p.locator(`[data-testid="${delId}-confirm"]`).click();
    await p.waitForTimeout(1200);
  }
  await ctx.close();

  // sam is viewer on Website Launch: no add button, viewer note shown
  const { ctx: c2, p: p2 } = await fresh();
  await signIn(p2, "sam");
  await p2.locator('[data-testid="nav--engagements"]').click();
  await p2.waitForTimeout(700);
  ok("M2 sam sees Website Launch (viewer)", await p2.locator('[data-testid="engagement-row-eng-website-launch"]').count() === 1);
  ok("M2 sam does NOT see Product Launch", await p2.locator('[data-testid="engagement-row-eng-product-launch"]').count() === 0);
  await p2.locator('[data-testid="engagement-row-eng-website-launch"]').click();
  await p2.waitForTimeout(600);
  await p2.locator('[data-testid="engagement-tab-tasks"]').click();
  await p2.waitForTimeout(500);
  ok("M2 viewer has no add-task button", await p2.locator('[data-testid="engagement-add-task-btn"]').count() === 0);
  ok("M2 viewer sees view-only note", await p2.locator('[data-testid="viewer-note"]').count() === 1);
  await p2.screenshot({ path: `${OUT}/m2-sam-viewer.png` });
  await c2.close();
}

// ── M3: the money demo — same utterance, different user, different landing ──
{
  // dan builds recency in Website Launch (clicks), then asks ambiguously.
  const { ctx, p } = await fresh();
  await signIn(p, "dan");
  await p.locator('[data-testid="nav--engagements"]').click();
  await p.waitForTimeout(500);
  await p.locator('[data-testid="engagement-row-eng-website-launch"]').click();
  await p.waitForTimeout(600);
  await p.locator('[data-testid="engagement-tab-tasks"]').click();
  await p.waitForTimeout(800); // visits recorded

  await agentTurn(p, "take me to the launch tasks");
  const crumb = await p.locator('[data-testid="breadcrumb"]').innerText();
  // Sound assertion: the TOOL must have decided (trace says Navigated) — a breadcrumb
  // alone can pass vacuously when the user was already standing on the target page.
  const lastStep = await p.locator(".step-label").last().innerText().catch(() => "");
  ok("M3 dan's navigate DECIDED (no interrogation)", lastStep.includes("Navigated"), lastStep);
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
  await p2.locator('[data-testid="nav--engagements"]').click();
  await p2.waitForTimeout(500);
  await p2.locator('[data-testid="engagement-row-eng-product-launch"]').click();
  await p2.waitForTimeout(600);
  await p2.locator('[data-testid="engagement-tab-tasks"]').click();
  await p2.waitForTimeout(800);

  await agentTurn(p2, "take me to the launch tasks");
  const crumb2 = await p2.locator('[data-testid="breadcrumb"]').innerText();
  const lastStep2 = await p2.locator(".step-label").last().innerText().catch(() => "");
  ok("M3 ava's navigate DECIDED", lastStep2.includes("Navigated"), lastStep2);
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
  const probeRow = () => p.locator('[data-testid^="task-row-"]').filter({ hasText: "Disposable e2e probe" });
  ok("M4 task still exists before confirm", await probeRow().count() === 1);
  await p.screenshot({ path: `${OUT}/m4-confirm-pending.png` });
  // Confirm via the card button (guarded: a missing card already failed above).
  if (await p.locator('[data-testid="confirm-card-yes"]').count()) {
    await p.locator('[data-testid="confirm-card-yes"]').last().click();
    const t0 = Date.now();
    while (Date.now() - t0 < 120000) {
      await p.waitForTimeout(2500);
      await p.locator('[data-testid="nav--todo"]').click().catch(() => {});
      await p.waitForTimeout(700);
      if (await probeRow().count() === 0) break;
    }
  }
  await p.locator('[data-testid="nav--todo"]').click();
  await p.waitForTimeout(1000);
  ok("M4 task deleted after confirm", await probeRow().count() === 0);
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

  // Turn in a French-convention engagement: inspector shows convention + precedence.
  await p.locator('[data-testid="nav--engagements"]').click();
  await p.waitForTimeout(500);
  await p.locator('[data-testid="engagement-row-eng-product-launch"]').click();
  await p.waitForTimeout(700);
  await agentTurn(p, "what tasks are in this engagement?");
  await p.locator('[data-testid="context-inspector"] summary').click().catch(() => {});
  await p.waitForTimeout(400);
  const insp = await p.locator('[data-testid="context-inspector"]').innerText().catch(() => "");
  ok("M5 inspector shows the French convention", insp.includes("French"), insp.slice(0, 100));
  ok("M5 inspector shows memory", insp.includes("Fridays"));
  ok("M5 inspector states precedence", insp.toLowerCase().includes("precedence") || insp.includes("›"));
  await p.screenshot({ path: `${OUT}/m5-inspector.png` });
  await ctx.close();
}

// ── M6: the delivery record — health-with-a-why, milestones, stat tiles ─────
{
  const { ctx, p } = await fresh();
  await signIn(p, "dan");
  await p.locator('[data-testid="nav--engagements"]').click();
  await p.waitForTimeout(600);

  // List shows the seeded amber + fleet tiles.
  ok("M6 list stat tiles render", await p.locator('[data-testid="eng-stat-amber"]').count() === 1);
  const amberTile = await p.locator('[data-testid="eng-stat-amber"]').innerText();
  ok("M6 amber tile counts the seeded amber", amberTile.includes("1"), amberTile);
  const wlHealth = await p.locator('[data-testid="engagement-health-eng-website-launch"]').innerText();
  ok("M6 Website Launch shows amber in the list", wlHealth.trim() === "amber", wlHealth);

  // Overview: health badge + the why from seed.
  await p.locator('[data-testid="engagement-row-eng-website-launch"]').click();
  await p.waitForTimeout(700);
  ok("M6 overview health badge is amber",
    (await p.locator('[data-testid="engagement-health-badge"]').innerText()).trim() === "amber");
  ok("M6 overview shows the why",
    (await p.locator('[data-testid="engagement-health-note"]').innerText()).includes("CMS migration"));
  ok("M6 milestone stat shows done/total",
    (await p.locator('[data-testid="stat-milestones"]').innerText()).includes("1/2"));

  // amber→red without a why is HELD client-side (nothing commits).
  await p.locator('[data-testid="health-select"]').selectOption("red");
  await p.locator('[data-testid="health-note-input"]').fill("");
  await p.waitForTimeout(300);
  ok("M6 red without a why is blocked client-side",
    await p.locator('[data-testid="health-commit-btn"]').isDisabled());
  ok("M6 hint explains the hold", await p.locator('[data-testid="health-note-hint"]').count() === 1);
  await p.reload({ waitUntil: "networkidle" });
  await p.waitForTimeout(1500);
  ok("M6 health unchanged after reload (nothing committed)",
    (await p.locator('[data-testid="engagement-health-badge"]').innerText()).trim() === "amber");
  await p.screenshot({ path: `${OUT}/m6-health-held.png` });

  // With a why it commits — and survives reload.
  await p.locator('[data-testid="health-select"]').selectOption("red");
  await p.locator('[data-testid="health-note-input"]').fill("e2e: cutover blocked by security review");
  await p.locator('[data-testid="health-commit-btn"]').click();
  await p.waitForTimeout(1500);
  await p.reload({ waitUntil: "networkidle" });
  await p.waitForTimeout(1500);
  ok("M6 red + why committed",
    (await p.locator('[data-testid="engagement-health-badge"]').innerText()).trim() === "red");
  ok("M6 why persisted",
    (await p.locator('[data-testid="engagement-health-note"]').innerText()).includes("security review"));

  // Add a milestone via the UI; the tile updates.
  await p.locator('[data-testid="add-milestone-btn"]').click();
  await p.locator('[data-testid="milestone-title-input"]').fill("e2e probe milestone");
  await p.locator('[data-testid="milestone-save-btn"]').click();
  await p.waitForTimeout(1200);
  ok("M6 milestone added",
    (await p.locator('[data-testid="milestones-table"]').innerText()).includes("e2e probe milestone"));
  ok("M6 milestone tile updated",
    (await p.locator('[data-testid="stat-milestones"]').innerText()).includes("1/3"));
  await p.screenshot({ path: `${OUT}/m6-delivery-record.png` });

  // Restore seed state so the suite stays re-runnable: back to amber + original why,
  // and remove the probe milestone.
  await p.locator('[data-testid="health-select"]').selectOption("amber");
  await p.locator('[data-testid="health-note-input"]')
    .fill("CMS migration slipped a week; launch date at risk until content freeze lands.");
  await p.locator('[data-testid="health-commit-btn"]').click();
  await p.waitForTimeout(1200);
  const probeRow = p.locator('[data-testid^="milestone-row-"]').filter({ hasText: "e2e probe milestone" });
  await probeRow.locator('[data-testid^="milestone-delete-"]').click();
  await probeRow.locator('[data-testid$="-confirm"]').click();
  await p.waitForTimeout(1200);
  ok("M6 probe milestone cleaned up",
    (await p.locator('[data-testid="stat-milestones"]').innerText()).includes("1/2"));

  // Viewer (sam) sees the record read-only: no editor, no add buttons.
  const { ctx: c2, p: p2 } = await fresh();
  await signIn(p2, "sam");
  await p2.locator('[data-testid="nav--engagements"]').click();
  await p2.waitForTimeout(600);
  await p2.locator('[data-testid="engagement-row-eng-website-launch"]').click();
  await p2.waitForTimeout(700);
  ok("M6 viewer sees no delivery-record editor",
    await p2.locator('[data-testid="engagement-detail-editor"]').count() === 0);
  ok("M6 viewer sees no add-milestone button",
    await p2.locator('[data-testid="add-milestone-btn"]').count() === 0);
  ok("M6 viewer still sees the why",
    (await p2.locator('[data-testid="engagement-health-note"]').innerText()).includes("CMS migration"));
  await p2.screenshot({ path: `${OUT}/m6-viewer-readonly.png` });
  await c2.close();
  await ctx.close();
}

await b.close();
console.log(failures === 0 ? "\nALL CHECKPOINTS PASSED" : `\n${failures} CHECK(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
