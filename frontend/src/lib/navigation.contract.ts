import { normalizeHostRoute, shouldApplyAgentNavigation, shouldQueueAgentNavigation } from "./navigation";
import { createStreamState, validateEvent } from "./sse";
import { decodeAppState, decodeContextBundle, decodeEngagement, decodeFilesPayload, decodeFileWrite, decodeSessionMetadata, decodeSessionUpload } from "./payload";
import type { AppState, Destination } from "./types";

const appState = { engagements: [{ id: "eng-1" }] } as AppState;
const valid: Destination = { id: "engagement_tasks", engagementId: "eng-1", path: "/engagements/eng-1/tasks" };

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

expect(normalizeHostRoute("/engagements/eng-1/tasks/task-1") === "/engagements/eng-1/tasks/task-1", "canonical Engagement task route must persist");
expect(normalizeHostRoute("/engagements/eng-1/artifacts/artifact-1") === "/engagements", "artifact routes cannot carry a record id");
expect(normalizeHostRoute("/engagements/eng-1/documents") === "/engagements", "legacy document route must be rejected");
expect(normalizeHostRoute("/engagements/eng-1/settings/member-1") === "/engagements", "settings routes cannot carry a record id");

expect(shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "valid structured event must navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "other", requestedAtNavigationVersion: 4, destination: valid } }), "run mismatch must not navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 5, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "newer manual navigation must win");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: true, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "cancelled run must not navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: { ...valid, path: "/engagements/eng-1/evil" } } }), "mismatched path must not navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: { id: "marker" as Destination["id"], path: "NAVIGATE: /engagements" } } }), "marker-like text cannot navigate");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: { ...valid, engagementId: "../eng-1", path: "/engagements/../eng-1/tasks" } } }), "malformed Engagement ID cannot navigate");

// Navigation is queued only while its run/version/cancellation contract still holds.
// A refreshed authoritative state decides whether a scoped Engagement is visible.
expect(shouldQueueAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "newly visible destination must queue");
expect(shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "newly visible destination must apply after refresh");
expect(!shouldApplyAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: false, appState: { engagements: [] } as unknown as AppState, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "forbidden or not-visible destination must be discarded after refresh");
expect(!shouldQueueAgentNavigation({ activeRunId: "run-1", navigationVersion: 4, cancelled: true, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "cancelled queued navigation must be discarded");
expect(!shouldQueueAgentNavigation({ activeRunId: "run-1", navigationVersion: 5, cancelled: false, event: { runId: "run-1", requestedAtNavigationVersion: 4, destination: valid } }), "manual supersession must discard queued navigation");

function rejects(events: unknown[]): void { const state = createStreamState(); let failed = false; try { events.forEach((event) => validateEvent(event, state)); } catch { failed = true; } expect(failed, "invalid stream sequence must reject"); }
const stream = createStreamState();
validateEvent({ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, stream);
validateEvent({ type: "TEXT_MESSAGE_START", message_id: "m", role: "assistant" }, stream);
validateEvent({ type: "TEXT_MESSAGE_CONTENT", message_id: "m", delta: "x" }, stream);
validateEvent({ type: "TEXT_MESSAGE_END", message_id: "m" }, stream);
validateEvent({ type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "navigate" }, stream);
validateEvent({ type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "resolved", code: "n", operation: "navigate", destination: { id: "engagements", path: "/engagements" } } }, stream);
validateEvent({ type: "NAVIGATION_RESOLVED", runId: "r", destination: { id: "engagements", path: "/engagements" }, requestedAtNavigationVersion: 0 }, stream);
validateEvent({ type: "TOOL_CALL_END", tool_call_id: "c" }, stream);
validateEvent({ type: "RUN_FINISHED", run_id: "r", thread_id: "t" }, stream);
rejects([{ type: "NAVIGATION_RESOLVED", runId: "r", destination: {}, requestedAtNavigationVersion: 0 }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "x" }, { type: "TOOL_CALL_END", tool_call_id: "c" }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "x" }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "failed", code: "x", operation: "x" } }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "failed", code: "x", operation: "x" } }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "RUN_FINISHED", run_id: "wrong", thread_id: "t" }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "x" }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "invented", code: "x", operation: "x" } }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "x" }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "failed", code: "x", operation: "x", resource: "not-an-object" } }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "navigate" }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "resolved", code: "n", operation: "navigate", destination: { id: "workbench", path: "/home" } } }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "navigate" }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "resolved", code: "n", operation: "navigate", destination: { id: "engagement_artifacts", engagementId: "eng-1", path: "/engagements/eng-1/artifacts/extra" } } }]);
rejects([{ type: "RUN_STARTED", run_id: "r", thread_id: "t" }, { type: "TOOL_CALL_START", tool_call_id: "c", tool_call_name: "navigate" }, { type: "TOOL_CALL_RESULT", tool_call_id: "c", result: { status: "resolved", code: "n", operation: "navigate", destination: { id: "engagement_artifacts", engagementId: "eng-1", path: "/engagements/eng-1/documents" } } }]);
const preRun = createStreamState(); validateEvent({ type: "RUN_ERROR", message: "transport" }, preRun); rejects([{ type: "RUN_ERROR", message: "one" }, { type: "RUN_ERROR", message: "two" }]);

function decoderRejects(decode: () => unknown, message: string): void {
  let failed = false; try { decode(); } catch { failed = true; } expect(failed, message);
}
decoderRejects(() => decodeSessionMetadata({ session_id: 7, status: "ready" }), "session decoder rejects malformed session id");
decoderRejects(() => decodeSessionUpload({ path: "/tmp/a", filename: "a.md", size: 4, markdown_ready: "yes" }), "upload decoder rejects malformed write flag");
decoderRejects(() => decodeFileWrite({ filename: "draft.md", size: -1 }), "file-write decoder rejects invalid byte size");
decoderRejects(() => decodeFilesPayload({ files: [{ filename: "draft.md", size: "large", modified_at: "now", has_markdown: true }] }), "file decoder rejects malformed file metadata");
decoderRejects(() => decodeContextBundle({ user: {}, persona: {}, conventions: [], engagementName: null, workingContext: {}, precedence: [] }), "context decoder rejects malformed user");
decoderRejects(() => decodeAppState({ currentRoute: "/engagements", engagements: [{ id: "eng-1", status: "blue", members: [], conventions: [], tasks: [], library: [], activity: [] }], user: { id: "u", username: "u", displayName: "U" } }), "state decoder rejects unsupported engagement status");
decoderRejects(() => decodeEngagement({ id: "eng-1", name: "Record", description: "", customer: "", status: "green", statusNote: "", startDate: "", targetDate: "", members: [{ userId: "u", role: "admin" }], conventions: [], tasks: [], library: [], activity: [], createdAt: "now", createdBy: "u" }), "engagement decoder rejects unsupported role");
