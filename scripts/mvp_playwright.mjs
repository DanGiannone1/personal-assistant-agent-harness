/*
 * MVP real-browser evidence: UI assertions are reconciled with /app/state and
 * typed SSE events.  It never treats assistant prose or a rendered tool label as
 * success.  Run only against the local demo stack:
 *
 * MVP_RESET_BEFORE_RUN=1 IDENTITY_MODE=demo DEMO_PASSWORD=... npm run playwright:mvp
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { chromium } from "@playwright/test";
import { evaluateCase, evidencePath, parseSse, requireCleanWorktree, requireLoopbackUrl, terminalEvents } from "./mvp_evidence.mjs";

const startedAt = new Date().toISOString();
const APP = requireLoopbackUrl(process.env.MVP_APP_URL || "http://localhost:3000", "MVP_APP_URL");
const API = requireLoopbackUrl(process.env.MVP_API_URL || "http://localhost:8000", "MVP_API_URL");
const runId = process.env.MVP_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-") + `-${randomUUID().slice(0, 8)}`;
const out = evidencePath("playwright", runId);
if (!process.env.DEMO_PASSWORD) throw new Error("DEMO_PASSWORD is required; this runner never supplies a static password.");
if (process.env.MVP_RESET_BEFORE_RUN !== "1") throw new Error("Set MVP_RESET_BEFORE_RUN=1; browser evidence starts only after a guarded fixture reset.");

function resetFixture() {
  const output = execFileSync("uv", ["run", "python", "scripts/reset_demo_state.py"], {
    env: { ...process.env, CONFIRM_DEMO_RESET: "YES" }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  return JSON.parse(output.split("\n").at(-1));
}

const checks = [];
function check(id, pass, detail = "") { checks.push({ id, pass: !!pass, detail }); console.log(`${pass ? "PASS" : "FAIL"} ${id}${detail ? ` — ${detail}` : ""}`); }
async function eventually(predicate, timeout = 15_000) {
  const until = Date.now() + timeout;
  let last;
  while (Date.now() < until) { last = await predicate(); if (last) return last; await new Promise((resolve) => setTimeout(resolve, 250)); }
  throw new Error(`Timed out waiting for condition: ${last ?? "false"}`);
}
async function signIn(page, username) {
  await page.goto(APP, { waitUntil: "networkidle" });
  await page.getByTestId("signin-username").fill(username);
  await page.getByTestId("signin-password").fill(process.env.DEMO_PASSWORD);
  await page.getByTestId("signin-submit").click();
  await page.getByTestId("workbench-app").waitFor({ state: "visible", timeout: 20_000 });
  await eventually(() => page.evaluate(() => Object.keys(sessionStorage).some((key) => key.startsWith("flow_session_id:"))));
}
async function sessionId(page) {
  return page.evaluate(() => Object.entries(sessionStorage).find(([key]) => key.startsWith("flow_session_id:"))?.[1] ?? null);
}
async function state(page) {
  const sid = await sessionId(page);
  if (!sid) throw new Error("browser did not establish an owned session");
  return page.evaluate(async ({ api, sid }) => {
    const token = localStorage.getItem("pa_auth_token");
    const response = await fetch(`${api}/sessions/${sid}/app/state`, { headers: token ? { "X-Auth-Token": token } : {} });
    if (!response.ok) throw new Error(`state ${response.status}`);
    return response.json();
  }, { api: API, sid });
}
async function raw(page, path, method, body) {
  return page.evaluate(async ({ api, path, method, body }) => {
    const token = localStorage.getItem("pa_auth_token");
    const response = await fetch(`${api}${path}`, { method, headers: { "content-type": "application/json", ...(token ? { "X-Auth-Token": token } : {}) }, body: body ? JSON.stringify(body) : undefined });
    return { status: response.status, text: await response.text() };
  }, { api: API, path, method, body });
}
async function noHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth);
}
async function newPage(browser, viewport, user) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await signIn(page, user);
  return { context, page, errors };
}

mkdirSync(out, { recursive: true });
const report = { schemaVersion: 1, kind: "mvp-playwright", runId, sourceRevision: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(), fixture: null, environment: "local-synthetic", harness: process.env.AGENT_BACKEND || "deepagents", model: process.env.AZURE_DEPLOYMENT || "UNSPECIFIED", app: APP, api: API, startedAt };
let browser;

try {
  requireCleanWorktree(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }));
  report.fixture = resetFixture();
  browser = await chromium.launch({ headless: process.env.MVP_HEADLESS !== "0" });
  const dan = await newPage(browser, { width: 1440, height: 900 }, "dan");
  const ava = await newPage(browser, { width: 1440, height: 900 }, "ava");
  const sam = await newPage(browser, { width: 1024, height: 768 }, "sam");
  const danSeed = await state(dan.page);
  const avaSeed = await state(ava.page);
  const danIds = (danSeed.engagements ?? []).map((entry) => entry.id).sort();
  const avaIds = (avaSeed.engagements ?? []).map((entry) => entry.id).sort();
  check("MVP-P1-distinct-personal-portfolios", JSON.stringify(danIds) !== JSON.stringify(avaIds), `dan=${danIds.join(",")} ava=${avaIds.join(",")}`);
  await dan.page.screenshot({ path: `${out}/wide-dan-portfolio.png`, fullPage: true });
  check("MVP-P2-wide-no-horizontal-overflow", await noHorizontalOverflow(dan.page));

  await dan.page.getByTestId("add-engagement-btn").click();
  await dan.page.getByTestId("engagement-name-input").fill("MVP Browser Collaboration");
  await dan.page.getByTestId("engagement-customer-input").fill("Synthetic Evidence Co");
  await dan.page.getByTestId("engagement-save-btn").click();
  const created = await eventually(async () => (await state(dan.page)).engagements.find((entry) => entry.name === "MVP Browser Collaboration"));
  const engagementId = created.id;
  check("MVP-P3-create-authoritative-owner", created.members.some((member) => member.userId === "dan" && member.role === "owner"), engagementId);
  check("MVP-P4-create-rendered", await eventually(() => dan.page.getByTestId("engagement-overview").count().then((count) => count === 1)));

  await dan.page.getByTestId("engagement-tab-settings").click();
  await dan.page.getByTestId("member-user-select").selectOption("ava");
  await dan.page.getByTestId("member-role-select").selectOption("editor");
  await dan.page.getByTestId("member-add-btn").click();
  await eventually(async () => (await state(dan.page)).engagements.find((entry) => entry.id === engagementId)?.members.some((member) => member.userId === "ava" && member.role === "editor"));
  check("MVP-P5-owner-shares-editor", true);
  await dan.page.screenshot({ path: `${out}/wide-owner-shared-engagement.png`, fullPage: true });

  // Ava was mounted before the share. Reload to exercise a real state/session
  // refetch rather than treating an active navigation click as one.
  await ava.page.reload({ waitUntil: "networkidle" });
  await ava.page.getByTestId("engagements-screen").waitFor({ state: "visible" });
  await eventually(() => ava.page.getByTestId(`engagement-row-${engagementId}`).count());
  await ava.page.getByTestId(`engagement-row-${engagementId}`).click();
  check("MVP-P6-editor-sees-durable-record", await ava.page.getByTestId("engagement-detail-editor").count() === 1);
  await ava.page.getByTestId("engagement-description-edit").fill("Edited by Ava through the real UI.");
  await ava.page.getByRole("button", { name: "Save delivery record" }).click();
  const avaEdited = await eventually(async () => (await state(ava.page)).engagements.find((entry) => entry.id === engagementId)?.description === "Edited by Ava through the real UI.");
  check("MVP-P7-editor-ui-change-authoritative", avaEdited);
  await dan.page.getByTestId("nav--engagements").click();
  await dan.page.getByTestId(`engagement-row-${engagementId}`).click();
  await eventually(() => dan.page.getByTestId("engagement-description-edit").inputValue().then((value) => value === "Edited by Ava through the real UI."));
  check("MVP-P8-owner-authoritative-refresh", true);

  const samList = await raw(sam.page, "/engagements", "GET");
  const samRead = await raw(sam.page, `/engagements/${engagementId}`, "GET");
  const beforeForged = await state(dan.page);
  const samWrite = await raw(sam.page, `/engagements/${engagementId}`, "PATCH", { description: "forged outsider write" });
  const afterForged = await state(dan.page);
  check("MVP-P9-outsider-list-hides-record", !samList.text.includes(engagementId));
  check("MVP-P10-outsider-direct-read-neutral-404", samRead.status === 404, String(samRead.status));
  check("MVP-P11-outsider-forged-write-neutral-404", samWrite.status === 404, String(samWrite.status));
  check("MVP-P12-outsider-write-unchanged-state", JSON.stringify(beforeForged.engagements.find((entry) => entry.id === engagementId)) === JSON.stringify(afterForged.engagements.find((entry) => entry.id === engagementId)));

  await sam.page.getByTestId("nav-toggle").click();
  await sam.page.getByTestId("nav-drawer").waitFor({ state: "visible" });
  await sam.page.getByTestId("nav--engagements").click();
  await sam.page.getByTestId("engagement-row-eng-website-launch").click();
  check("MVP-P13-viewer-has-no-editor-affordance", await sam.page.getByTestId("engagement-detail-editor").count() === 0);
  check("MVP-P14-viewer-note-visible", await sam.page.getByTestId("viewer-note").count() === 1);
  await sam.page.screenshot({ path: `${out}/compact-sam-viewer.png`, fullPage: true });
  check("MVP-P15-compact-no-horizontal-overflow", await noHorizontalOverflow(sam.page));

  // A manual validation path is visible and leaves the committed record unchanged.
  await ava.page.getByTestId("status-select").selectOption("red");
  await ava.page.getByTestId("status-note-input").fill("");
  await ava.page.getByRole("button", { name: "Save delivery record" }).click();
  check("MVP-P16-validation-visible", await ava.page.getByRole("alert").count() > 0);
  check("MVP-P17-validation-no-state-change", (await state(ava.page)).engagements.find((entry) => entry.id === engagementId)?.status === "green");

  // Capture the real SSE payload from the browser turn, then require a structured
  // committed result and the corresponding authoritative state.  The rendered label
  // and assistant response are intentionally not examined as the oracle.
  const sseBodies = [];
  dan.page.on("response", async (response) => {
    if (response.url().includes(`/sessions/`) && response.url().endsWith("/messages")) {
      try { sseBodies.push(await response.text()); } catch { /* recorded as missing below */ }
    }
  });
  const turnMetaBefore = await dan.page.getByTestId("turn-meta").count();
  const agentBefore = await state(dan.page);
  await dan.page.getByTestId("chat-input").fill(`Set Engagement ${engagementId} to Yellow with reason 'Agent structured evidence refresh'. Use the supported product tool.`);
  await dan.page.getByTestId("send-button").click();
  await eventually(async () => (await dan.page.getByTestId("turn-meta").count()) > turnMetaBefore, 180_000);
  const events = await eventually(() => {
    for (const body of sseBodies) {
      const candidate = parseSse(body);
      if (terminalEvents(candidate).length === 1 && candidate.at(-1) === terminalEvents(candidate)[0]) return candidate;
    }
    return null;
  }, 30_000);
  const agentState = await state(dan.page);
  const agentOracle = evaluateCase({
    expectation: {
      operation: "update", status: "committed", resourceId: engagementId, stateChanged: true,
      onlyEngagementMayChange: engagementId,
      exactEngagementUpdate: { id: engagementId, actor: "dan", detail: "status, statusNote" },
      engagementAfter: { id: engagementId, status: "yellow", statusNote: "Agent structured evidence refresh" },
    },
    before: agentBefore, after: agentState, events,
  });
  report.agentMutationOracle = agentOracle;
  check("MVP-P18-agent-e4-oracle", agentOracle.pass, JSON.stringify(agentOracle.checks));
  check("MVP-P20-agent-ui-refreshed", await dan.page.getByTestId("engagement-status-badge").innerText().then((value) => value.trim().toLowerCase() === "yellow"));
  await dan.page.screenshot({ path: `${out}/wide-agent-updated-engagement.png`, fullPage: true });

  const narrow = await newPage(browser, { width: 390, height: 844 }, "dan");
  await narrow.page.getByTestId("nav-toggle").click();
  check("MVP-P21-narrow-drawer-opens", await narrow.page.getByTestId("nav-drawer").count() === 1);
  check("MVP-P22-narrow-drawer-focuses", await narrow.page.evaluate(() => document.activeElement?.closest("#workbench-nav") !== null));
  await narrow.page.screenshot({ path: `${out}/narrow-dan-drawer-open.png`, fullPage: true });
  await narrow.page.keyboard.press("Escape");
  check("MVP-P23-narrow-escape-restores-focus", await narrow.page.getByTestId("nav-toggle").evaluate((element) => document.activeElement === element));
  check("MVP-P24-narrow-no-horizontal-overflow", await noHorizontalOverflow(narrow.page));
  const critical = await narrow.page.getByTestId("nav-toggle").boundingBox();
  check("MVP-P25-narrow-critical-control-not-clipped", !!critical && critical.x >= 0 && critical.y >= 0 && critical.x + critical.width <= 390 && critical.y + critical.height <= 844);
  await narrow.page.screenshot({ path: `${out}/narrow-dan-workspace.png`, fullPage: true });

  report.pageErrors = { dan: dan.errors, ava: ava.errors, sam: sam.errors, narrow: narrow.errors };
  check("MVP-P26-no-page-errors", Object.values(report.pageErrors).every((errors) => errors.length === 0), JSON.stringify(report.pageErrors));
  await Promise.all([dan.context.close(), ava.context.close(), sam.context.close(), narrow.context.close()]);
} catch (error) {
  report.fatalError = error instanceof Error ? error.message : String(error);
  check("MVP-P-FATAL", false, report.fatalError);
} finally {
  if (browser) await browser.close();
  report.checks = checks;
  report.summary = { passed: checks.filter((item) => item.pass).length, failed: checks.filter((item) => !item.pass).map((item) => item.id) };
  writeFileSync(`${out}/results.json`, JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ evidence: `${out}/results.json`, ...report.summary }, null, 2));
process.exitCode = report.summary.failed.length ? 1 : 0;
