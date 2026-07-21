import { notifyAuthExpired, withAppAuth } from "./appAuth";
import { AGUIEvent } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// A turn can legitimately go quiet for a while when the model reads a large
// uploaded document and prepares the first response chunk.
const INACTIVITY_TIMEOUT_MS = Number(
  process.env.NEXT_PUBLIC_SSE_INACTIVITY_TIMEOUT_MS || "600000",
);

const KNOWN_TYPES = new Set([
  "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
  "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_RESULT", "TOOL_CALL_END",
  "NAVIGATION_RESOLVED", "RUN_FINISHED", "RUN_ERROR", "REASONING_START",
  "REASONING_DELTA", "REASONING_END",
]);
const TOOL_STATUSES = new Set([
  "committed", "resolved", "succeeded", "noop", "needs_confirmation", "ambiguous",
  "invalid", "not_found", "forbidden", "conflict", "failed",
]);
const ENGAGEMENT_ID = /^[A-Za-z0-9_-]{1,128}$/;

function requireString(value: unknown, field: string): asserts value is string {
  if (typeof value !== "string" || !value) throw new Error(`Malformed assistant event: ${field}`);
}

function requireDestination(value: unknown): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Malformed assistant destination");
  const destination = value as Record<string, unknown>;
  if (!Object.keys(destination).every((key) => ["id", "path", "engagementId", "label"].includes(key))) throw new Error("Malformed assistant destination");
  requireString(destination.id, "destination.id");
  requireString(destination.path, "destination.path");
  if (destination.label !== undefined) requireString(destination.label, "destination.label");
  if (destination.id === "engagements") {
    if (destination.path !== "/engagements" || destination.engagementId !== undefined) throw new Error("Malformed assistant destination");
    return;
  }
  if (typeof destination.engagementId !== "string" || !ENGAGEMENT_ID.test(destination.engagementId)) throw new Error("Malformed assistant destination");
  const suffix = destination.id === "engagement_overview" ? "" : destination.id === "engagement_tasks" ? "/tasks" : destination.id === "engagement_artifacts" ? "/artifacts" : null;
  if (suffix === null || destination.path !== `/engagements/${destination.engagementId}${suffix}`) throw new Error("Malformed assistant destination");
}

function requireProductToolResult(value: unknown): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Malformed tool result");
  const result = value as Record<string, unknown>;
  requireString(result.status, "result.status");
  if (!TOOL_STATUSES.has(result.status)) throw new Error("Malformed tool result status");
  requireString(result.code, "result.code");
  requireString(result.operation, "result.operation");
  if (result.message !== undefined && typeof result.message !== "string") throw new Error("Malformed tool result message");
  if (result.resource !== undefined && (!result.resource || typeof result.resource !== "object" || Array.isArray(result.resource))) throw new Error("Malformed tool result resource");
  if (result.destination !== undefined) requireDestination(result.destination);
}

export type StreamState = { started: boolean; terminal: boolean; runId: string | null; threadId: string | null; messageId: string | null; tools: Map<string, { phase: "started" | "result"; result?: Record<string, unknown>; navigated: boolean }> };
export function createStreamState(): StreamState { return { started: false, terminal: false, runId: null, threadId: null, messageId: null, tools: new Map() }; }
export function validateEvent(event: unknown, state: StreamState): AGUIEvent {
  if (!event || typeof event !== "object" || Array.isArray(event)) throw new Error("Malformed assistant event");
  const value = event as Record<string, unknown>;
  requireString(value.type, "type");
  if (!KNOWN_TYPES.has(value.type)) throw new Error(`Unknown assistant event type: ${value.type}`);
  if (state.terminal) throw new Error("Assistant event after terminal");
  if (!state.started && value.type !== "RUN_STARTED" && value.type !== "RUN_ERROR") throw new Error("Assistant stream must start with RUN_STARTED");
  switch (value.type) {
    case "RUN_STARTED":
      if (state.started) throw new Error("Duplicate RUN_STARTED");
      requireString(value.run_id, "run_id"); requireString(value.thread_id, "thread_id"); state.runId = value.run_id; state.threadId = value.thread_id; state.started = true; break;
    case "TEXT_MESSAGE_START": if (state.messageId) throw new Error("Overlapping text messages"); state.messageId = (requireString(value.message_id, "message_id"), value.message_id as string); requireString(value.role, "role"); break;
    case "TEXT_MESSAGE_CONTENT": if ((requireString(value.message_id, "message_id"), value.message_id) !== state.messageId) throw new Error("Text content without matching start"); requireString(value.delta, "delta"); break;
    case "TEXT_MESSAGE_END": if ((requireString(value.message_id, "message_id"), value.message_id) !== state.messageId) throw new Error("Text end without matching start"); state.messageId = null; break;
    case "TOOL_CALL_START":
      requireString(value.tool_call_id, "tool_call_id"); requireString(value.tool_call_name, "tool_call_name"); if (state.tools.has(value.tool_call_id)) throw new Error("Duplicate tool start"); state.tools.set(value.tool_call_id, { phase: "started", navigated: false }); break;
    case "TOOL_CALL_ARGS": requireString(value.tool_call_id, "tool_call_id"); if (state.tools.get(value.tool_call_id)?.phase !== "started") throw new Error("Tool args out of order"); requireString(value.delta, "delta"); break;
    case "TOOL_CALL_RESULT": {
      requireString(value.tool_call_id, "tool_call_id"); if (state.tools.get(value.tool_call_id)?.phase !== "started") throw new Error("Tool result out of order");
      const result = value.result;
      requireProductToolResult(result);
      state.tools.set(value.tool_call_id, { phase: "result", result, navigated: false }); break;
    }
    case "TOOL_CALL_END": requireString(value.tool_call_id, "tool_call_id"); if (state.tools.get(value.tool_call_id)?.phase !== "result") throw new Error("Tool end out of order"); state.tools.delete(value.tool_call_id); break;
    case "NAVIGATION_RESOLVED": { requireString(value.runId, "runId"); requireDestination(value.destination); if (value.runId !== state.runId || !Number.isInteger(value.requestedAtNavigationVersion)) throw new Error("Malformed navigation event"); const matches = [...state.tools.values()].filter((tool) => tool.phase === "result" && !tool.navigated && tool.result?.status && ["resolved", "committed"].includes(tool.result.status as string) && JSON.stringify(tool.result.destination) === JSON.stringify(value.destination)); if (matches.length !== 1) throw new Error("Navigation not bound to a tool result"); matches[0].navigated = true; break; }
    case "RUN_FINISHED": requireString(value.run_id, "run_id"); requireString(value.thread_id, "thread_id"); if (value.run_id !== state.runId || value.thread_id !== state.threadId || state.tools.size || state.messageId) throw new Error("Invalid terminal"); state.terminal = true; break;
    case "RUN_ERROR": requireString(value.message, "message"); if (state.tools.size || state.messageId) throw new Error("Invalid error terminal"); state.terminal = true; break;
  }
  return value as AGUIEvent;
}

export async function* streamSSE(
  prompt: string,
  signal: AbortSignal,
  sessionId: string,
  navigationVersion: number,
): AsyncGenerator<AGUIEvent> {
  const url = `${API_BASE}/sessions/${sessionId}/messages`;
  const headers = await withAppAuth({ "Content-Type": "application/json" });

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ prompt, navigation_version: navigationVersion }),
    signal,
  });

  if (res.status === 401) {
    notifyAuthExpired();
    yield { type: "RUN_ERROR", message: "Signed out — please sign in again." };
    return;
  }
  if (!res.ok) {
    yield { type: "RUN_ERROR", message: `HTTP ${res.status}: ${res.statusText}` };
    return;
  }

  if (!res.body) {
    yield { type: "RUN_ERROR", message: "Empty response body" } as AGUIEvent;
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "";
  let inactivityTimer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;
  const eventState = createStreamState();

  function resetInactivityTimer() {
    if (inactivityTimer) clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(() => { timedOut = true; reader.cancel(); }, INACTIVITY_TIMEOUT_MS);
  }

  resetInactivityTimer();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      resetInactivityTimer();
      try { buffer += decoder.decode(value, { stream: true }); }
      catch { throw new Error("Malformed UTF-8 assistant stream"); }

      while (true) {
        const separator = /\r?\n\r?\n/.exec(buffer);
        if (!separator || separator.index === undefined) break;
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        if (!frame.trim()) continue;
        const data = frame.replace(/\r\n/g, "\n").split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart());
        if (data.length !== 1) throw new Error("Malformed assistant stream frame");
        let event: unknown;
        try { event = JSON.parse(data[0]); } catch { throw new Error("Malformed assistant event JSON"); }
        const validated = validateEvent(event, eventState);
        yield validated;
        if (eventState.terminal) { await reader.cancel(); return; }
      }
    }

    // On inactivity timeout, don't replay any buffered event (a stale RUN_FINISHED
    // would otherwise finalize the turn before the timeout error surfaces).
    if (timedOut) {
      yield { type: "RUN_ERROR", message: "The assistant stopped responding (timed out). Please try again." };
      return;
    }

    try { buffer += decoder.decode(); } catch { throw new Error("Malformed UTF-8 assistant stream"); }
    if (buffer.trim()) throw new Error("Truncated assistant stream frame");
    if (!eventState.terminal) throw new Error("Assistant stream ended without a terminal event");
  } finally {
    if (inactivityTimer) clearTimeout(inactivityTimer);
  }
}
