/* Live Deep Agents MVP evidence.  Structured events and authoritative state are
 * the oracle; assistant wording is intentionally recorded but never scored. */
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { relative, resolve, sep } from "node:path";
import { evidencePath, evaluateCase, evaluateWorkflow, parseMvpEvalScope, parseSse, requireCleanWorktree, requireLoopbackUrl, selectMvpEvalScope } from "./mvp_evidence.mjs";
import { buildMvpScorecard, renderMvpScorecard } from "./mvp_scorecard.mjs";
import { atomicScoringMode } from "./mvp_eval_manifest.mjs";

const startedAt = new Date().toISOString();
const scope = parseMvpEvalScope(process.env.MVP_EVAL_SCOPE);
const API = requireLoopbackUrl(process.env.MVP_API_URL || "http://localhost:8000", "MVP_API_URL");
const runId = process.env.MVP_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-") + `-${randomUUID().slice(0, 8)}`;
const out = evidencePath("agent-evals", runId);
const cases = scope === "workflow" ? null : JSON.parse(readFileSync("tests/evals/mvp-cases.json", "utf8"));
const workflowSuite = scope === "atomic" ? null : JSON.parse(readFileSync("tests/evals/mvp-workflows.json", "utf8"));
const selectedSuites = selectMvpEvalScope(scope, cases, workflowSuite);
const harness = process.env.AGENT_BACKEND || "deepagents";
if (harness !== "deepagents") throw new Error("The MVP workflow lane is Deep Agents product-runtime evidence; run Waza separately for skill-laboratory evidence.");
const skillPath = "session-container/product-skills/engagement-meeting-prep/SKILL.md";
const skill = {
  name: "engagement-meeting-prep",
  version: "1.0.0",
  path: skillPath,
  sha256: createHash("sha256").update(readFileSync(skillPath)).digest("hex"),
};

if (!process.env.DEMO_PASSWORD) throw new Error("DEMO_PASSWORD is required; no static demo password is used.");
if (process.env.MVP_RESET_BEFORE_RUN !== "1") throw new Error("Set MVP_RESET_BEFORE_RUN=1; each live eval must begin from the guarded fixture reset.");
const sourceRevision = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
requireCleanWorktree(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }));

function resetFixture() {
  const output = execFileSync("uv", ["run", "python", "scripts/reset_demo_state.py"], {
    env: { ...process.env, CONFIRM_DEMO_RESET: "YES" }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  return JSON.parse(output.split("\n").at(-1));
}

function requireFixtureIdentity(actual, expected = null) {
  if (actual?.fixtureVersion !== selectedSuites.fixtureVersion) {
    throw new Error(`fixture version mismatch: ${actual?.fixtureVersion} != ${selectedSuites.fixtureVersion}`);
  }
  if (typeof actual?.fixtureHash !== "string" || !actual.fixtureHash) {
    throw new Error("fixture reset did not return its stable SHA-256 identity");
  }
  if (expected && (actual.fixtureVersion !== expected.fixtureVersion || actual.fixtureHash !== expected.fixtureHash)) {
    throw new Error("fixture reset identity changed within the eval run");
  }
}

async function json(path, init = {}) {
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) throw new Error(`${init.method ?? "GET"} ${path} failed: ${response.status} ${await response.text()}`);
  return response.status === 204 ? null : response.json();
}

async function sessionFor(actor) {
  const login = await json("/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: actor, password: process.env.DEMO_PASSWORD }) });
  const headers = { "X-Auth-Token": login.token, "content-type": "application/json" };
  const session = await json("/sessions", { method: "POST", headers });
  return { headers, sessionId: session.session_id };
}

async function state(session) {
  return json(`/sessions/${session.sessionId}/app/state`, { headers: session.headers });
}

function readRawRecords(rawPath, runIdForTurn) {
  if (typeof rawPath !== "string" || !rawPath) throw new Error("raw SDK trace is required for complete eval evidence");
  const configuredRoot = resolve(process.env.MVP_RAW_TRACE_ROOT || "logs/sdk-events");
  const root = realpathSync(configuredRoot);
  const file = realpathSync(rawPath);
  const within = relative(root, file);
  if (within.startsWith(`..${sep}`) || within === ".." || within.startsWith(sep)) {
    throw new Error("raw SDK trace path is outside MVP_RAW_TRACE_ROOT");
  }
  return readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
    .filter((record) => record.run_id === runIdForTurn);
}

async function turn(session, prompt) {
  const started = performance.now();
  const response = await fetch(`${API}/sessions/${session.sessionId}/messages`, {
    method: "POST", headers: session.headers, body: JSON.stringify({ prompt, navigation_version: 0 }),
  });
  if (!response.ok) throw new Error(`agent turn failed: ${response.status} ${await response.text()}`);
  const text = await response.text();
  const events = parseSse(text);
  const runIdForTurn = events.find((event) => event.type === "RUN_STARTED")?.run_id;
  if (!runIdForTurn) throw new Error("agent turn did not emit a correlated RUN_STARTED event");
  const trace = await json(`/sessions/${session.sessionId}/trace`, { headers: session.headers });
  return {
    events,
    rawRecords: readRawRecords(trace.raw_sdk_trace, runIdForTurn),
    latencyMs: Math.max(0, Math.round(performance.now() - started)),
  };
}

mkdirSync(out, { recursive: true });
const results = [];
let fixture = null;
for (const item of selectedSuites.atomicCases) {
  const caseFixture = resetFixture();
  requireFixtureIdentity(caseFixture, fixture);
  fixture ??= caseFixture;
  const session = await sessionFor(item.actor);
  const observerActor = item.observerActor ?? item.actor;
  const observer = observerActor === item.actor ? session : await sessionFor(observerActor);
  const before = await state(observer);
  const observed = await turn(session, item.prompt);
  const after = await state(observer);
  const verdict = evaluateCase({ expectation: item.expectation, before, after, events: observed.events, rawRecords: observed.rawRecords, scoringMode: atomicScoringMode(item.id) });
  results.push({ id: item.id, actor: item.actor, observerActor, prompt: item.prompt, fixture: caseFixture, ...verdict, latencyMs: observed.latencyMs, before, after, events: observed.events, rawRecords: observed.rawRecords });
}

const workflows = [];
for (const sourceDefinition of selectedSuites.workflowDefinitions) {
  const workflowFixture = resetFixture();
  requireFixtureIdentity(workflowFixture, fixture);
  fixture ??= workflowFixture;
  const definition = structuredClone(sourceDefinition);
  const skillTurn = definition.turns.find((entry) => entry.id === "prepare") ?? definition.turns[0];
  skillTurn.expectation.skill = { name: skill.name, sha256: skill.sha256 };
  const session = await sessionFor(definition.actor);
  const before = await state(session);
  const turnEvidence = [];
  for (const turnDefinition of definition.turns) {
    const turnBefore = await state(session);
    const observed = await turn(session, turnDefinition.prompt);
    const turnAfter = await state(session);
    turnEvidence.push({
      id: turnDefinition.id,
      prompt: turnDefinition.prompt,
      sessionId: session.sessionId,
      before: turnBefore,
      after: turnAfter,
      events: observed.events,
      rawRecords: observed.rawRecords,
      latencyMs: observed.latencyMs,
    });
  }
  const after = await state(session);
  const verdict = evaluateWorkflow({ definition, resetCount: 1, sessionId: session.sessionId, before, turns: turnEvidence, after, scoringMode: "partial" });
  workflows.push({
    id: definition.id,
    actor: definition.actor,
    description: definition.description,
    fixture: workflowFixture,
    sessionId: session.sessionId,
    before,
    after,
    turns: turnEvidence,
    ...verdict,
  });
}
const endingSourceRevision = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
if (endingSourceRevision !== sourceRevision) throw new Error("source revision changed during the live eval run");
requireCleanWorktree(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }));
const completedAt = new Date().toISOString();
const report = {
  schemaVersion: 5, kind: "mvp-agent-eval", runId, sourceRevision, scope,
  fixture, environment: "local-synthetic", harness, model: process.env.AZURE_DEPLOYMENT || "UNSPECIFIED",
  skill, api: API, startedAt, completedAt, results, workflows,
  summary: {
    atomic: { passed: results.filter((result) => result.pass === true).length, failed: results.filter((result) => result.pass !== true).map((result) => result.id) },
    workflows: { passed: workflows.filter((result) => result.pass === true).length, failed: workflows.filter((result) => result.pass !== true).map((result) => result.id) },
    checks: {
      passed: [...results, ...workflows].reduce((total, result) => total + result.checkScore.credit.passed, 0),
      total: [...results, ...workflows].reduce((total, result) => total + result.checkScore.credit.total, 0),
    },
  },
};
writeFileSync(`${out}/results.json`, JSON.stringify(report, null, 2));
const scorecard = buildMvpScorecard(report);
writeFileSync(`${out}/scorecard.json`, JSON.stringify(scorecard, null, 2));
writeFileSync(`${out}/scorecard.md`, renderMvpScorecard(scorecard));
console.log(JSON.stringify({ evidence: `${out}/results.json`, scorecard: `${out}/scorecard.md`, ...report.summary }, null, 2));
process.exitCode = report.summary.atomic.failed.length || report.summary.workflows.failed.length ? 1 : 0;
