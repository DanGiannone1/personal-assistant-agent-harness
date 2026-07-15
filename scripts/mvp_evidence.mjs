import { createHash } from "node:crypto";
import { isIP } from "node:net";

export function parseSse(text) {
  const frames = text.split(/\r?\n\r?\n/).filter((frame) => frame.trim());
  return frames.map((frame) => {
    const lines = frame.replace(/\r\n/g, "\n").split("\n");
    const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart());
    if (data.length !== 1) throw new Error("SSE frame must contain exactly one data event");
    return JSON.parse(data[0]);
  });
}

export function terminalEvents(events) {
  return events.filter((event) => event.type === "RUN_FINISHED" || event.type === "RUN_ERROR");
}

export function requireLoopbackUrl(value, label) {
  let url;
  try { url = new URL(value); } catch { throw new Error(`${label} must be an absolute http(s) URL`); }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error(`${label} must use http or https`);
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  const loopback = host === "localhost"
    || (isIP(host) === 4 && host.split(".")[0] === "127")
    || (isIP(host) === 6 && host === "::1");
  if (!loopback) {
    throw new Error(`${label} must target a loopback host`);
  }
  return url.toString().replace(/\/$/, "");
}

export function requireCleanWorktree(status) {
  const sourceChanges = status.split(/\r?\n/).filter(Boolean).filter((line) => {
    const path = line.slice(3);
    return !path.startsWith("evidence/mvp/local-synthetic/");
  });
  if (sourceChanges.length) throw new Error("live evidence requires a clean Git worktree");
}

export function normalizedState(value) {
  const volatile = new Set(["_etag", "_rid", "_self", "_attachments", "_ts", "createdAt", "createdAt", "uploadedAt", "savedAt", "ts"]);
  if (Array.isArray(value)) return value.map(normalizedState).sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !volatile.has(key))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => [key, normalizedState(item)]));
}

export function stateFingerprint(state) {
  return createHash("sha256").update(JSON.stringify(normalizedState(state))).digest("hex");
}

export function onlyNamedEngagementMayChange(before, after, engagementId) {
  const normalizedBefore = normalizedState(before);
  const normalizedAfter = normalizedState(after);
  const { engagements: beforeEngagements = [], ...beforeElse } = normalizedBefore;
  const { engagements: afterEngagements = [], ...afterElse } = normalizedAfter;
  if (JSON.stringify(beforeElse) !== JSON.stringify(afterElse)) return false;
  const beforeTarget = beforeEngagements.find((entry) => entry.id === engagementId);
  const afterTarget = afterEngagements.find((entry) => entry.id === engagementId);
  if (!beforeTarget || !afterTarget) return false;
  const others = (entries) => entries.filter((entry) => entry.id !== engagementId);
  return JSON.stringify(others(beforeEngagements)) === JSON.stringify(others(afterEngagements));
}

export function onlyExpectedEngagementUpdate(before, after, { id, actor, detail }) {
  if (!onlyNamedEngagementMayChange(before, after, id)) return false;
  const beforeTarget = normalizedState((before.engagements ?? []).find((entry) => entry.id === id));
  const afterTarget = normalizedState((after.engagements ?? []).find((entry) => entry.id === id));
  if (!beforeTarget || !afterTarget) return false;
  const beforeActivity = beforeTarget.activity ?? [];
  const afterActivity = afterTarget.activity ?? [];
  if (afterActivity.length !== beforeActivity.length + 1) return false;
  const retainedActivity = [...afterActivity];
  for (const entry of beforeActivity) {
    const index = retainedActivity.findIndex((candidate) => JSON.stringify(candidate) === JSON.stringify(entry));
    if (index < 0) return false;
    retainedActivity.splice(index, 1);
  }
  if (retainedActivity.length !== 1) return false;
  const [newActivity] = retainedActivity;
  if (newActivity?.action !== "engagement.updated" || (actor && newActivity?.userId !== actor) || (detail && newActivity?.detail !== detail)) return false;
  delete beforeTarget.status; delete beforeTarget.statusNote; delete beforeTarget.activity;
  delete afterTarget.status; delete afterTarget.statusNote; delete afterTarget.activity;
  return JSON.stringify(beforeTarget) === JSON.stringify(afterTarget);
}

function validEventSequence(events) {
  if (!Array.isArray(events) || events.length < 2 || events[0]?.type !== "RUN_STARTED") return false;
  const terminals = terminalEvents(events);
  const runId = events[0]?.run_id;
  const threadId = events[0]?.thread_id;
  if (typeof runId !== "string" || !runId || typeof threadId !== "string" || !threadId) return false;
  if (terminals.length !== 1 || events.at(-1) !== terminals[0]) return false;
  if (terminals[0].type === "RUN_FINISHED" && (terminals[0].run_id !== runId || terminals[0].thread_id !== threadId)) return false;
  if (terminals[0].type === "RUN_ERROR" && (typeof terminals[0].message !== "string" || !terminals[0].message)) return false;
  const expectedOperations = {
    list_engagements: "list",
    create_engagement: "create",
    get_engagement: "get",
    update_engagement: "update",
    set_engagement_status: "update",
    share_engagement: "share",
    navigate: "navigate",
  };
  const knownTypes = new Set([
    "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
    "REASONING_START", "REASONING_DELTA", "REASONING_END",
    "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_RESULT", "TOOL_CALL_END",
    "NAVIGATION_RESOLVED", "RUN_FINISHED", "RUN_ERROR",
  ]);
  const tools = new Map();
  const closedToolIds = new Set();
  const seenMessageIds = new Set();
  let openMessageId = null;
  let reasoningOpen = false;
  for (let index = 0; index < events.length; index += 1) {
    const event = events[index];
    if (!event || typeof event.type !== "string" || !knownTypes.has(event.type)) return false;
    if (index === 0) continue;
    if (event.type === "RUN_STARTED" || index === events.length - 1 && !["RUN_FINISHED", "RUN_ERROR"].includes(event.type)) return false;
    if (event.type === "TEXT_MESSAGE_START") {
      if (openMessageId !== null || typeof event.message_id !== "string" || !event.message_id
        || seenMessageIds.has(event.message_id) || typeof event.role !== "string" || !event.role) return false;
      openMessageId = event.message_id;
      seenMessageIds.add(event.message_id);
    } else if (event.type === "TEXT_MESSAGE_CONTENT") {
      if (event.message_id !== openMessageId || typeof event.delta !== "string") return false;
    } else if (event.type === "TEXT_MESSAGE_END") {
      if (event.message_id !== openMessageId) return false;
      openMessageId = null;
    } else if (event.type === "REASONING_START") {
      if (reasoningOpen) return false;
      reasoningOpen = true;
    } else if (event.type === "REASONING_DELTA") {
      if (!reasoningOpen || typeof event.delta !== "string") return false;
    } else if (event.type === "REASONING_END") {
      if (!reasoningOpen) return false;
      reasoningOpen = false;
    } else if (event.type === "TOOL_CALL_START") {
      if (typeof event.tool_call_id !== "string" || !event.tool_call_id || typeof event.tool_call_name !== "string" || !event.tool_call_name
        || !Object.hasOwn(expectedOperations, event.tool_call_name)
        || tools.has(event.tool_call_id) || closedToolIds.has(event.tool_call_id)) return false;
      tools.set(event.tool_call_id, { phase: "started", navigationBound: false, expectedOperation: expectedOperations[event.tool_call_name] });
    } else if (event.type === "TOOL_CALL_ARGS") {
      const tool = tools.get(event.tool_call_id);
      if (!tool || tool.phase !== "started" || typeof event.delta !== "string") return false;
    } else if (event.type === "TOOL_CALL_RESULT") {
      const tool = tools.get(event.tool_call_id);
      const result = event.result;
      if (!tool || tool.phase !== "started" || !result || typeof result !== "object"
        || typeof result.status !== "string" || !result.status
        || typeof result.code !== "string" || !result.code
        || typeof result.operation !== "string" || !result.operation
        || !tool.expectedOperation || result.operation !== tool.expectedOperation) return false;
      tool.phase = "result"; tool.result = result;
    } else if (event.type === "NAVIGATION_RESOLVED") {
      if (event.runId !== runId || !Number.isInteger(event.requestedAtNavigationVersion) || !event.destination || typeof event.destination !== "object") return false;
      const matches = [...tools.values()].filter((tool) => tool.phase === "result" && !tool.navigationBound
        && ["resolved", "committed"].includes(tool.result.status)
        && JSON.stringify(tool.result.destination) === JSON.stringify(event.destination));
      if (matches.length !== 1) return false;
      matches[0].navigationBound = true;
    } else if (event.type === "TOOL_CALL_END") {
      const tool = tools.get(event.tool_call_id);
      if (!tool || tool.phase !== "result") return false;
      tools.delete(event.tool_call_id);
      closedToolIds.add(event.tool_call_id);
    } else if (event.type === "RUN_FINISHED") {
      if (event.run_id !== runId || event.thread_id !== threadId || openMessageId !== null || reasoningOpen || tools.size) return false;
    } else if (event.type === "RUN_ERROR") {
      if (openMessageId !== null || reasoningOpen || tools.size) return false;
    }
  }
  return true;
}

function sameResultMultiset(results, allowedResults) {
  if (!Array.isArray(allowedResults)) return false;
  const normalize = (result) => {
    if (!result || typeof result !== "object" || typeof result.operation !== "string" || !result.operation
      || typeof result.status !== "string" || !result.status
      || Object.keys(result).some((key) => key !== "operation" && key !== "status")) return null;
    return { operation: result.operation, status: result.status };
  };
  const actual = results.map((result) => normalize({ operation: result?.operation, status: result?.status }));
  const allowed = allowedResults.map(normalize);
  return !actual.includes(null) && !allowed.includes(null)
    && JSON.stringify(actual.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))))
      === JSON.stringify(allowed.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))));
}

function safeNonExecutionChecks(safeNonExecution, { before, after, events, results, validEventSequence, terminalExpected }) {
  if (!safeNonExecution || typeof safeNonExecution !== "object") return null;
  const targetId = safeNonExecution.targetId;
  const beforeTarget = (before.engagements ?? []).find((entry) => entry.id === targetId);
  const afterTarget = (after.engagements ?? []).find((entry) => entry.id === targetId);
  return {
    validEventSequence,
    terminalExpected,
    exactNormalizedState: stateFingerprint(before) === stateFingerprint(after),
    targetUnchanged: !!beforeTarget && !!afterTarget
      && JSON.stringify(normalizedState(beforeTarget)) === JSON.stringify(normalizedState(afterTarget)),
    noCommittedOrResolved: !results.some((result) => ["committed", "resolved"].includes(result?.status)),
    noNavigation: !events.some((event) => event.type === "NAVIGATION_RESOLVED"),
    exactAllowedResultMultiset: sameResultMultiset(results, safeNonExecution.allowedResults),
  };
}

export function evaluateCase({ expectation, before, after, events }) {
  const results = events.filter((event) => event.type === "TOOL_CALL_RESULT").map((event) => event.result);
  const terminals = terminalEvents(events);
  const matchedResult = results.find((result) =>
    (!expectation.operation || result?.operation === expectation.operation)
    && (!expectation.status || result?.status === expectation.status),
  );
  const target = expectation.engagementAfter;
  const targetAfter = !target || (() => {
    const engagement = (after.engagements ?? []).find((entry) => entry.id === target.id);
    return !!engagement
      && engagement.status === target.status
      && (target.statusNote === undefined || engagement.statusNote === target.statusNote);
  })();
  const checks = {
    validEventSequence: validEventSequence(events),
    terminalExpected: terminals.length === 1 && events.at(-1) === terminals[0] && terminals[0].type === (expectation.terminal ?? "RUN_FINISHED"),
    structuredResultPolicy: expectation.zeroToolResults ? results.length === 0 : results.length > 0,
    matchedStructuredResult: (!expectation.operation && !expectation.status) || !!matchedResult,
    noCommitted: !expectation.noCommitted || !results.some((result) => result?.status === "committed"),
    stateChanged: expectation.stateChanged === undefined || (stateFingerprint(before) !== stateFingerprint(after)) === expectation.stateChanged,
    engagementAfter: targetAfter,
    onlyNamedEngagementMayChange: !expectation.onlyEngagementMayChange || onlyNamedEngagementMayChange(before, after, expectation.onlyEngagementMayChange),
    onlyExpectedEngagementUpdate: !expectation.exactEngagementUpdate || onlyExpectedEngagementUpdate(before, after, expectation.exactEngagementUpdate),
    resourceMatchesTarget: !expectation.resourceId || (matchedResult?.resource?.kind === "engagement" && matchedResult.resource.id === expectation.resourceId),
    expectedNavigation: !expectation.navigation || (() => {
      const navigationEvents = events.filter((event) => event.type === "NAVIGATION_RESOLVED");
      return navigationEvents.length === 1
        && navigationEvents[0].destination?.id === expectation.navigation.destination.id
        && navigationEvents[0].destination?.path === expectation.navigation.destination.path
        && (expectation.navigation.requestedAtNavigationVersion === undefined
          || navigationEvents[0].requestedAtNavigationVersion === expectation.navigation.requestedAtNavigationVersion);
    })(),
    noNavigation: !expectation.noNavigation || !events.some((event) => event.type === "NAVIGATION_RESOLVED"),
  };
  const primaryPass = Object.values(checks).every(Boolean);
  const safeChecks = safeNonExecutionChecks(expectation.safeNonExecution, {
    before, after, events, results,
    validEventSequence: checks.validEventSequence,
    terminalExpected: checks.terminalExpected,
  });
  const safeNonExecutionPass = safeChecks !== null && Object.values(safeChecks).every(Boolean);
  return {
    pass: primaryPass || safeNonExecutionPass, checks,
    safeNonExecution: safeChecks === null ? null : { pass: safeNonExecutionPass, checks: safeChecks },
    results: results.map((result) => ({ operation: result?.operation, status: result?.status })),
    terminal: terminals[0]?.type ?? null,
  };
}

export function evidencePath(kind, runId) {
  return `evidence/mvp/local-synthetic/${kind}/${runId}`;
}
