/* Live Deep Agents MVP evidence.  Structured events and authoritative state are
 * the oracle; assistant wording is intentionally recorded but never scored. */
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { evidencePath, evaluateCase, parseSse, requireCleanWorktree, requireTargetUrl } from "./mvp_evidence.mjs";

const startedAt = new Date().toISOString();
const API = requireTargetUrl(process.env.MVP_API_URL || "http://localhost:8000", "MVP_API_URL");
const runId = process.env.MVP_RUN_ID || new Date().toISOString().replace(/[:.]/g, "-") + `-${randomUUID().slice(0, 8)}`;
const out = evidencePath("agent-evals", runId);
const cases = JSON.parse(readFileSync("tests/evals/mvp-cases.json", "utf8"));

if (!process.env.DEMO_PASSWORD) throw new Error("DEMO_PASSWORD is required; no static demo password is used.");
if (process.env.MVP_RESET_BEFORE_RUN !== "1") throw new Error("Set MVP_RESET_BEFORE_RUN=1; each live eval must begin from the guarded fixture reset.");
requireCleanWorktree(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }));

function resetFixture() {
  const output = execFileSync("uv", ["run", "python", "scripts/reset_demo_state.py"], {
    env: { ...process.env, CONFIRM_DEMO_RESET: "YES" }, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  return JSON.parse(output.split("\n").at(-1));
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

async function turn(session, prompt) {
  const started = Date.now();
  const response = await fetch(`${API}/sessions/${session.sessionId}/messages`, {
    method: "POST", headers: session.headers, body: JSON.stringify({ prompt, navigation_version: 0 }),
  });
  if (!response.ok) throw new Error(`agent turn failed: ${response.status} ${await response.text()}`);
  const text = await response.text();
  return { events: parseSse(text), latencyMs: Date.now() - started };
}

const fixture = resetFixture();
if (fixture.fixtureVersion !== cases.fixtureVersion) throw new Error(`fixture version mismatch: ${fixture.fixtureVersion} != ${cases.fixtureVersion}`);
mkdirSync(out, { recursive: true });
const results = [];
for (const item of cases.cases) {
  const session = await sessionFor(item.actor);
  const observerActor = item.observerActor ?? item.actor;
  const observer = observerActor === item.actor ? session : await sessionFor(observerActor);
  const before = await state(observer);
  const observed = await turn(session, item.prompt);
  const after = await state(observer);
  const verdict = evaluateCase({ expectation: item.expectation, before, after, events: observed.events });
  results.push({ id: item.id, actor: item.actor, observerActor, prompt: item.prompt, ...verdict, latencyMs: observed.latencyMs, before, after, events: observed.events });
}
const report = {
  schemaVersion: 1, kind: "mvp-agent-eval", runId, sourceRevision: execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
  fixture, environment: "local-synthetic", harness: process.env.AGENT_BACKEND || "deepagents", model: process.env.AZURE_DEPLOYMENT || "UNSPECIFIED",
  api: API, startedAt, results,
  summary: { passed: results.filter((result) => result.pass).length, failed: results.filter((result) => !result.pass).map((result) => result.id) },
};
writeFileSync(`${out}/results.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify({ evidence: `${out}/results.json`, ...report.summary }, null, 2));
process.exitCode = report.summary.failed.length ? 1 : 0;
