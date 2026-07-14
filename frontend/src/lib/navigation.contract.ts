import { shouldApplyAgentNavigation } from "./navigation";
import { createStreamState, validateEvent } from "./sse";
import type { AppState, Destination } from "./types";

const appState = { engagements: [{ id: "eng-1" }] } as AppState;
const valid: Destination = { id: "engagement_tasks", engagementId: "eng-1", path: "/engagements/eng-1/tasks" };

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

expect(shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "valid structured event must navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "other", requestedAtNavigationVersion: 4, destination: valid } }), "run mismatch must not navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 5, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "newer manual navigation must win");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: true, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "cancelled run must not navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: { ...valid, path: "/engagements/eng-1/evil" } } }), "mismatched path must not navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: { id: "marker" as Destination["id"], path: "NAVIGATE: /engagements" } } }), "marker-like text cannot navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: { ...valid, engagementId: "../eng-1", path: "/engagements/../eng-1/tasks" } } }), "malformed Engagement ID cannot navigate");

function rejects(events: unknown[]): void { const state = createStreamState(); let failed = false; try { events.forEach((event) => validateEvent(event, state)); } catch { failed = true; } expect(failed, "invalid stream sequence must reject"); }
const stream = createStreamState();
validateEvent({ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, stream);
validateEvent({ type: "TEXT_MESSAGE_START", message_id: "m", role: "assistant" }, stream);
validateEvent({ type: "TEXT_MESSAGE_CONTENT", message_id: "m", delta: "x" }, stream);
validateEvent({ type: "TEXT_MESSAGE_END", message_id: "m" }, stream);
validateEvent({ type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "navigate" }, stream);
validateEvent({ type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "resolved", code: "n", operation: "navigate", destination: { id: "workbench", path: "/home" } } }, stream);
validateEvent({ type: "NAVIGATION_RESOLVED", runId: "r", destination: { id: "workbench", path: "/home" }, requestedAtNavigationVersion: 0 }, stream);
validateEvent({ type: "TOOL_CALL_END", tool_call_id: "c" }, stream);
validateEvent({ type: "RUN_FINISHED", run_id: "r", thread_id: "t" }, stream);
rejects([{ type: "NAVIGATION_RESOLVED", runId: "r", destination: {}, requestedAtNavigationVersion: 0 }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "x" }, { type: "TOOL_CALL_END", tool_call_id: "c" }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "x" }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "failed", code: "x", operation: "x" } }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "failed", code: "x", operation: "x" } }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "RUN_FINISHED", run_id: "wrong", thread_id: "t" }]);
const preRun = createStreamState(); validateEvent({ type: "RUN_ERROR", message: "transport" }, preRun); rejects([{ type: "RUN_ERROR", message: "one" }, { type: "RUN_ERROR", message: "two" }]);
