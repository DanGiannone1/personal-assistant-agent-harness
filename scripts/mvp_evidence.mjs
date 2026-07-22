import { createHash } from "node:crypto";
import { isIP } from "node:net";

export const MVP_EVAL_SCOPES = Object.freeze(["all", "atomic", "workflow"]);

export function parseMvpEvalScope(value) {
  const scope = value === undefined ? "all" : value;
  if (!MVP_EVAL_SCOPES.includes(scope)) {
    throw new Error(`MVP_EVAL_SCOPE must be one of: ${MVP_EVAL_SCOPES.join(", ")}`);
  }
  return scope;
}

export function selectMvpEvalScope(scopeValue, atomicSuite, workflowSuite) {
  const scope = parseMvpEvalScope(scopeValue);
  const runsAtomic = scope === "all" || scope === "atomic";
  const runsWorkflow = scope === "all" || scope === "workflow";
  if (runsAtomic && !Array.isArray(atomicSuite?.cases)) throw new Error("atomic MVP suite must define cases");
  if (runsWorkflow && !Array.isArray(workflowSuite?.workflows)) throw new Error("workflow MVP suite must define workflows");
  if (scope === "all" && workflowSuite.fixtureVersion !== atomicSuite.fixtureVersion) {
    throw new Error("atomic and workflow fixture versions must match");
  }
  return {
    scope,
    fixtureVersion: runsWorkflow ? workflowSuite.fixtureVersion : atomicSuite.fixtureVersion,
    atomicCases: runsAtomic ? atomicSuite.cases : [],
    workflowDefinitions: runsWorkflow ? workflowSuite.workflows : [],
  };
}

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

export function assistantResponse(events) {
  return events.filter((event) => event.type === "TEXT_MESSAGE_CONTENT").map((event) => event.delta).join("");
}

export function extractToolCalls(events) {
  const open = new Map();
  const completed = [];
  for (const event of events) {
    if (event?.type === "TOOL_CALL_START") {
      open.set(event.tool_call_id, { id: event.tool_call_id, name: event.tool_call_name, argsText: "", result: null });
    } else if (event?.type === "TOOL_CALL_ARGS") {
      const call = open.get(event.tool_call_id);
      if (call) call.argsText += event.delta;
    } else if (event?.type === "TOOL_CALL_RESULT") {
      const call = open.get(event.tool_call_id);
      if (call) call.result = event.result;
    } else if (event?.type === "TOOL_CALL_END") {
      const call = open.get(event.tool_call_id);
      if (!call) continue;
      let args = null;
      if (call.argsText) {
        try { args = JSON.parse(call.argsText); } catch { args = null; }
      } else {
        args = {};
      }
      completed.push({ ...call, args });
      open.delete(event.tool_call_id);
    }
  }
  return completed;
}

function containsExpected(actual, expected) {
  if (expected === null || typeof expected !== "object") return actual === expected;
  if (Array.isArray(expected)) return Array.isArray(actual) && expected.length === actual.length
    && expected.every((value, index) => containsExpected(actual[index], value));
  return !!actual && typeof actual === "object"
    && Object.entries(expected).every(([key, value]) => containsExpected(actual[key], value));
}

function productEvidenceFor(call, rawRecords) {
  return rawRecords.find((record) => record?.kind === "product_tool_execution"
    && record.tool_call_id === call.id
    && record.tool === call.name);
}

function skillInvocations(rawRecords) {
  return rawRecords.filter((record) => record?.kind === "skill_invoked" && record.skill?.name);
}

function normalizeModelVisibleLineEndings(value) {
  return typeof value === "string" ? value.replace(/\r\n/g, "\n") : null;
}

function actorIdFromState(before) {
  const actorId = before?.user?.id;
  return typeof actorId === "string" && actorId.trim() ? actorId.trim().toLowerCase() : null;
}

function memberRoleForActor(engagement, actorId) {
  if (!Array.isArray(engagement?.members) || !actorId) return null;
  const member = engagement.members.find((entry) => entry?.userId === actorId);
  return typeof member?.role === "string" ? member.role : null;
}

function isStringOrAbsent(value) {
  return value === undefined || typeof value === "string";
}

function isAuthoritativeEngagement(engagement, actorId) {
  if (!engagement || typeof engagement !== "object"
    || typeof engagement.id !== "string" || typeof engagement.name !== "string"
    || !isStringOrAbsent(engagement.customer) || typeof engagement.status !== "string"
    || !isStringOrAbsent(engagement.statusNote) || !isStringOrAbsent(engagement.startDate)
    || !isStringOrAbsent(engagement.targetDate) || !isStringOrAbsent(engagement.description)
    || !Array.isArray(engagement.members) || !Array.isArray(engagement.tasks)
    || !Array.isArray(engagement.actions) || !Array.isArray(engagement.milestones)
    || !Array.isArray(engagement.risks) || !Array.isArray(engagement.library)
    || !Array.isArray(engagement.conventions)) return false;
  if (!memberRoleForActor(engagement, actorId)) return false;
  return engagement.members.every((member) => member && typeof member.userId === "string" && typeof member.role === "string")
    && engagement.conventions.every((convention) => convention && typeof convention.text === "string")
    && [
      [engagement.tasks, ["id", "title", "status", "priority", "dueDate"]],
      [engagement.actions, ["id", "title", "status", "owner", "dueDate"]],
      [engagement.milestones, ["id", "title", "status", "dueDate"]],
      [engagement.risks, ["id", "title", "severity", "status"]],
    ].every(([items, fields]) => items.every((item) => item && typeof item.id === "string"
      && fields.every((field) => isStringOrAbsent(item[field]))));
}

function authoritativeEngagements(before) {
  const actorId = actorIdFromState(before);
  if (!actorId || !Array.isArray(before?.engagements)) return null;
  if (!before.engagements.every((engagement) => isAuthoritativeEngagement(engagement, actorId))) return null;
  return { actorId, engagements: before.engagements };
}

function renderAuthorizedEngagementList(before) {
  const state = authoritativeEngagements(before);
  if (!state) return null;
  const { actorId, engagements } = state;
  if (!engagements.length) return "No engagements yet.";
  const lines = [`${engagements.length} engagement(s):`];
  for (const engagement of engagements) {
    const role = memberRoleForActor(engagement, actorId);
    const openTasks = engagement.tasks.filter((task) => task.status !== "Done").length;
    const statusNote = engagement.statusNote ? ` (${engagement.statusNote})` : "";
    lines.push(
      `- [${engagement.id}] ${engagement.name} | your role: ${role} | customer=${engagement.customer || "n/a"} | `
      + `status=${engagement.status}${statusNote} | open tasks=${openTasks} | `
      + `target=${engagement.targetDate || "n/a"} | docs: ${engagement.library.length}`,
    );
  }
  return lines.join("\n");
}

function renderEngagementDetail(before, engagementId) {
  const state = authoritativeEngagements(before);
  if (!state || typeof engagementId !== "string") return null;
  const engagement = state.engagements.find((entry) => entry.id === engagementId);
  if (!engagement) return null;
  const lines = [
    `Engagement [${engagement.id}] ${engagement.name}`,
    `customer=${engagement.customer || "n/a"} | status=${engagement.status || "green"}${engagement.statusNote ? ` (${engagement.statusNote})` : ""} | start=${engagement.startDate || "n/a"} | target=${engagement.targetDate || "n/a"}`,
    "members: " + (engagement.members.map((member) => `${member.userId}(${member.role})`).join(", ") || "none"),
  ];
  if (engagement.description) lines.push(`description: ${engagement.description}`);
  for (const [label, key, fields] of [
    ["tasks", "tasks", ["title", "status", "priority", "dueDate"]],
    ["actions", "actions", ["title", "status", "owner", "dueDate"]],
    ["milestones", "milestones", ["title", "status", "dueDate"]],
    ["risks", "risks", ["title", "severity", "status"]],
  ]) {
    const items = engagement[key];
    if (items.length) {
      lines.push(`${label}:`);
      for (const item of items) {
        const parts = fields.filter((field) => item[field]).map((field) => item[field]);
        lines.push(`- [${item.id}] ${parts.join(" | ")}`);
      }
    }
  }
  lines.push(`artifacts: ${engagement.library.length}`);
  if (engagement.conventions.length) lines.push(`conventions: ${engagement.conventions.map((convention) => convention.text).join("; ")}`);
  return lines.join("\n");
}

function modelVisibleOutputMatches(output, expected) {
  return expected !== null && normalizeModelVisibleLineEndings(output) === expected;
}

function groundedModelVisibleOutputChecks(expectation, before, toolCalls, rawRecords) {
  const specification = expectation.modelVisibleOutput;
  const notRequired = {
    authorizedEngagementIdsGrounded: true,
    engagementDetailFactsGrounded: true,
  };
  if (!specification) return notRequired;
  const matchingCalls = toolCalls.filter((call) => call.name === expectation.toolCall?.name);
  if (specification.kind === "authorizedEngagementList") {
    return {
      authorizedEngagementIdsGrounded: matchingCalls.length > 0 && matchingCalls.every((call) =>
        modelVisibleOutputMatches(
          productEvidenceFor(call, rawRecords)?.model_visible_output,
          renderAuthorizedEngagementList(before),
        )),
      engagementDetailFactsGrounded: true,
    };
  }
  if (specification.kind === "engagementDetail") {
    return {
      authorizedEngagementIdsGrounded: true,
      engagementDetailFactsGrounded: matchingCalls.length > 0 && matchingCalls.every((call) =>
        modelVisibleOutputMatches(
          productEvidenceFor(call, rawRecords)?.model_visible_output,
          renderEngagementDetail(before, specification.engagementId),
        )),
    };
  }
  return {
    authorizedEngagementIdsGrounded: false,
    engagementDetailFactsGrounded: false,
  };
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

// Loopback-only by default (safe). Opt in with MVP_ALLOW_REMOTE=1 to drive the live
// Azure demo stack; then only an https *.azurecontainerapps.io host is accepted.
export function requireTargetUrl(value, label) {
  if (process.env.MVP_ALLOW_REMOTE !== "1") return requireLoopbackUrl(value, label);
  let url;
  try { url = new URL(value); } catch { throw new Error(`${label} must be an absolute http(s) URL`); }
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (url.protocol !== "https:" || !host.endsWith(".azurecontainerapps.io")) {
    throw new Error(`${label} with MVP_ALLOW_REMOTE=1 must be an https *.azurecontainerapps.io host`);
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

// Personal Tasks, Calendar events, and Reminders are actor-scoped aggregates (never shared,
// never Engagement-scoped): app/state already returns only the calling actor's own records,
// so "only this aggregate may change" means every other top-level key is untouched and the
// named aggregate gained exactly the one new record, with all prior records retained as-is.
export function onlyPersonalAggregateMayChange(before, after, aggregateKey) {
  const normalizedBefore = normalizedState(before);
  const normalizedAfter = normalizedState(after);
  const { [aggregateKey]: beforeItems = [], ...beforeElse } = normalizedBefore;
  const { [aggregateKey]: afterItems = [], ...afterElse } = normalizedAfter;
  if (JSON.stringify(beforeElse) !== JSON.stringify(afterElse)) return false;
  if (!Array.isArray(beforeItems) || !Array.isArray(afterItems) || afterItems.length !== beforeItems.length + 1) return false;
  const remaining = [...afterItems];
  for (const entry of beforeItems) {
    const index = remaining.findIndex((candidate) => JSON.stringify(candidate) === JSON.stringify(entry));
    if (index < 0) return false;
    remaining.splice(index, 1);
  }
  return remaining.length === 1;
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
    // Personal-workspace tools report their own literal tool name as the result operation
    // (see _personal_mutation), unlike the canonical Engagement verbs above.
    create_task: "create_task",
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
    exactAllowedResultMultiset: Array.isArray(safeNonExecution.allowedResultAlternatives)
      ? safeNonExecution.allowedResultAlternatives.some((alternative) => sameResultMultiset(results, alternative))
      : sameResultMultiset(results, safeNonExecution.allowedResults),
  };
}

export function evaluateCase({ expectation, before, after, events, rawRecords = [] }) {
  const results = events.filter((event) => event.type === "TOOL_CALL_RESULT").map((event) => event.result);
  const toolCalls = extractToolCalls(events);
  const terminals = terminalEvents(events);
  const matchedResult = results.find((result) =>
    (!expectation.operation || result?.operation === expectation.operation)
    && (!expectation.status || result?.status === expectation.status),
  );
  const target = expectation.engagementAfter;
  const expectedArgumentTarget = expectation.argumentTargetId ?? expectation.resourceId;
  const targetAfter = !target || (() => {
    const engagement = (after.engagements ?? []).find((entry) => entry.id === target.id);
    return !!engagement
      && engagement.status === target.status
      && (target.statusNote === undefined || engagement.statusNote === target.statusNote);
  })();
  const modelVisibleOutputChecks = groundedModelVisibleOutputChecks(expectation, before, toolCalls, rawRecords);
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
    onlyPersonalAggregateMayChange: !expectation.onlyPersonalAggregateMayChange
      || onlyPersonalAggregateMayChange(before, after, expectation.onlyPersonalAggregateMayChange),
    resourceKindMatchesTarget: !expectation.resourceKind || matchedResult?.resource?.kind === expectation.resourceKind,
    resourceMatchesTarget: !expectation.resourceId || (matchedResult?.resource?.kind === "engagement" && matchedResult.resource.id === expectation.resourceId),
    noUnexpectedResourceTargets: !expectation.resourceId || results.every((result) =>
      result?.resource?.kind !== "engagement" || result.resource.id === expectation.resourceId),
    noUnexpectedArgumentTargets: !expectedArgumentTarget || toolCalls.every((call) =>
      call.args?.engagement_id === undefined || call.args.engagement_id === expectedArgumentTarget),
    requiredToolCalls: !expectation.requiredToolNames
      || expectation.requiredToolNames.every((name) => toolCalls.some((call) => call.name === name)),
    forbiddenToolCalls: !expectation.forbiddenToolNames
      || expectation.forbiddenToolNames.every((name) => !toolCalls.some((call) => call.name === name)),
    expectedToolCall: !expectation.toolCall || toolCalls.some((call) => call.name === expectation.toolCall.name
      && call.args !== null && containsExpected(call.args, expectation.toolCall.args ?? {})),
    completeModelVisibleToolEvidence: !expectation.completeToolEvidence || toolCalls.every((call) => {
      const evidence = productEvidenceFor(call, rawRecords);
      return !!evidence
        && containsExpected(evidence.arguments, call.args ?? {})
        && typeof evidence.model_visible_output === "string"
        && evidence.model_visible_output.length > 0
        && JSON.stringify(evidence.product_result) === JSON.stringify(call.result);
    }),
    ...modelVisibleOutputChecks,
    expectedSkillInvocation: !expectation.skill || skillInvocations(rawRecords).some((record) =>
      record.skill.name === expectation.skill.name
      && (!expectation.skill.sha256 || record.skill.sha256 === expectation.skill.sha256)),
    forbiddenSkillInvocation: !expectation.forbiddenSkillNames
      || expectation.forbiddenSkillNames.every((name) => !skillInvocations(rawRecords).some((record) => record.skill.name === name)),
    assistantResponsePresent: !expectation.assistantResponseRequired || assistantResponse(events).trim().length > 0,
    expectedNavigation: !expectation.navigation || (() => {
      const navigationEvents = events.filter((event) => event.type === "NAVIGATION_RESOLVED");
      return navigationEvents.length === 1
        && navigationEvents[0].destination?.id === expectation.navigation.destination.id
        && navigationEvents[0].destination?.path === expectation.navigation.destination.path
        && (expectation.navigation.destination.engagementId === undefined
          || navigationEvents[0].destination?.engagementId === expectation.navigation.destination.engagementId)
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
    toolCalls: toolCalls.map((call) => ({ id: call.id, name: call.name, args: call.args, result: call.result })),
    assistantResponse: assistantResponse(events),
    terminal: terminals[0]?.type ?? null,
  };
}

export function evaluateWorkflow({ definition, resetCount, sessionId, before, turns, after }) {
  const expectedTurns = definition.turns ?? [];
  const turnResults = turns.map((turn, index) => evaluateCase({
    expectation: expectedTurns[index]?.expectation ?? {},
    before: turn.before,
    after: turn.after,
    events: turn.events,
    rawRecords: turn.rawRecords,
  }));
  const finalExpected = definition.finalEngagement;
  const finalEngagement = !finalExpected ? null : (after.engagements ?? []).find((entry) => entry.id === finalExpected.id);
  const checks = {
    resetExactlyOnce: resetCount === 1,
    expectedTurnCount: turns.length === expectedTurns.length,
    oneSession: typeof sessionId === "string" && !!sessionId && turns.every((turn) => turn.sessionId === sessionId),
    continuousState: turns.every((turn, index) => index === 0
      ? stateFingerprint(turn.before) === stateFingerprint(before)
      : stateFingerprint(turn.before) === stateFingerprint(turns[index - 1].after)),
    allTurnsPass: turnResults.length === expectedTurns.length && turnResults.every((result) => result.pass),
    finalEngagement: !finalExpected || (!!finalEngagement
      && finalEngagement.status === finalExpected.status
      && finalEngagement.statusNote === finalExpected.statusNote),
  };
  const groundingTurn = turnResults[definition.groundingTurn ?? 0];
  return {
    pass: Object.values(checks).every(Boolean),
    checks,
    turnResults,
    groundingReview: {
      status: "REVIEW_REQUIRED",
      question: "Does the meeting brief contain only facts present in the captured model-visible tool outputs?",
      assistantResponse: groundingTurn?.assistantResponse ?? "",
      evidenceRecordKinds: ["product_tool_execution", "skill_invoked"],
    },
  };
}

export function evidencePath(kind, runId) {
  return `evidence/mvp/local-synthetic/${kind}/${runId}`;
}
