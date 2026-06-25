import { useReducer, useRef, useCallback, useEffect, useState } from "react";
import { AGUIEvent, AppFile, AppState, ChatMessage, MessagePart, ToolOutcome } from "@/lib/types";
import { streamSSE } from "@/lib/sse";
import { createSession, deleteSession, getSession, getAppState, listFiles, uploadFile, saveToLibrary as apiSaveToLibrary, deleteFromLibrary as apiDeleteFromLibrary } from "@/lib/api";
import { clearSessionId, getSessionId, getStoredMessages, storeSessionId, storeMessages } from "@/lib/session";
import { friendlyError } from "@/lib/utils";

// Tools that set the server-side currentRoute when they succeed. When one of
// these completes with an "ok" outcome, the pane should follow the route.
const ROUTE_SETTING_TOOLS = new Set([
  "navigate",
  "create_task",   // lands the user on the new task's detail page
  "update_task",   // lands the user on the updated task
  "delete_task",   // returns the user to the to-do list
  "add_subtask",   // lands the user on the task it added a step to
  "create_event",  // lands the user on the calendar
  "update_event",  // lands the user on the calendar
  "delete_event",  // returns the user to the calendar
]);

type Action =
  | { type: "USER_SEND"; content: string }
  | { type: "RUN_STARTED"; runId: string }
  | { type: "ASSISTANT_START"; messageId: string }
  | { type: "DELTA"; delta: string }
  | { type: "MESSAGE_END" }
  | { type: "TOOL_START"; toolCallId: string; toolCallName: string }
  | { type: "TOOL_ARGS"; toolCallId: string; delta: string }
  | { type: "TOOL_RESULT"; toolCallId: string; outcome: ToolOutcome; candidates?: string[] }
  | { type: "TOOL_END"; toolCallId: string }
  | { type: "SET_TURN_META"; steps: number; durationMs: number }
  | { type: "DONE" }
  | { type: "ERROR"; message: string }
  | { type: "SET_SESSION_ID"; sessionId: string }
  | { type: "SET_INITIALIZING"; value: boolean }
  | { type: "RESTORE_SESSION"; sessionId: string; messages: ChatMessage[] }
  | { type: "RESET_FOR_NEW_CHAT" }
  | { type: "FILE_PENDING"; filename: string; size: number }
  | { type: "FILE_CLEAR_PENDING"; filename: string }
  | { type: "FILES_LOADED"; files: AppFile[] }
  | { type: "APP_STATE_LOADED"; appState: AppState; follow: boolean }
  | { type: "SET_VIEW_ROUTE"; route: string }
  | { type: "SESSION_ERROR"; error: string | null };

interface State {
  messages: ChatMessage[];
  isStreaming: boolean;
  sessionId: string | null;
  isInitializing: boolean;
  currentRunId: string | null;
  files: AppFile[];
  appState: AppState | null;
  viewRoute: string;
  appRoute: string;        // last server-side currentRoute we observed
  newRecordIds: string[];  // task/event ids that appeared on the latest refetch (for highlight)
  sessionError: string | null;
}

const SESSION_TIMEOUT_MS = 12_000;
const UPLOAD_TIMEOUT_MS = 180_000;

function normalizeFiles(raw: AppFile[]): AppFile[] {
  const byName = new Map(raw.map((f) => [f.filename, f]));
  return raw
    .filter((f) => {
      if (!f.filename.endsWith(".md")) return true;
      const sourceName = f.filename.slice(0, -3);
      return !byName.has(sourceName);
    })
    .map((f): AppFile => ({
      filename: f.filename,
      size: f.size,
      modified_at: f.modified_at,
      origin: f.origin ?? "generated",
      status: "ready",
      has_markdown: f.has_markdown,
    }))
    .sort((a, b) => Date.parse(b.modified_at) - Date.parse(a.modified_at));
}

function updateLastMessage(msgs: ChatMessage[], updater: (msg: ChatMessage) => ChatMessage): ChatMessage[] {
  if (msgs.length === 0) return msgs;
  const copy = [...msgs];
  copy[copy.length - 1] = updater({ ...copy[copy.length - 1] });
  return copy;
}

function createUserMessage(content: string): ChatMessage {
  return { id: crypto.randomUUID(), role: "user", isStreaming: false, parts: [{ type: "text", content }] };
}

function createAssistantMessage(id: string, parts: MessagePart[], isStreaming: boolean): ChatMessage {
  return { id, role: "assistant", isStreaming, parts };
}

function finalizeAssistantMessage(msg: ChatMessage): ChatMessage {
  if (msg.role !== "assistant") return msg;
  const parts = msg.parts.map((p) =>
    p.type === "tool_call" && p.status === "running" ? { ...p, status: "done" as const } : p,
  );
  return { ...msg, parts, isStreaming: false };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "SET_SESSION_ID": return { ...state, sessionId: action.sessionId };
    case "SET_INITIALIZING": return { ...state, isInitializing: action.value };
    case "SESSION_ERROR": return { ...state, sessionError: action.error };
    case "RESET_FOR_NEW_CHAT":
      return {
        ...state, messages: [], isStreaming: false, sessionId: null, currentRunId: null,
        files: [], appState: null, viewRoute: "/home", appRoute: "/home", newRecordIds: [], sessionError: null,
      };
    case "USER_SEND":
      return {
        ...state, isStreaming: true, newRecordIds: [],  // "New" badges mean "created this turn"
        messages: [
          ...state.messages,
          createUserMessage(action.content),
          createAssistantMessage(`pending-${crypto.randomUUID()}`, [], true),
        ],
      };
    case "RUN_STARTED": return { ...state, currentRunId: action.runId };
    case "ASSISTANT_START": {
      if (state.messages.length === 0) return { ...state, messages: [createAssistantMessage(action.messageId, [], true)] };
      const last = state.messages[state.messages.length - 1];
      if (last.role === "assistant" && last.isStreaming && last.id.startsWith("pending-")) {
        return { ...state, messages: updateLastMessage(state.messages, (m) => ({ ...m, id: action.messageId })) };
      }
      if (last.role === "assistant" && last.isStreaming && state.currentRunId) return state;
      return { ...state, messages: [...state.messages, createAssistantMessage(action.messageId, [], true)] };
    }
    case "DELTA": {
      if (state.messages.length === 0) return state;
      return {
        ...state,
        messages: updateLastMessage(state.messages, (m) => {
          const parts = [...m.parts];
          const lastPart = parts[parts.length - 1];
          if (lastPart && lastPart.type === "text") {
            parts[parts.length - 1] = { ...lastPart, content: lastPart.content + action.delta };
          } else {
            parts.push({ type: "text", content: action.delta });
          }
          return { ...m, parts };
        }),
      };
    }
    case "MESSAGE_END": return { ...state, messages: updateLastMessage(state.messages, (m) => finalizeAssistantMessage(m)) };
    case "TOOL_START": {
      if (state.messages.length === 0) return state;
      return {
        ...state,
        messages: updateLastMessage(state.messages, (m) => ({
          ...m,
          parts: [...m.parts, { type: "tool_call" as const, tool: action.toolCallName, toolCallId: action.toolCallId, status: "running" as const }],
        })),
      };
    }
    case "TOOL_ARGS": {
      if (state.messages.length === 0) return state;
      return {
        ...state,
        messages: updateLastMessage(state.messages, (m) => ({
          ...m,
          parts: m.parts.map((p) =>
            p.type === "tool_call" && p.toolCallId === action.toolCallId ? { ...p, args: (p.args || "") + action.delta } : p,
          ),
        })),
      };
    }
    case "TOOL_RESULT": {
      if (state.messages.length === 0) return state;
      return {
        ...state,
        messages: updateLastMessage(state.messages, (m) => ({
          ...m,
          parts: m.parts.map((p) =>
            p.type === "tool_call" && p.toolCallId === action.toolCallId ? { ...p, outcome: action.outcome, candidates: action.candidates } : p,
          ),
        })),
      };
    }
    case "SET_TURN_META":
      return { ...state, messages: updateLastMessage(state.messages, (m) => (m.role === "assistant" ? { ...m, meta: { steps: action.steps, durationMs: action.durationMs } } : m)) };
    case "TOOL_END": {
      if (state.messages.length === 0) return state;
      return {
        ...state,
        messages: updateLastMessage(state.messages, (m) => ({
          ...m,
          parts: m.parts.map((p) =>
            p.type === "tool_call" && p.toolCallId === action.toolCallId ? { ...p, status: "done" as const } : p,
          ),
        })),
      };
    }
    case "DONE": return { ...state, isStreaming: false, currentRunId: null, messages: updateLastMessage(state.messages, (m) => finalizeAssistantMessage(m)) };
    case "ERROR": {
      const msgs = [...state.messages];
      if (msgs.length > 0 && msgs[msgs.length - 1].role === "assistant") {
        return {
          ...state, isStreaming: false, currentRunId: null,
          messages: updateLastMessage(msgs, (m) => ({ ...m, parts: [...m.parts, { type: "text" as const, content: `\n\n${action.message}` }], isStreaming: false })),
        };
      }
      msgs.push(createAssistantMessage(crypto.randomUUID(), [{ type: "text", content: action.message }], false));
      return { ...state, messages: msgs, isStreaming: false, currentRunId: null };
    }
    case "RESTORE_SESSION":
      return { ...state, sessionId: action.sessionId, messages: action.messages, isInitializing: false, sessionError: null };
    case "FILE_PENDING": {
      const pending: AppFile = { filename: action.filename, size: action.size, modified_at: new Date().toISOString(), origin: "uploaded", status: "pending", has_markdown: false };
      return { ...state, files: [pending, ...state.files.filter((f) => f.filename !== action.filename)] };
    }
    case "FILE_CLEAR_PENDING":
      return { ...state, files: state.files.filter((f) => !(f.status === "pending" && f.filename === action.filename)) };
    case "FILES_LOADED": {
      const serverNames = new Set(action.files.map((f) => f.filename));
      const stillPending = state.files.filter((f) => f.status === "pending" && !serverNames.has(f.filename));
      return { ...state, files: [...stillPending, ...action.files] };
    }
    case "APP_STATE_LOADED": {
      const serverRoute = action.appState.currentRoute || "/home";
      // Tasks/events that appeared since the last snapshot — highlight them in the pane.
      const prevIds = new Set<string>([
        ...(state.appState?.tasks ?? []).map((t) => t.id),
        ...(state.appState?.events ?? []).map((e) => e.id),
      ]);
      const newRecordIds = state.appState
        ? [...action.appState.tasks, ...action.appState.events].map((r) => r.id).filter((id) => !prevIds.has(id))
        : [];
      return {
        ...state,
        appState: action.appState,
        appRoute: serverRoute,
        // Follow the server route only when a navigation-intent tool ran this
        // turn — NOT on every value change. A human clicking back to the
        // dashboard leaves the server route untouched, so re-navigating to the
        // same place must still move the pane (the old change-heuristic dropped it).
        viewRoute: action.follow ? serverRoute : state.viewRoute,
        newRecordIds: newRecordIds.length > 0 ? newRecordIds : state.newRecordIds,
      };
    }
    case "SET_VIEW_ROUTE": return { ...state, viewRoute: action.route };
    default: return state;
  }
}

const initialState: State = {
  messages: [], isStreaming: false, sessionId: null, isInitializing: true,
  currentRunId: null, files: [], appState: null, viewRoute: "/home",
  appRoute: "/home", newRecordIds: [], sessionError: null,
};

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, timeoutMessage: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
    promise.then((value) => { clearTimeout(timer); resolve(value); }).catch((error) => { clearTimeout(timer); reject(error); });
  });
}

function viewLabel(appState: AppState | null, route: string): string {
  if (!appState) return "Home";
  if (route.startsWith("/todo/")) {
    const t = appState.tasks.find((x) => x.id === route.split("/").pop());
    return t ? `the "${t.title}" task` : "Tasks";
  }
  if (route === "/todo") return "Tasks";
  if (route === "/calendar") return "Calendar";
  if (route === "/documents") return "Documents";
  return "Home";
}

export function useAgentSession() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [chatUploadName, setChatUploadName] = useState<string | null>(null);
  const [isChatUploading, setIsChatUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const streamingRef = useRef(false);
  const viewRouteRef = useRef<string>("/home");
  const appStateRef = useRef<AppState | null>(null);
  const runStartRef = useRef<number>(0);
  const stepCountRef = useRef<number>(0);
  const inFlightRef = useRef(false);
  // Tracks whether a navigation-intent tool succeeded during the current turn,
  // so the pane follows the server route even when re-navigating to where the
  // server already pointed. Keyed lookups need the tool name from TOOL_CALL_START.
  const routeFollowRef = useRef(false);
  const toolNamesRef = useRef<Map<string, string>>(new Map());
  // Set when the user manually navigates (sidebar/card) after an agent nav this turn —
  // suppresses a trailing refetch from yanking the pane back over a deliberate click.
  const userNavSinceToolRef = useRef(false);
  // Monotonic sequence so out-of-order app-state refetches can't apply a stale snapshot:
  // only the most-recently-issued refresh's result is allowed to dispatch (last-issued-wins).
  const appStateSeqRef = useRef(0);
  // Set on Stop so buffered events arriving after abort don't re-finalize/re-refresh a cancelled turn.
  const cancelledRef = useRef(false);

  useEffect(() => { sessionIdRef.current = state.sessionId; }, [state.sessionId]);
  useEffect(() => { streamingRef.current = state.isStreaming; }, [state.isStreaming]);
  useEffect(() => { viewRouteRef.current = state.viewRoute; }, [state.viewRoute]);
  useEffect(() => { appStateRef.current = state.appState; }, [state.appState]);

  const clearAndDeleteSession = useCallback(async (sessionId: string | null) => {
    if (!sessionId) return;
    clearSessionId();
    try { await deleteSession(sessionId); } catch { /* best effort */ }
  }, []);

  const refreshFiles = useCallback(async (sessionId: string) => {
    try {
      const data = await listFiles(sessionId);
      dispatch({ type: "FILES_LOADED", files: normalizeFiles(data.files as AppFile[]) });
    } catch { /* non-fatal */ }
  }, []);

  const refreshAppState = useCallback(async (sessionId: string, follow = false) => {
    const seq = ++appStateSeqRef.current;
    try {
      const appState = await getAppState(sessionId);
      // Drop a stale snapshot: if a newer refresh was issued while this one was in
      // flight, only the newer one may apply (prevents an out-of-order resolve from
      // clobbering the pane with pre-mutation state and miscomputing newRecordIds).
      if (seq !== appStateSeqRef.current) return;
      dispatch({ type: "APP_STATE_LOADED", appState, follow });
    } catch { /* non-fatal — pane keeps last state */ }
  }, []);

  const restoreStoredSession = useCallback(async (storedId: string): Promise<boolean> => {
    // Returns true if restored, false ONLY when the session is genuinely gone (404 → null).
    // Transient errors (500/timeout/network) THROW so the caller surfaces an error and
    // does NOT delete + recreate — wiping a valid session on a blip would lose the workspace.
    const meta = await withTimeout(getSession(storedId), SESSION_TIMEOUT_MS, "Session check timed out");
    if (!meta) return false;
    dispatch({ type: "RESTORE_SESSION", sessionId: meta.session_id, messages: getStoredMessages() });
    // On reload, restore the pane to wherever the session last was (no human-click
    // ambiguity exists at initial load), so a browser refresh doesn't reset to Dashboard.
    await Promise.all([refreshAppState(meta.session_id, true), refreshFiles(meta.session_id)]);
    return true;
  }, [refreshAppState, refreshFiles]);

  const startSession = useCallback(async () => {
    setStatusMessage(null);
    dispatch({ type: "SESSION_ERROR", error: null });
    dispatch({ type: "SET_INITIALIZING", value: true });
    const storedId = getSessionId();
    try {
      // A transient failure here throws and is caught below WITHOUT deleting the session.
      if (storedId && (await restoreStoredSession(storedId))) return;
      // No stored session, or it's genuinely gone (404) — start fresh.
      await clearAndDeleteSession(storedId);
      const meta = await withTimeout(createSession(), SESSION_TIMEOUT_MS, "Session creation timed out");
      storeSessionId(meta.session_id);
      dispatch({ type: "SET_SESSION_ID", sessionId: meta.session_id });
      await Promise.all([refreshAppState(meta.session_id, true), refreshFiles(meta.session_id)]);
    } catch (err) {
      dispatch({ type: "SESSION_ERROR", error: friendlyError(err, "Could not reach your session. Retry.") });
    } finally {
      dispatch({ type: "SET_INITIALIZING", value: false });
    }
  }, [clearAndDeleteSession, restoreStoredSession, refreshAppState, refreshFiles]);

  useEffect(() => { startSession(); }, [startSession]);

  useEffect(() => {
    if (!state.isStreaming && state.messages.length > 0) storeMessages(state.messages);
  }, [state.isStreaming, state.messages]);

  const navigateView = useCallback((route: string) => {
    // A deliberate manual nav: a trailing same-turn refetch must not yank the pane back.
    userNavSinceToolRef.current = true;
    dispatch({ type: "SET_VIEW_ROUTE", route });
  }, []);

  const handleAGUIEvent = useCallback((event: AGUIEvent) => {
    // Once the user hit Stop, ignore buffered events from the cancelled turn so they
    // don't re-finalize it or re-refresh state the user chose to stop watching.
    if (cancelledRef.current && event.type !== "RUN_STARTED") return;
    switch (event.type) {
      case "RUN_STARTED": runStartRef.current = performance.now(); stepCountRef.current = 0; routeFollowRef.current = false; userNavSinceToolRef.current = false; cancelledRef.current = false; toolNamesRef.current.clear(); dispatch({ type: "RUN_STARTED", runId: event.run_id }); break;
      case "TEXT_MESSAGE_START": dispatch({ type: "ASSISTANT_START", messageId: event.message_id }); break;
      case "TEXT_MESSAGE_CONTENT": dispatch({ type: "DELTA", delta: event.delta }); break;
      case "TEXT_MESSAGE_END": dispatch({ type: "MESSAGE_END" }); break;
      case "TOOL_CALL_START":
        if (event.tool_call_name !== "skill") stepCountRef.current += 1;
        toolNamesRef.current.set(event.tool_call_id, event.tool_call_name);
        dispatch({ type: "TOOL_START", toolCallId: event.tool_call_id, toolCallName: event.tool_call_name });
        break;
      case "TOOL_CALL_ARGS": dispatch({ type: "TOOL_ARGS", toolCallId: event.tool_call_id, delta: event.delta }); break;
      case "TOOL_CALL_RESULT": {
        // Follow the route only when a navigation-intent tool actually succeeded
        // (an ambiguous/not-found navigate stays put). Emitted just before TOOL_CALL_END.
        const toolName = toolNamesRef.current.get(event.tool_call_id);
        if (event.outcome === "ok" && toolName && ROUTE_SETTING_TOOLS.has(toolName)) {
          routeFollowRef.current = true;
          // A fresh agent nav supersedes any earlier manual nav this turn.
          userNavSinceToolRef.current = false;
        }
        dispatch({ type: "TOOL_RESULT", toolCallId: event.tool_call_id, outcome: event.outcome, candidates: event.candidates });
        break;
      }
      case "TOOL_CALL_END":
        dispatch({ type: "TOOL_END", toolCallId: event.tool_call_id });
        // A tool may have mutated workspace state (navigation, CRUD) — refetch so the pane reflects it live.
        if (sessionIdRef.current) void refreshAppState(sessionIdRef.current, routeFollowRef.current && !userNavSinceToolRef.current);
        break;
      case "RUN_FINISHED":
        if (runStartRef.current) dispatch({ type: "SET_TURN_META", steps: stepCountRef.current, durationMs: Math.round(performance.now() - runStartRef.current) });
        dispatch({ type: "DONE" });
        if (sessionIdRef.current) { void refreshAppState(sessionIdRef.current, routeFollowRef.current && !userNavSinceToolRef.current); void refreshFiles(sessionIdRef.current); }
        break;
      case "RUN_ERROR":
        dispatch({ type: "ERROR", message: event.message || "Error during generation." });
        if (sessionIdRef.current) { void refreshAppState(sessionIdRef.current, routeFollowRef.current && !userNavSinceToolRef.current); void refreshFiles(sessionIdRef.current); }
        break;
    }
  }, [refreshAppState, refreshFiles]);

  const handleSend = useCallback(async (content: string) => {
    // inFlightRef is synchronous — guards against two sends in the same tick,
    // before isStreaming/streamingRef flip on the next render.
    if (!state.sessionId || state.isStreaming || streamingRef.current || inFlightRef.current) return;
    // Everything from here is inside try/finally so inFlightRef can never get stuck
    // true (a throw in the synchronous prelude would otherwise block all future sends).
    inFlightRef.current = true;
    cancelledRef.current = false;
    let controller: AbortController | null = null;
    try {
      dispatch({ type: "USER_SEND", content });
      abortRef.current?.abort();
      controller = new AbortController();
      abortRef.current = controller;
      // Attach today's date + the user's current view so the agent never guesses "today"
      // (deadline/overdue questions need the real date) and can resolve "here" / "this".
      const label = viewLabel(appStateRef.current, viewRouteRef.current);
      const today = new Date().toISOString().slice(0, 10);
      const prompt = `[Today: ${today}] [Current view: ${label}]\n\n${content}`;
      for await (const event of streamSSE(prompt, controller.signal, state.sessionId)) { handleAGUIEvent(event); }
      if (streamingRef.current) dispatch({ type: "DONE" });
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      dispatch({ type: "ERROR", message: friendlyError(err, "Message failed.") });
    } finally {
      inFlightRef.current = false;
      if (controller && abortRef.current === controller) abortRef.current = null;
    }
  }, [handleAGUIEvent, state.sessionId, state.isStreaming]);

  const handleChatUpload = useCallback(async (file: File) => {
    if (!state.sessionId) return;
    setIsChatUploading(true); setChatUploadName(file.name);
    dispatch({ type: "FILE_PENDING", filename: file.name, size: file.size });
    try {
      await withTimeout(uploadFile(state.sessionId, file), UPLOAD_TIMEOUT_MS, "Upload timed out");
      dispatch({ type: "FILE_CLEAR_PENDING", filename: file.name });
      await refreshFiles(state.sessionId);
    } catch (err) {
      dispatch({ type: "FILE_CLEAR_PENDING", filename: file.name });
      dispatch({ type: "ERROR", message: friendlyError(err, "File upload failed.") });
    } finally {
      setIsChatUploading(false); setChatUploadName(null);
    }
  }, [state.sessionId, refreshFiles]);

  // Manual upload from the Documents screen (no AI) — reuses the chat-upload path.
  const uploadDocument = useCallback(async (file: File) => {
    await handleChatUpload(file);
  }, [handleChatUpload]);

  // Promote a session file into the persistent Library, then refresh state + files so it
  // moves from "This session" to "Library". Manual (works without the AI).
  const saveToLibrary = useCallback(async (filename: string) => {
    if (!state.sessionId) return;
    await apiSaveToLibrary(state.sessionId, filename);
    await Promise.all([refreshAppState(state.sessionId), refreshFiles(state.sessionId)]);
  }, [state.sessionId, refreshAppState, refreshFiles]);

  const removeFromLibrary = useCallback(async (filename: string) => {
    if (!state.sessionId) return;
    await apiDeleteFromLibrary(state.sessionId, filename);
    await Promise.all([refreshAppState(state.sessionId), refreshFiles(state.sessionId)]);
  }, [state.sessionId, refreshAppState, refreshFiles]);

  // Re-pull app state after a manual CRUD mutation (tasks/events/reminders), so the UI
  // reflects the same owner doc the agent mutates.
  const refresh = useCallback(async () => {
    if (state.sessionId) await refreshAppState(state.sessionId);
  }, [state.sessionId, refreshAppState]);

  const handleStop = useCallback(() => {
    if (streamingRef.current) {  // synchronous — not the render-captured state
      cancelledRef.current = true;  // ignore any buffered events from the cancelled turn
      abortRef.current?.abort();
      abortRef.current = null;
      dispatch({ type: "DONE" });
    }
  }, []);

  const doNewChat = useCallback(async () => {
    abortRef.current?.abort(); abortRef.current = null;
    await clearAndDeleteSession(state.sessionId);
    setStatusMessage(null);
    dispatch({ type: "RESET_FOR_NEW_CHAT" });
    dispatch({ type: "SET_INITIALIZING", value: true });
    await startSession();
  }, [clearAndDeleteSession, state.sessionId, startSession]);

  return {
    state, statusMessage, isChatUploading, chatUploadName,
    handleSend, handleStop, handleChatUpload, doNewChat, startSession, navigateView,
    uploadDocument, saveToLibrary, removeFromLibrary, refresh,
  };
}
