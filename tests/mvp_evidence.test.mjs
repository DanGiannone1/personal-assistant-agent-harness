import assert from "node:assert/strict";
import test from "node:test";
import { evaluateCase, onlyExpectedEngagementUpdate, onlyNamedEngagementMayChange, parseSse, requireCleanWorktree, requireLoopbackUrl, stateFingerprint } from "../scripts/mvp_evidence.mjs";

const start = { type: "RUN_STARTED", run_id: "run-1", thread_id: "thread-1" };
const finish = { type: "RUN_FINISHED", run_id: "run-1", thread_id: "thread-1" };
const toolEvents = (operation, status, resource, id = "call-1") => [
  { type: "TOOL_CALL_START", tool_call_id: id, tool_call_name: operation },
  { type: "TOOL_CALL_RESULT", tool_call_id: id, result: { operation, status, code: `engagement.${status}`, ...(resource ? { resource } : {}) } },
  { type: "TOOL_CALL_END", tool_call_id: id },
];

test("parses only one JSON event per SSE frame", () => {
  const events = parseSse('data: {"type":"RUN_STARTED"}\n\ndata: {"type":"RUN_FINISHED"}\n\n');
  assert.equal(events.length, 2);
  assert.throws(() => parseSse("data: {}\ndata: {}\n\n"), /exactly one/);
});

test("the evaluation oracle requires structured evidence, one terminal, and state effect", () => {
  const before = { engagements: [{ id: "eng-a", status: "green" }] };
  const after = { engagements: [{ id: "eng-a", status: "red" }] };
  const verdict = evaluateCase({
    expectation: { operation: "update", status: "committed", stateChanged: true, resourceId: "eng-a" }, before, after,
    events: [start, ...toolEvents("update", "committed", { kind: "engagement", id: "eng-a" }), finish],
  });
  assert.equal(verdict.pass, true);
  assert.notEqual(stateFingerprint(before), stateFingerprint(after));
  const missingResource = evaluateCase({
    expectation: { operation: "update", status: "committed", stateChanged: true, resourceId: "eng-a" }, before, after,
    events: [start, ...toolEvents("update", "committed"), finish],
  });
  assert.equal(missingResource.pass, false);
});

test("success-like prose or a bare terminal cannot make an eval case pass", () => {
  const state = { engagements: [{ id: "eng-a", status: "green" }] };
  const prose = evaluateCase({
    expectation: { operation: "update", status: "committed", stateChanged: true }, before: state, after: state,
    events: [start, { type: "TEXT_MESSAGE_CONTENT", delta: "TOOL_CALL_RESULT committed" }, finish],
  });
  assert.equal(prose.pass, false);
  const bare = evaluateCase({ expectation: {}, before: state, after: state, events: [start, finish] });
  assert.equal(bare.pass, false);
});

test("operation and status must come from one result, with a correlated final terminal", () => {
  const before = { engagements: [{ id: "eng-a", status: "green" }] };
  const after = { engagements: [{ id: "eng-a", status: "red" }] };
  const split = evaluateCase({
    expectation: { operation: "update", status: "committed", stateChanged: true }, before, after,
    events: [start, ...toolEvents("update", "invalid", undefined, "call-1"), ...toolEvents("list", "committed", undefined, "call-2"), finish],
  });
  assert.equal(split.pass, false);
  const mismatchedTerminal = evaluateCase({
    expectation: { zeroToolResults: true, stateChanged: false }, before, after: before,
    events: [start, { type: "RUN_FINISHED", run_id: "run-other", thread_id: "thread-1" }],
  });
  assert.equal(mismatchedTerminal.pass, false);
});

test("marker cases require zero tool results and no structured navigation", () => {
  const state = { engagements: [] };
  const inert = evaluateCase({ expectation: { zeroToolResults: true, noNavigation: true, stateChanged: false }, before: state, after: state, events: [start, finish] });
  assert.equal(inert.pass, true);
  const toolLeak = evaluateCase({ expectation: { zeroToolResults: true, noNavigation: true, stateChanged: false }, before: state, after: state, events: [start, ...toolEvents("list", "succeeded"), finish] });
  assert.equal(toolLeak.pass, false);
});

test("tool and navigation lifecycle events must bind to one call and result", () => {
  const state = { engagements: [] };
  const missingStart = evaluateCase({ expectation: { operation: "list", status: "succeeded" }, before: state, after: state, events: [start, { type: "TOOL_CALL_RESULT", tool_call_id: "missing", result: { operation: "list", status: "succeeded", code: "engagement.listed" } }, finish] });
  assert.equal(missingStart.pass, false);
  const unmatchedNavigation = evaluateCase({
    expectation: { operation: "navigate", status: "resolved" }, before: state, after: state,
    events: [start, ...toolEvents("navigate", "resolved", { kind: "engagement", id: "eng-a" }), { type: "NAVIGATION_RESOLVED", runId: "run-1", requestedAtNavigationVersion: 0, destination: { id: "engagements", path: "/engagements" } }, finish],
  });
  assert.equal(unmatchedNavigation.pass, false);
});

test("navigation expectations require exactly one matching resolved route event", () => {
  const state = { engagements: [] };
  const navigationExpectation = {
    operation: "navigate", status: "resolved", stateChanged: false,
    navigation: { destination: { id: "engagements", path: "/engagements" }, requestedAtNavigationVersion: 0 },
  };
  const noRoute = evaluateCase({
    expectation: navigationExpectation, before: state, after: state,
    events: [start, ...toolEvents("navigate", "resolved"), finish],
  });
  assert.equal(noRoute.pass, false);
  const wrongRoute = evaluateCase({
    expectation: navigationExpectation, before: state, after: state,
    events: [
      start,
      { type: "TOOL_CALL_START", tool_call_id: "call-nav", tool_call_name: "navigate" },
      { type: "TOOL_CALL_RESULT", tool_call_id: "call-nav", result: { operation: "navigate", status: "resolved", code: "navigation.resolved", destination: { id: "engagements", path: "/engagements" } } },
      { type: "NAVIGATION_RESOLVED", runId: "run-1", requestedAtNavigationVersion: 0, destination: { id: "workbench", path: "/home" } },
      { type: "TOOL_CALL_END", tool_call_id: "call-nav" },
      finish,
    ],
  });
  assert.equal(wrongRoute.pass, false);
  const matchingRoute = evaluateCase({
    expectation: navigationExpectation, before: state, after: state,
    events: [
      start,
      { type: "TOOL_CALL_START", tool_call_id: "call-nav", tool_call_name: "navigate" },
      { type: "TOOL_CALL_RESULT", tool_call_id: "call-nav", result: { operation: "navigate", status: "resolved", code: "navigation.resolved", destination: { id: "engagements", path: "/engagements" } } },
      { type: "NAVIGATION_RESOLVED", runId: "run-1", requestedAtNavigationVersion: 0, destination: { id: "engagements", path: "/engagements" } },
      { type: "TOOL_CALL_END", tool_call_id: "call-nav" },
      finish,
    ],
  });
  assert.equal(matchingRoute.pass, true);
});

test("only the exact status update may touch its target engagement", () => {
  const before = {
    engagements: [{ id: "eng-a", name: "A", status: "green", statusNote: "", members: [{ userId: "dan", role: "owner" }], activity: [] }, { id: "eng-b", status: "green" }],
    currentRoute: "/engagements",
  };
  const after = {
    engagements: [{ id: "eng-a", name: "Renamed", status: "red", statusNote: "why", members: [{ userId: "ava", role: "owner" }], activity: [{ ts: "volatile", userId: "dan", action: "engagement.updated", detail: "status, statusNote" }] }, { id: "eng-b", status: "green" }],
    currentRoute: "/engagements",
  };
  assert.equal(onlyNamedEngagementMayChange(before, after, "eng-a"), true);
  assert.equal(onlyExpectedEngagementUpdate(before, after, { id: "eng-a", actor: "dan" }), false);
  const verdict = evaluateCase({
    expectation: { operation: "update", status: "committed", resourceId: "eng-a", exactEngagementUpdate: { id: "eng-a", actor: "dan" }, engagementAfter: { id: "eng-a", status: "red", statusNote: "why" } }, before, after,
    events: [start, ...toolEvents("update", "committed", { kind: "engagement", id: "eng-a" }), finish],
  });
  assert.equal(verdict.pass, false);
});

test("loopback and clean-worktree guards refuse crafted DNS, remote hosts, and source changes", () => {
  assert.equal(requireLoopbackUrl("http://localhost:8000", "MVP_API_URL"), "http://localhost:8000");
  assert.equal(requireLoopbackUrl("http://127.0.0.1:8000", "MVP_API_URL"), "http://127.0.0.1:8000");
  assert.throws(() => requireLoopbackUrl("https://127.attacker.example", "MVP_API_URL"), /loopback/);
  assert.throws(() => requireLoopbackUrl("https://example.com", "MVP_API_URL"), /loopback/);
  assert.throws(() => requireCleanWorktree(" M scripts/mvp_evidence.mjs\n"), /clean Git/);
  assert.doesNotThrow(() => requireCleanWorktree("?? evidence/mvp/local-synthetic/playwright/run/results.json\n"));
  assert.doesNotThrow(() => requireCleanWorktree(""));
});
