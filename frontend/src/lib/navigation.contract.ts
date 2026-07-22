import { isHostRoute, normalizeHostRoute, shouldApplyAgentNavigation, shouldQueueAgentNavigation } from "./navigation";
import { createStreamState, validateEvent } from "./sse";
import { decodeAppState, decodeCalendarEvent, decodeContextBundle, decodeEngagement, decodeFilesPayload, decodeFileWrite, decodeReminder, decodeSessionMetadata, decodeSessionUpload, decodeTask } from "./payload";
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

// Personal-workspace routes (My work): Home, Tasks, Calendar, Reminders.
expect(normalizeHostRoute("/home") === "/home", "home route must persist");
expect(normalizeHostRoute("/todo") === "/todo", "tasks route must persist");
expect(normalizeHostRoute("/todo/t-1") === "/todo/t-1", "task detail route must persist");
expect(normalizeHostRoute("/todo/") === "/engagements", "trailing-slash task route must be rejected");
expect(normalizeHostRoute("/todo/t 1") === "/engagements", "task detail route rejects an unsafe record id");
expect(normalizeHostRoute("/calendar") === "/calendar", "calendar route must persist");
expect(normalizeHostRoute("/reminders") === "/reminders", "reminders route must persist");
for (const route of ["/home", "/engagements", "/engagements/eng-1", "/todo", "/todo/t-1", "/calendar", "/reminders", "/settings"]) {
  expect(isHostRoute(route), `${route} must be recognized as a host route`);
}
expect(!isHostRoute("/assistant"), "AI Mode must not be recognized as a host route");
expect(!isHostRoute("/todo/unsafe id"), "unsafe paths must not be recognized as host routes");

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

const blankPersonaState = decodeAppState({
  currentRoute: "/engagements",
  personalTasks: [], calendarEvents: [], reminders: [],
  engagements: [{ id: "eng-1", name: "Record", description: "", customer: "", status: "green", statusNote: "", startDate: "", targetDate: "", members: [], conventions: [], tasks: [], library: [], activity: [], createdAt: "now", createdBy: "u" }],
  user: { id: "u", username: "u", displayName: "U", persona: { role: "Product lead", tone: "concise", outputPrefs: "", language: "English" } },
});
expect(blankPersonaState.user.persona?.outputPrefs === undefined, "state decoder accepts an empty optional persona preference");

// Personal workspace: app state carries the actor's own Tasks/Calendar/Reminders
// alongside shared Engagements — the decoder must accept the full shape.
const richAppState = decodeAppState({
  currentRoute: "/home",
  personalTasks: [{
    id: "t-1", title: "Draft the plan", status: "In progress", priority: "High", group: "Work",
    dueDate: "2030-02-28", notes: "private", createdAt: "2030-01-01T00:00:00+00:00",
    subtasks: [{ text: "Outline", done: true }],
  }],
  calendarEvents: [{ id: "e-1", title: "Planning", date: "2030-02-28", start: "09:00", end: "09:30", type: "Focus", notes: "" }],
  reminders: [{
    id: "s-1", title: "Weekly review", message: "Plan the week.", frequency: "weekly",
    dueDate: "2030-01-07", time: "09:00", timezone: "UTC", daysOfWeek: [0], enabled: true,
    nextDueAt: "2030-01-07T09:00:00+00:00", createdAt: "2030-01-01T00:00:00+00:00",
    lastSentAt: "2030-01-07T09:00:05+00:00", lastStatus: "sent",
  }],
  engagements: [],
  user: { id: "u", username: "u", displayName: "U" },
});
expect(richAppState.personalTasks.length === 1 && richAppState.personalTasks[0].title === "Draft the plan", "state decoder accepts personalTasks");
expect(richAppState.calendarEvents.length === 1 && richAppState.calendarEvents[0].type === "Focus", "state decoder accepts calendarEvents");
expect(richAppState.reminders.length === 1 && richAppState.reminders[0].lastStatus === "sent", "state decoder accepts reminders with delivery status");

decoderRejects(() => decodeAppState({
  currentRoute: "/home",
  personalTasks: [{ id: "t-1", title: "x", status: "Unknown", priority: "High", group: "Work" }],
  calendarEvents: [], reminders: [], engagements: [], user: { id: "u", username: "u", displayName: "U" },
}), "state decoder rejects malformed personalTasks");
decoderRejects(() => decodeAppState({
  currentRoute: "/home", personalTasks: [],
  calendarEvents: [{ id: "e-1", title: "x", date: "2030-01-01", start: "", end: "", type: "Other", notes: "" }],
  reminders: [], engagements: [], user: { id: "u", username: "u", displayName: "U" },
}), "state decoder rejects malformed calendarEvents");
decoderRejects(() => decodeAppState({
  currentRoute: "/home", personalTasks: [], calendarEvents: [],
  reminders: [{ id: "s-1", title: "x", message: "", frequency: "monthly", dueDate: "2030-01-01", time: "09:00", timezone: "UTC", daysOfWeek: [], enabled: true, nextDueAt: null, createdAt: "now" }],
  engagements: [], user: { id: "u", username: "u", displayName: "U" },
}), "state decoder rejects malformed reminders");
decoderRejects(() => decodeReminder({ id: "s-1", title: "x", message: "", frequency: "weekly", dueDate: "2030-01-01", time: "09:00", timezone: "UTC", daysOfWeek: [7], enabled: true, nextDueAt: null, createdAt: "now" }), "reminder decoder rejects an out-of-range day of week");
decoderRejects(() => decodeTask({ id: "t-1", title: "x", status: "To do", priority: "High", group: "Work", subtasks: [{ text: "a", done: "yes" }] }), "task decoder rejects a non-boolean subtask flag");
decoderRejects(() => decodeCalendarEvent({ id: "e-1", title: "x", date: "2030-01-01", start: "", end: "", type: "Other", notes: "" }), "event decoder rejects an unsupported event type");
