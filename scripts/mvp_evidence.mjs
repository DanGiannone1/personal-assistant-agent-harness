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
  const starts = events.filter((event) => event?.type === "RUN_STARTED");
  const terminals = terminalEvents(events);
  const runId = events[0]?.run_id;
  const threadId = events[0]?.thread_id;
  if (starts.length !== 1 || typeof runId !== "string" || !runId || typeof threadId !== "string" || !threadId) return false;
  if (terminals.length !== 1 || events.at(-1) !== terminals[0]) return false;
  if (terminals[0].type === "RUN_FINISHED" && (terminals[0].run_id !== runId || terminals[0].thread_id !== threadId)) return false;
  if (terminals[0].type === "RUN_ERROR" && (typeof terminals[0].message !== "string" || !terminals[0].message)) return false;
  const tools = new Map();
  for (const event of events) {
    if (!event || typeof event.type !== "string") return false;
    if (event.type === "TOOL_CALL_START") {
      if (typeof event.tool_call_id !== "string" || !event.tool_call_id || typeof event.tool_call_name !== "string" || !event.tool_call_name || tools.has(event.tool_call_id)) return false;
      tools.set(event.tool_call_id, { phase: "started", navigationBound: false });
    } else if (event.type === "TOOL_CALL_RESULT") {
      const tool = tools.get(event.tool_call_id);
      const result = event.result;
      if (!tool || tool.phase !== "started" || !result || typeof result !== "object"
        || typeof result.status !== "string" || !result.status
        || typeof result.code !== "string" || !result.code
        || typeof result.operation !== "string" || !result.operation) return false;
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
      tool.phase = "ended";
    }
  }
  return [...tools.values()].every((tool) => tool.phase === "ended");
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
  return {
    pass: Object.values(checks).every(Boolean), checks,
    results: results.map((result) => ({ operation: result?.operation, status: result?.status })),
    terminal: terminals[0]?.type ?? null,
  };
}

export function evidencePath(kind, runId) {
  return `evidence/mvp/local-synthetic/${kind}/${runId}`;
}
