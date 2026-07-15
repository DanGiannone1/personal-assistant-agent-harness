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
async function capture(page, path) {
  await page.evaluate(async () => {
    await document.fonts?.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  await page.screenshot({ path, fullPage: true, animations: "disabled", caret: "hide" });
}
async function wideLayout(page) {
  return page.evaluate(() => {
    const box = (testid) => {
      const rect = document.querySelector(`[data-testid="${testid}"]`)?.getBoundingClientRect();
      return rect && { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    };
    const host = document.querySelector('[data-testid="host-shell"]');
    return host && {
      scrollLeft: host.scrollLeft,
      scrollWidth: host.scrollWidth,
      clientWidth: host.clientWidth,
      workbench: box("workbench-app"),
      dock: box("copilot-dock"),
    };
  });
}
function stableWideLayout(current, baseline) {
  const stableBox = (box, base) => !!box && !!base &&
    Math.abs(box.x - base.x) <= 1 && Math.abs(box.y - base.y) <= 1 &&
    Math.abs(box.width - base.width) <= 1 && Math.abs(box.height - base.height) <= 1;
  return !!current && current.scrollLeft === 0 && current.scrollWidth <= current.clientWidth &&
    stableBox(current.workbench, baseline.workbench) && stableBox(current.dock, baseline.dock);
}
async function signOutUnobstructed(page) {
  return page.getByTestId("sign-out").evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const target = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return target === element || element.contains(target);
  });
}
function intersects(first, second) {
  return !!first && !!second && first.x < second.x + second.width && first.x + first.width > second.x &&
    first.y < second.y + second.height && first.y + first.height > second.y;
}
function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value)
      .sort(([first], [second]) => first.localeCompare(second))
      .map(([key, item]) => [key, canonicalize(item)]));
  }
  return value;
}
function sameCanonical(first, second) {
  return JSON.stringify(canonicalize(first)) === JSON.stringify(canonicalize(second));
}
function engagementFrom(state, engagementId) {
  return (state.engagements ?? []).find((entry) => entry.id === engagementId) ?? null;
}
async function finalCardHitPoints(page) {
  return page.evaluate(() => {
    const finalCard = Array.from(document.querySelectorAll("[data-testid^='engagement-row-']")).at(-1);
    const finalCardTitle = finalCard?.querySelector(".tw-td-title");
    const bounds = (element) => {
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    };
    const atCenter = (name, element, intendedAncestor = null) => {
      const rect = bounds(element);
      if (!rect || rect.width <= 0 || rect.height <= 0) return { name, bounds: rect, resolves: false };
      const point = { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      const hit = document.elementFromPoint(point.x, point.y);
      const resolves = !!hit && (hit === element || element.contains(hit) || hit === intendedAncestor);
      return {
        name,
        bounds: rect,
        point,
        resolves,
        hit: hit && { tag: hit.tagName, testId: hit.getAttribute("data-testid") },
      };
    };
    return {
      card: bounds(finalCard),
      action: atCenter("final-card-action", finalCard),
      title: atCenter("final-card-title", finalCardTitle, finalCard),
    };
  });
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
  const fixturePortfolios = {
    dan: ["eng-product-launch", "eng-website-launch"],
    ava: ["eng-product-launch", "eng-q3-budget"],
  };
  const danIds = (danSeed.engagements ?? []).map((entry) => entry.id).sort();
  const avaIds = (avaSeed.engagements ?? []).map((entry) => entry.id).sort();
  check(
    "MVP-P1-deterministic-personal-portfolios",
    report.fixture?.fixtureVersion === "mvp-demo-v1" &&
      sameCanonical(danIds, fixturePortfolios.dan) &&
      sameCanonical(avaIds, fixturePortfolios.ava),
    `fixture=${report.fixture?.fixtureVersion ?? "missing"} expectedDan=${fixturePortfolios.dan.join(",")} dan=${danIds.join(",")} expectedAva=${fixturePortfolios.ava.join(",")} ava=${avaIds.join(",")}`,
  );
  await capture(dan.page, `${out}/wide-dan-portfolio.png`);
  check("MVP-P2-wide-no-horizontal-overflow", await noHorizontalOverflow(dan.page));

  await dan.page.getByTestId("add-engagement-btn").click();
  await dan.page.getByTestId("engagement-save-btn").click();
  const engagementNameError = dan.page.getByTestId("engagement-error");
  await engagementNameError.waitFor({ state: "visible" });
  const blankNameUiValid = await eventually(() => dan.page.getByTestId("engagement-name-input").evaluate((input) => input.getAttribute("aria-describedby") === "engagement-name-error" && document.activeElement === input));
  const blankNameState = await state(dan.page);
  check("MVP-P34-create-name-validation-accessible", await engagementNameError.isVisible() && blankNameUiValid && (blankNameState.engagements ?? []).length === danIds.length);
  await dan.page.getByTestId("engagement-name-input").fill("MVP Browser Collaboration");
  await dan.page.getByTestId("engagement-customer-input").fill("Synthetic Evidence Co");
  await dan.page.getByTestId("engagement-save-btn").click();
  const created = await eventually(async () => (await state(dan.page)).engagements.find((entry) => entry.name === "MVP Browser Collaboration"));
  const engagementId = created.id;
  check("MVP-P3-create-authoritative-owner", created.members.some((member) => member.userId === "dan" && member.role === "owner"), engagementId);
  check("MVP-P4-create-rendered", await eventually(() => dan.page.getByTestId("engagement-overview").count().then((count) => count === 1)));

  const taskCountBeforeBlankSave = (await state(dan.page)).engagements.find((entry) => entry.id === engagementId)?.tasks.length;
  await dan.page.getByTestId("engagement-tab-tasks").click();
  await dan.page.getByTestId("engagement-add-task-btn").click();
  await dan.page.getByTestId("engagement-task-save-btn").click();
  const engagementTaskTitleError = dan.page.getByTestId("engagement-task-title-error");
  await engagementTaskTitleError.waitFor({ state: "visible" });
  const blankTaskTitleUiValid = await eventually(() => dan.page.getByTestId("engagement-task-title-input").evaluate((input) => input.getAttribute("aria-describedby") === "engagement-task-title-error" && document.activeElement === input));
  const taskCountAfterBlankSave = (await state(dan.page)).engagements.find((entry) => entry.id === engagementId)?.tasks.length;
  check("MVP-P35-engagement-task-title-validation-accessible", await engagementTaskTitleError.isVisible() && blankTaskTitleUiValid && taskCountAfterBlankSave === taskCountBeforeBlankSave);

  await dan.page.getByTestId("engagement-tab-settings").click();
  await dan.page.getByTestId("member-user-select").selectOption("ava");
  await dan.page.getByTestId("member-role-select").selectOption("editor");
  await dan.page.getByTestId("member-add-btn").click();
  await eventually(async () => (await state(dan.page)).engagements.find((entry) => entry.id === engagementId)?.members.some((member) => member.userId === "ava" && member.role === "editor"));
  check("MVP-P5-owner-shares-editor", true);
  await capture(dan.page, `${out}/wide-owner-shared-engagement.png`);

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
  await sam.page.locator("#workbench-nav").waitFor({ state: "hidden" });
  await sam.page.getByTestId("engagement-row-eng-website-launch").click();
  await sam.page.getByRole("heading", { name: "Website Launch", exact: true }).waitFor({ state: "visible" });
  await sam.page.getByTestId("engagement-overview").waitFor({ state: "visible" });
  await sam.page.getByTestId("viewer-note").waitFor({ state: "visible" });
  check("MVP-P13-viewer-has-no-editor-affordance", await sam.page.getByTestId("engagement-detail-editor").count() === 0);
  check("MVP-P14-viewer-note-visible", await sam.page.getByTestId("viewer-note").isVisible());
  await capture(sam.page, `${out}/compact-sam-viewer.png`);
  check("MVP-P15-compact-no-horizontal-overflow", await noHorizontalOverflow(sam.page));

  // A manual validation path is visible and leaves the committed record unchanged.
  const beforeRejectedYellow = canonicalize(engagementFrom(await state(ava.page), engagementId));
  await ava.page.getByTestId("status-select").selectOption("yellow");
  await ava.page.getByTestId("status-note-input").fill("");
  await ava.page.getByRole("button", { name: "Save delivery record" }).click();
  check("MVP-P16-validation-visible", await ava.page.getByRole("alert").count() > 0);
  const afterRejectedYellow = canonicalize(engagementFrom(await state(ava.page), engagementId));
  report.rejectedYellowValidation = { engagementId, before: beforeRejectedYellow, after: afterRejectedYellow };
  check("MVP-P17-validation-no-state-change", !!beforeRejectedYellow && sameCanonical(beforeRejectedYellow, afterRejectedYellow));

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
  const layoutBefore = await wideLayout(dan.page);
  check("MVP-P27-wide-layout-before-agent", !!layoutBefore && stableWideLayout(layoutBefore, layoutBefore));
  await dan.page.getByTestId("chat-input").fill(`Set Engagement ${engagementId} to Yellow with reason 'Agent structured evidence refresh'. Use the supported product tool.`);
  await dan.page.getByTestId("send-button").click();
  const layoutsDuring = [await wideLayout(dan.page)];
  await eventually(async () => {
    layoutsDuring.push(await wideLayout(dan.page));
    return (await dan.page.getByTestId("turn-meta").count()) > turnMetaBefore;
  }, 180_000);
  check("MVP-P28-wide-layout-during-agent", !!layoutBefore && layoutsDuring.length > 0 && layoutsDuring.every((layout) => stableWideLayout(layout, layoutBefore)));
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
  const layoutAfter = await wideLayout(dan.page);
  check("MVP-P29-wide-layout-after-agent", !!layoutBefore && stableWideLayout(layoutAfter, layoutBefore));
  check("MVP-P30-wide-no-horizontal-overflow-after-agent", await noHorizontalOverflow(dan.page));
  await capture(dan.page, `${out}/wide-agent-updated-engagement.png`);

  const narrow = await newPage(browser, { width: 390, height: 844 }, "dan");
  await narrow.page.getByTestId("nav-toggle").click();
  check("MVP-P21-narrow-drawer-opens", await narrow.page.getByTestId("nav-drawer").count() === 1);
  check("MVP-P22-narrow-drawer-focuses", await eventually(() => narrow.page.evaluate(() => document.activeElement?.closest("#workbench-nav") !== null)));
  check("MVP-P31-narrow-drawer-hides-launcher", await eventually(() => narrow.page.getByTestId("dock-launcher").count().then((count) => count === 0)));
  check("MVP-P32-narrow-drawer-sign-out-unobstructed", await signOutUnobstructed(narrow.page));
  await capture(narrow.page, `${out}/narrow-dan-drawer-open.png`);
  await narrow.page.keyboard.press("Escape");
  check("MVP-P23-narrow-escape-restores-focus", await eventually(() => narrow.page.getByTestId("nav-toggle").evaluate((element) => document.activeElement === element)));
  check("MVP-P24-narrow-no-horizontal-overflow", await noHorizontalOverflow(narrow.page));
  const critical = await narrow.page.getByTestId("nav-toggle").boundingBox();
  check("MVP-P25-narrow-critical-control-not-clipped", !!critical && critical.x >= 0 && critical.y >= 0 && critical.x + critical.width <= 390 && critical.y + critical.height <= 844);
  const narrowContent = narrow.page.getByTestId("workbench-content");
  await narrowContent.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  await eventually(() => narrowContent.evaluate((element) => element.scrollTop + element.clientHeight >= element.scrollHeight - 1));
  const lastEngagement = await narrow.page.locator("[data-testid^='engagement-row-']").last().boundingBox();
  const launcher = await narrow.page.getByTestId("dock-launcher").boundingBox();
  const finalCardHits = await finalCardHitPoints(narrow.page);
  report.narrowFinalCardHitPoints = finalCardHits;
  check(
    "MVP-P33-narrow-final-engagement-clears-launcher",
    !!lastEngagement && !!launcher && !intersects(lastEngagement, launcher) &&
      finalCardHits.action.resolves && finalCardHits.title.resolves,
    JSON.stringify(finalCardHits),
  );
  await narrowContent.evaluate((element) => element.scrollTo({ top: 0 }));
  await eventually(() => narrowContent.evaluate((element) => element.scrollTop === 0));
  await capture(narrow.page, `${out}/narrow-dan-workspace.png`);

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
