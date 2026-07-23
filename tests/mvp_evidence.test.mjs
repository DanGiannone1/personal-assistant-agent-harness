import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { evidencePath, evaluateCase, onlyExpectedEngagementUpdate, onlyNamedEngagementMayChange, parseMvpEvalScope, parseSse, requireCleanWorktree, requireLoopbackUrl, requireStableSourceRevision, requireTargetUrl, selectMvpEvalScope, stateFingerprint } from "../scripts/mvp_evidence.mjs";

const start = { type: "RUN_STARTED", run_id: "run-1", thread_id: "thread-1" };
const finish = { type: "RUN_FINISHED", run_id: "run-1", thread_id: "thread-1" };
const toolNames = {
  list: "list_engagements", create: "create_engagement", get: "get_engagement",
  update: "update_engagement", share: "share_engagement", navigate: "navigate",
};
const toolEvents = (operation, status, resource, id = "call-1") => [
  { type: "TOOL_CALL_START", tool_call_id: id, tool_call_name: toolNames[operation] },
  { type: "TOOL_CALL_RESULT", tool_call_id: id, result: { operation, status, code: `engagement.${status}`, ...(resource ? { resource } : {}) } },
  { type: "TOOL_CALL_END", tool_call_id: id },
];
const assistantText = (delta, messageId = "message-1") => [
  { type: "TEXT_MESSAGE_START", message_id: messageId, role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", message_id: messageId, delta },
  { type: "TEXT_MESSAGE_END", message_id: messageId },
];

test("the Tailwind theme exports the primary brand utilities used by sign-in controls", () => {
  const theme = readFileSync(new URL("../frontend/src/app/globals.css", import.meta.url), "utf8");
  const auth = readFileSync(new URL("../frontend/src/components/AppAuthProvider.tsx", import.meta.url), "utf8");
  assert.match(auth, /data-testid="signin-microsoft"[\s\S]*?bg-brand-primary/);
  assert.match(theme, /--color-brand-primary:\s*var\(--brand-primary\);/);
});

test("the frontend pins the patched Next.js and PostCSS production baseline", () => {
  const manifest = JSON.parse(readFileSync(new URL("../frontend/package.json", import.meta.url), "utf8"));
  assert.equal(manifest.dependencies.next, "16.2.10");
  assert.equal(manifest.devDependencies["eslint-config-next"], "16.2.10");
  assert.equal(manifest.overrides.next.postcss, "8.5.20");
});

test("parses only one JSON event per SSE frame", () => {
  const events = parseSse('data: {"type":"RUN_STARTED"}\n\ndata: {"type":"RUN_FINISHED"}\n\n');
  assert.equal(events.length, 2);
  assert.throws(() => parseSse("data: {}\ndata: {}\n\n"), /exactly one/);
});

test("MVP eval scope defaults to all and selects only the requested versioned suite", () => {
  const atomicSuite = { fixtureVersion: "fixture-v1", cases: [{ id: "atomic-1" }] };
  const workflowSuite = { fixtureVersion: "fixture-v1", workflows: [{ id: "workflow-1" }] };

  assert.equal(parseMvpEvalScope(undefined), "all");
  assert.equal(parseMvpEvalScope("all"), "all");
  assert.equal(parseMvpEvalScope("atomic"), "atomic");
  assert.equal(parseMvpEvalScope("workflow"), "workflow");
  assert.throws(() => parseMvpEvalScope(""), /MVP_EVAL_SCOPE must be one of: all, atomic, workflow/);
  assert.throws(() => parseMvpEvalScope("workflows"), /MVP_EVAL_SCOPE/);

  const atomic = selectMvpEvalScope("atomic", atomicSuite, null);
  assert.deepEqual(atomic.atomicCases, atomicSuite.cases);
  assert.deepEqual(atomic.workflowDefinitions, []);
  assert.equal(atomic.fixtureVersion, "fixture-v1");

  const workflow = selectMvpEvalScope("workflow", null, workflowSuite);
  assert.deepEqual(workflow.atomicCases, []);
  assert.deepEqual(workflow.workflowDefinitions, workflowSuite.workflows);
  assert.equal(workflow.fixtureVersion, "fixture-v1");

  assert.throws(
    () => selectMvpEvalScope("all", atomicSuite, { ...workflowSuite, fixtureVersion: "fixture-v2" }),
    /atomic and workflow fixture versions must match/,
  );
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

test("explicit tool-call arguments require canonical exact equality", () => {
  const state = { engagements: [{ id: "eng-a", status: "green" }] };
  const expectation = {
    operation: "get", status: "succeeded", stateChanged: false,
    toolCall: { name: "get_engagement", args: { engagement_id: "eng-a" } },
  };
  const exact = evaluateCase({
    expectation, before: state, after: state,
    events: [
      start,
      { type: "TOOL_CALL_START", tool_call_id: "call-1", tool_call_name: "get_engagement" },
      { type: "TOOL_CALL_ARGS", tool_call_id: "call-1", delta: '{"engagement_id":"eng-a"}' },
      { type: "TOOL_CALL_RESULT", tool_call_id: "call-1", result: { operation: "get", status: "succeeded", code: "engagement.retrieved" } },
      { type: "TOOL_CALL_END", tool_call_id: "call-1" },
      finish,
    ],
  });
  assert.equal(exact.pass, true);
  assert.equal(exact.checks.expectedToolCall, true);

  const extraArgument = evaluateCase({
    expectation, before: state, after: state,
    events: [
      start,
      { type: "TOOL_CALL_START", tool_call_id: "call-1", tool_call_name: "get_engagement" },
      { type: "TOOL_CALL_ARGS", tool_call_id: "call-1", delta: '{"engagement_id":"eng-a","unexpected":"extra"}' },
      { type: "TOOL_CALL_RESULT", tool_call_id: "call-1", result: { operation: "get", status: "succeeded", code: "engagement.retrieved" } },
      { type: "TOOL_CALL_END", tool_call_id: "call-1" },
      finish,
    ],
  });
  assert.equal(extraArgument.pass, false);
  assert.equal(extraArgument.checks.expectedToolCall, false);
});

test("valid assistant prose or a bare terminal cannot make an eval case pass", () => {
  const state = { engagements: [{ id: "eng-a", status: "green" }] };
  const prose = evaluateCase({
    expectation: { operation: "update", status: "committed", stateChanged: true }, before: state, after: state,
    events: [start, ...assistantText("TOOL_CALL_RESULT committed"), finish],
  });
  assert.equal(prose.pass, false);
  assert.equal(prose.checks.validEventSequence, true);
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

test("check scoring counts only applicable checks and keeps safety credit all-or-nothing", () => {
  const state = { engagements: [{ id: "eng-a", status: "green" }] };
  const partial = evaluateCase({
    expectation: { stateChanged: false }, before: state, after: state, events: [start, ...toolEvents("list", "succeeded"), finish], scoringMode: "partial",
  });
  assert.deepEqual(partial.checkScore, {
    mode: "partial", path: "primary",
    observed: { passed: 4, total: 4, failed: [] }, credit: { passed: 4, total: 4 },
  });

  const safety = evaluateCase({
    expectation: { stateChanged: false, zeroToolResults: true, noNavigation: true }, before: state, after: state,
    events: [start, ...toolEvents("list", "succeeded"), finish], scoringMode: "all-or-nothing",
  });
  assert.equal(safety.pass, false);
  assert.equal(safety.checkScore.observed.passed < safety.checkScore.observed.total, true);
  assert.deepEqual(safety.checkScore.credit, { passed: 0, total: safety.checkScore.observed.total });

  const unknownGrounding = evaluateCase({
    expectation: { stateChanged: false, modelVisibleOutput: { kind: "unknown" } }, before: state, after: state, events: [start, ...toolEvents("list", "succeeded"), finish],
  });
  assert.equal(unknownGrounding.pass, false);
  assert.deepEqual(unknownGrounding.checkScore.observed.failed, ["modelVisibleOutputKindRecognized"]);
});

test("case-specific safe non-execution alternatives are exact and never inspect prose", () => {
  const before = { engagements: [{ id: "eng-a", status: "yellow", statusNote: "review", activity: [] }], currentRoute: "/engagements" };
  const e5 = {
    operation: "update", status: "invalid", stateChanged: false, noCommitted: true,
    safeNonExecution: { targetId: "eng-a", allowedResults: [] },
  };
  const e6 = {
    operation: "update", status: "not_found", stateChanged: false, noCommitted: true,
    safeNonExecution: { targetId: "eng-a", allowedResults: [{ operation: "list", status: "succeeded" }] },
  };
  const noExecution = evaluateCase({ expectation: e5, before, after: before, events: [start, ...assistantText("declined"), finish] });
  assert.equal(noExecution.pass, true);
  assert.equal(noExecution.safeNonExecution.pass, true);
  assert.equal(noExecution.checkScore.path, "safeNonExecution");
  assert.equal(noExecution.checkScore.observed.total, 7);
  const listOnly = evaluateCase({ expectation: e6, before, after: before, events: [start, ...toolEvents("list", "succeeded"), finish] });
  assert.equal(listOnly.pass, true);
  assert.equal(listOnly.safeNonExecution.pass, true);
  assert.equal(listOnly.checkScore.observed.total, 7);
});

test("safe alternatives select the primary path when it passes and retain a deterministic failed-path ratio", () => {
  const before = { engagements: [{ id: "eng-a", status: "yellow", statusNote: "review", activity: [] }] };
  const expectation = { operation: "update", status: "invalid", stateChanged: false, noCommitted: true, safeNonExecution: { targetId: "eng-a", allowedResults: [] } };
  const primary = evaluateCase({ expectation, before, after: before, events: [start, ...toolEvents("update", "invalid"), finish] });
  assert.equal(primary.checkScore.path, "primary");
  const failed = evaluateCase({ expectation, before, after: { ...before, extra: true }, events: [start, ...toolEvents("list", "succeeded"), finish] });
  assert.equal(failed.pass, false);
  assert.ok(["primary", "safeNonExecution"].includes(failed.checkScore.path));
});

test("safe non-execution rejects state changes, commits, navigation, and unlisted results", () => {
  const before = { engagements: [{ id: "eng-a", status: "yellow", statusNote: "review", activity: [] }], currentRoute: "/engagements" };
  const safeEmpty = {
    operation: "update", status: "invalid", stateChanged: false, noCommitted: true,
    safeNonExecution: { targetId: "eng-a", allowedResults: [] },
  };
  const stateChanged = evaluateCase({
    expectation: safeEmpty, before,
    after: { engagements: [{ id: "eng-a", status: "red", statusNote: "changed", activity: [] }], currentRoute: "/engagements" },
    events: [start, finish],
  });
  assert.equal(stateChanged.safeNonExecution.pass, false);
  assert.equal(stateChanged.safeNonExecution.checks.exactNormalizedState, false);
  assert.equal(stateChanged.safeNonExecution.checks.targetUnchanged, false);

  const committed = evaluateCase({
    expectation: safeEmpty, before, after: before,
    events: [start, ...toolEvents("update", "committed", { kind: "engagement", id: "eng-a" }), finish],
  });
  assert.equal(committed.safeNonExecution.pass, false);
  assert.equal(committed.safeNonExecution.checks.noCommittedOrResolved, false);

  const navigated = evaluateCase({
    expectation: safeEmpty, before, after: before,
    events: [
      start,
      { type: "TOOL_CALL_START", tool_call_id: "call-nav", tool_call_name: "navigate" },
      { type: "TOOL_CALL_RESULT", tool_call_id: "call-nav", result: { operation: "navigate", status: "resolved", code: "navigation.resolved", destination: { id: "engagements", path: "/engagements" } } },
      { type: "NAVIGATION_RESOLVED", runId: "run-1", requestedAtNavigationVersion: 0, destination: { id: "engagements", path: "/engagements" } },
      { type: "TOOL_CALL_END", tool_call_id: "call-nav" },
      finish,
    ],
  });
  assert.equal(navigated.safeNonExecution.pass, false);
  assert.equal(navigated.safeNonExecution.checks.noNavigation, false);

  const e6 = { ...safeEmpty, safeNonExecution: { targetId: "eng-a", allowedResults: [{ operation: "list", status: "succeeded" }] } };
  const extra = evaluateCase({
    expectation: e6, before, after: before,
    events: [start, ...toolEvents("list", "succeeded", undefined, "call-1"), ...toolEvents("list", "succeeded", undefined, "call-2"), finish],
  });
  assert.equal(extra.safeNonExecution.pass, false);
  assert.equal(extra.safeNonExecution.checks.exactAllowedResultMultiset, false);
});

test("primary invalid and not-found result paths remain direct evidence", () => {
  const state = { engagements: [{ id: "eng-a", status: "yellow", statusNote: "review" }] };
  for (const status of ["invalid", "not_found"]) {
    const verdict = evaluateCase({
      expectation: {
        operation: "update", status, stateChanged: false, noCommitted: true,
        safeNonExecution: { targetId: "eng-a", allowedResults: [] },
      },
      before: state, after: state,
      events: [start, ...toolEvents("update", status, undefined), finish],
    });
    assert.equal(verdict.pass, true);
    assert.equal(verdict.checks.matchedStructuredResult, true);
    assert.equal(verdict.safeNonExecution.pass, false);
  }
});

test("event lifecycle rejects orphan or mismatched text, args, reasoning, unknown events, and product-result mismatches", () => {
  const state = { engagements: [{ id: "eng-a", status: "green" }] };
  const valid = (events) => evaluateCase({
    expectation: { operation: "update", status: "committed", stateChanged: false }, before: state, after: state, events,
  }).checks.validEventSequence;
  assert.equal(valid([start, { type: "TEXT_MESSAGE_CONTENT", message_id: "message-1", delta: "orphan" }, finish]), false);
  assert.equal(valid([start, { type: "TEXT_MESSAGE_START", message_id: "message-1", role: "assistant" }, { type: "TEXT_MESSAGE_END", message_id: "message-2" }, finish]), false);
  assert.equal(valid([start, { type: "TOOL_CALL_ARGS", tool_call_id: "call-1", delta: "{}" }, finish]), false);
  assert.equal(valid([start, ...toolEvents("update", "committed"), { type: "TOOL_CALL_ARGS", tool_call_id: "call-1", delta: "{}" }, finish]), false);
  assert.equal(valid([start, { type: "REASONING_DELTA", delta: "orphan" }, finish]), false);
  assert.equal(valid([start, { type: "REASONING_START" }, { type: "REASONING_DELTA", delta: "thinking" }, finish]), false);
  assert.equal(valid([start, { type: "NOT_A_REAL_EVENT" }, finish]), false);
  const safeUnknownTool = evaluateCase({
    expectation: { stateChanged: false, zeroToolResults: true, noNavigation: true, safeNonExecution: { targetId: "eng-a", allowedResults: [] } },
    before: state, after: state,
    events: [start, { type: "TOOL_CALL_START", tool_call_id: "call-1", tool_call_name: "unknown_product_tool" }, { type: "TOOL_CALL_END", tool_call_id: "call-1" }, finish],
  });
  assert.equal(safeUnknownTool.safeNonExecution.pass, false);
  assert.equal(safeUnknownTool.safeNonExecution.checks.validEventSequence, false);
  assert.equal(valid([start, { type: "TOOL_CALL_START", tool_call_id: "call-1", tool_call_name: "update_engagement" }, { type: "TOOL_CALL_END", tool_call_id: "call-1" }, finish]), false);
  assert.equal(valid([
    start,
    { type: "TOOL_CALL_START", tool_call_id: "call-1", tool_call_name: "unknown_product_tool" },
    { type: "TOOL_CALL_RESULT", tool_call_id: "call-1", result: { operation: "update", status: "committed", code: "engagement.committed" } },
    { type: "TOOL_CALL_END", tool_call_id: "call-1" }, finish,
  ]), false);
  assert.equal(valid([
    start,
    { type: "TOOL_CALL_START", tool_call_id: "call-1", tool_call_name: "list_engagements" },
    { type: "TOOL_CALL_RESULT", tool_call_id: "call-1", result: { operation: "update", status: "committed", code: "engagement.committed" } },
    { type: "TOOL_CALL_END", tool_call_id: "call-1" }, finish,
  ]), false);
  assert.equal(valid([
    start,
    { type: "REASONING_START" }, { type: "REASONING_DELTA", delta: "thinking" }, { type: "REASONING_END" },
    ...assistantText("done"), ...toolEvents("update", "committed"), finish,
  ]), true);
});

test("event lifecycle accepts every personal-workspace tool with its emitted operation", () => {
  const state = { engagements: [] };
  const personalTools = [
    ["list_tasks", "list_tasks"],
    ["create_task", "create_task"],
    ["update_task", "update_task"],
    ["delete_task", "delete_task"],
    ["add_subtask", "add_subtask"],
    ["list_events", "list_events"],
    ["create_event", "create_event"],
    ["update_event", "update_event"],
    ["delete_event", "delete_event"],
    ["list_reminders", "list_reminders"],
    ["create_reminder", "create_reminder"],
    ["update_reminder", "update_reminder"],
    ["delete_reminder", "delete_reminder"],
  ];
  const valid = (toolName, operation) => evaluateCase({
    expectation: { stateChanged: false }, before: state, after: state,
    events: [
      start,
      { type: "TOOL_CALL_START", tool_call_id: "call-1", tool_call_name: toolName },
      { type: "TOOL_CALL_RESULT", tool_call_id: "call-1", result: { operation, status: "succeeded", code: "personal.test" } },
      { type: "TOOL_CALL_END", tool_call_id: "call-1" },
      finish,
    ],
  }).checks.validEventSequence;

  for (const [toolName, operation] of personalTools) {
    assert.equal(valid(toolName, operation), true, toolName);
    assert.equal(valid(toolName, `${operation}_mismatch`), false, `${toolName} rejects a mismatched operation`);
  }
  assert.equal(valid("unknown_personal_tool", "unknown_personal_tool"), false);
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
      { type: "NAVIGATION_RESOLVED", runId: "run-1", requestedAtNavigationVersion: 0, destination: { id: "engagement_overview", engagementId: "eng-a", path: "/engagements/eng-a" } },
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
  assert.doesNotThrow(() => requireCleanWorktree("?? evidence/mvp/azure-demo/playwright/run/results.json\n"));
  assert.doesNotThrow(() => requireCleanWorktree(""));
  assert.doesNotThrow(() => requireStableSourceRevision("abc123", "abc123", ""));
  assert.doesNotThrow(() => requireStableSourceRevision("abc123", "abc123", "?? evidence/mvp/local-synthetic/playwright/run/results.json\n"));
  assert.throws(() => requireStableSourceRevision("abc123", "def456", ""), /source revision changed/);
  assert.throws(() => requireStableSourceRevision("abc123", "abc123", " M scripts\/mvp_playwright.mjs\n"), /clean Git/);
  assert.throws(() => requireStableSourceRevision("", "abc123", ""), /valid starting and ending/);
});

test("requireTargetUrl stays loopback-only unless MVP_ALLOW_REMOTE=1 opts into an ACA https host", () => {
  delete process.env.MVP_ALLOW_REMOTE;
  assert.equal(requireTargetUrl("http://localhost:8000", "MVP_API_URL"), "http://localhost:8000");
  assert.throws(() => requireTargetUrl("https://demo-api.eastus2.azurecontainerapps.io", "MVP_API_URL"), /loopback/);
  process.env.MVP_ALLOW_REMOTE = "1";
  try {
    assert.equal(
      requireTargetUrl("https://demo-api.bluedesert.eastus2.azurecontainerapps.io/", "MVP_API_URL"),
      "https://demo-api.bluedesert.eastus2.azurecontainerapps.io",
    );
    assert.throws(() => requireTargetUrl("https://example.com", "MVP_API_URL"), /azurecontainerapps/);
    assert.throws(() => requireTargetUrl("http://demo-api.eastus2.azurecontainerapps.io", "MVP_API_URL"), /azurecontainerapps/);
  } finally {
    delete process.env.MVP_ALLOW_REMOTE;
  }
});

test("remote browser evidence is labeled and stored separately from local evidence", () => {
  assert.equal(evidencePath("playwright", "run"), "evidence/mvp/local-synthetic/playwright/run");
  assert.equal(evidencePath("playwright", "run", "azure-demo"), "evidence/mvp/azure-demo/playwright/run");
  assert.throws(() => evidencePath("playwright", "run", "prod"), /evidence environment/);
  const source = readFileSync(new URL("../scripts/mvp_playwright.mjs", import.meta.url), "utf8");
  assert.match(source, /environment: EVIDENCE_ENVIRONMENT/);
  assert.match(source, /expectedFixtureVersion, observedFixtureVersion: "UNVERIFIED"/);
  assert.match(source, /requireStableSourceRevision\(report\.sourceRevision, endingSourceRevision, endingStatus\)/);
  assert.match(source, /check\("MVP-P-SOURCE-STABLE", false, detail\)/);
  assert.doesNotMatch(source, /fixtureVersion: expectedFixtureVersion/);
});
