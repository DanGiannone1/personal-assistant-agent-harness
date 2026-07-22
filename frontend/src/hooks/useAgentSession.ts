import { useReducer, useRef, useCallback, useEffect, useState } from "react";
import { AGUIEvent, AppFile, AppState, ChatMessage, ContextBundle, Destination, MessagePart, ProductToolResult } from "@/lib/types";
import { streamSSE } from "@/lib/sse";
import { normalizeHostRoute, shouldApplyAgentNavigation, shouldQueueAgentNavigation } from "@/lib/navigation";
import { createSession, deleteSession, getSession, getAppState, listFiles, uploadFile, getContextBundle } from "@/lib/api";
import { clearSessionId, getSessionId, getStoredMessages, storeSessionId, storeMessages } from "@/lib/session";
import { friendlyError } from "@/lib/utils";

type Action =
  | { type: "USER_SEND"; content: string }
  | { type: "RUN_STARTED"; runId: string }
  | { type: "ASSISTANT_START"; messageId: string }
  | { type: "DELTA"; delta: string }
  | { type: "MESSAGE_END" }
  | { type: "REASONING_START" }
  | { type: "REASONING_DELTA"; delta: string }
  | { type: "TOOL_START"; toolCallId: string; toolCallName: string }
  | { type: "TOOL_ARGS"; toolCallId: string; delta: string }
  | { type: "TOOL_RESULT"; toolCallId: string; result: ProductToolResult }
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
  | { type: "BUNDLE_USED"; bundle: ContextBundle | null }
  | { type: "SESSION_ERROR"; error: string | null }
  | { type: "WORKSPACE_REFRESH_FAILED"; error: string | null };

interface State {
  messages: ChatMessage[];
  isStreaming: boolean;
  sessionId: string | null;
  isInitializing: boolean;
  currentRunId: string | null;
  files: AppFile[];
  appState: AppState | null;
  viewRoute: string;
  viewRouteRevision: number;
  lastBundle: ContextBundle | null; // what personalized the most recent turn (inspector)
  sessionError: string | null;
  workspaceStale: string | null;
}

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
    case "WORKSPACE_REFRESH_FAILED": return { ...state, workspaceStale: action.error };
    case "RESET_FOR_NEW_CHAT":
      return {
        ...state, messages: [], isStreaming: false, sessionId: null, currentRunId: null,
        files: [], appState: null, viewRoute: "/home", sessionError: null, workspaceStale: null,
      };
    case "USER_SEND":
      return {
        ...state, isStreaming: true,
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
    case "REASONING_START": {
      if (state.messages.length === 0) return state;
      return {
        ...state,
        messages: updateLastMessage(state.messages, (m) => ({
          ...m, parts: [...m.parts, { type: "reasoning" as const, content: "" }],
        })),
      };
    }
    case "REASONING_DELTA": {
      if (state.messages.length === 0) return state;
      return {
        ...state,
        messages: updateLastMessage(state.messages, (m) => {
          const parts = [...m.parts];
          const lastPart = parts[parts.length - 1];
          if (lastPart && lastPart.type === "reasoning") {
            parts[parts.length - 1] = { ...lastPart, content: lastPart.content + action.delta };
          } else {
            parts.push({ type: "reasoning" as const, content: action.delta });
          }
          return { ...m, parts };
        }),
      };
    }
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
            p.type === "tool_call" && p.toolCallId === action.toolCallId ? { ...p, result: action.result } : p,
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
      const serverRoute = normalizeHostRoute(action.appState.currentRoute || "/home");
      return {
        ...state,
        appState: action.appState,
        workspaceStale: null,
        // Follow a server route only during initialization; manual route changes remain local.
        viewRoute: action.follow ? serverRoute : normalizeHostRoute(state.viewRoute),
      };
    }
    case "SET_VIEW_ROUTE": return {
      ...state,
      viewRoute: action.route,
      viewRouteRevision: state.viewRouteRevision + 1,
    };
    case "BUNDLE_USED": return { ...state, lastBundle: action.bundle };
    default: return state;
  }
}

const initialState: State = {
  messages: [], isStreaming: false, sessionId: null, isInitializing: true,
  currentRunId: null, files: [], appState: null, viewRoute: "/home", viewRouteRevision: 0,
  lastBundle: null, sessionError: null, workspaceStale: null,
};

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, timeoutMessage: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(timeoutMessage)), timeoutMs);
    promise.then((value) => { clearTimeout(timer); resolve(value); }).catch((error) => { clearTimeout(timer); reject(error); });
  });
}

function viewLabel(appState: AppState | null, route: string): string {
  if (!appState) return "Engagements";
  if (route === "/engagements") return "Engagements";
  if (route.startsWith("/engagements/")) return "Engagement";
  if (route === "/settings") return "Settings";
  if (route === "/home") return "Home";
  if (route.startsWith("/todo/")) {
    const task = appState.personalTasks.find((entry) => entry.id === route.split("/").pop());
    return task ? `the "${task.title}" task` : "Tasks";
  }
  if (route === "/todo") return "Tasks";
  if (route === "/calendar") return "Calendar";
  if (route === "/reminders") return "Reminders";
  return "Engagements";
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
  const navigationVersionRef = useRef(0);
  // Unlike reducer state, this remains bound through RUN_FINISHED while a route
  // waits for its authoritative refresh. A newer RUN_STARTED replaces it.
  const navigationRunIdRef = useRef<string | null>(null);
  // Monotonic sequence so out-of-order app-state refetches can't apply a stale snapshot:
  // only the most-recently-issued refresh's result is allowed to dispatch (last-issued-wins).
  const appStateSeqRef = useRef(0);
  // Superseded callers inherit the latest authoritative refresh outcome rather
  // than treating an obsolete response as a successful refresh.
  const latestAppStateRefreshRef = useRef<Promise<void> | null>(null);
  // Set on Stop so buffered events arriving after abort don't re-finalize/re-refresh a cancelled turn.
  const cancelledRef = useRef(false);
  const pendingNavigationRef = useRef<{ runId: string; destination: Destination; requestedAtNavigationVersion: number } | null>(null);

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

  const refreshAppState = useCallback((sessionId: string, follow = false): Promise<void> => {
    const seq = ++appStateSeqRef.current;
    const refreshPromise = Promise.resolve().then(async () => {
      const awaitLatest = async () => {
        const latest = latestAppStateRefreshRef.current;
        if (latest && latest !== refreshPromise) await latest;
      };
      try {
        const appState = await getAppState(sessionId);
        // A superseded caller must adopt the latest request's result. This chains
        // naturally if that request is itself superseded before it settles.
        if (seq !== appStateSeqRef.current) return await awaitLatest();
        appStateRef.current = appState;
        dispatch({ type: "APP_STATE_LOADED", appState, follow });
        if (seq !== appStateSeqRef.current) await awaitLatest();
      } catch (err) {
        if (seq !== appStateSeqRef.current) return await awaitLatest();
        dispatch({ type: "WORKSPACE_REFRESH_FAILED", error: friendlyError(err, "Could not refresh the workspace. Your last saved view may be out of date.") });
        throw err;
      }
    });
    latestAppStateRefreshRef.current = refreshPromise;
    return refreshPromise;
  }, []);

  const restoreStoredSession = useCallback(async (storedId: string): Promise<boolean> => {
    // Returns true if restored, false ONLY when the session is genuinely gone (404 → null).
    // Transient errors (500/timeout/network) THROW so the caller surfaces an error and
    // does NOT delete + recreate — wiping a valid session on a blip would lose the workspace.
    const meta = await getSession(storedId);
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
      const meta = await createSession();
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
    navigationVersionRef.current += 1;
    pendingNavigationRef.current = null;
    dispatch({ type: "SET_VIEW_ROUTE", route: normalizeHostRoute(route) });
    // A manual destination may expose changes another member made since this tab's
    // last read. Keep navigation immediate while reconciling the owned session.
    if (sessionIdRef.current) void refreshAppState(sessionIdRef.current).catch(() => undefined);
  }, [refreshAppState]);

  const handleAGUIEvent = useCallback((event: AGUIEvent) => {
    // Once the user hit Stop, ignore buffered events from the cancelled turn so they
    // don't re-finalize it or re-refresh state the user chose to stop watching.
    if (cancelledRef.current && event.type !== "RUN_STARTED") return;
    switch (event.type) {
      case "RUN_STARTED": runStartRef.current = performance.now(); stepCountRef.current = 0; cancelledRef.current = false; navigationRunIdRef.current = event.run_id; dispatch({ type: "RUN_STARTED", runId: event.run_id }); break;
      case "TEXT_MESSAGE_START": dispatch({ type: "ASSISTANT_START", messageId: event.message_id }); break;
      case "TEXT_MESSAGE_CONTENT": dispatch({ type: "DELTA", delta: event.delta }); break;
      case "TEXT_MESSAGE_END": dispatch({ type: "MESSAGE_END" }); break;
      case "REASONING_START": dispatch({ type: "REASONING_START" }); break;
      case "REASONING_DELTA": dispatch({ type: "REASONING_DELTA", delta: event.delta }); break;
      case "REASONING_END": break;
      case "TOOL_CALL_START":
        if (event.tool_call_name !== "skill") stepCountRef.current += 1;
        dispatch({ type: "TOOL_START", toolCallId: event.tool_call_id, toolCallName: event.tool_call_name });
        break;
      case "TOOL_CALL_ARGS": dispatch({ type: "TOOL_ARGS", toolCallId: event.tool_call_id, delta: event.delta }); break;
      case "TOOL_CALL_RESULT": dispatch({ type: "TOOL_RESULT", toolCallId: event.tool_call_id, result: event.result }); break;
      case "NAVIGATION_RESOLVED":
        if (!shouldQueueAgentNavigation({ activeRunId: navigationRunIdRef.current, navigationVersion: navigationVersionRef.current, cancelled: cancelledRef.current, event }) || !sessionIdRef.current) break;
        pendingNavigationRef.current = event;
        void refreshAppState(sessionIdRef.current).then(() => {
          const pending = pendingNavigationRef.current;
          if (!pending) return;
          pendingNavigationRef.current = null;
          if (shouldApplyAgentNavigation({ activeRunId: navigationRunIdRef.current, navigationVersion: navigationVersionRef.current, cancelled: cancelledRef.current, event: pending, appState: appStateRef.current })) {
            dispatch({ type: "SET_VIEW_ROUTE", route: pending.destination.path });
          }
        }).catch(() => { pendingNavigationRef.current = null; });
        break;
      case "TOOL_CALL_END":
        dispatch({ type: "TOOL_END", toolCallId: event.tool_call_id });
        if (sessionIdRef.current) void refreshAppState(sessionIdRef.current).catch(() => undefined);
        break;
      case "RUN_FINISHED":
        if (runStartRef.current) dispatch({ type: "SET_TURN_META", steps: stepCountRef.current, durationMs: Math.round(performance.now() - runStartRef.current) });
        dispatch({ type: "DONE" });
        if (sessionIdRef.current) { void refreshAppState(sessionIdRef.current).catch(() => undefined); void refreshFiles(sessionIdRef.current); }
        break;
      case "RUN_ERROR":
        pendingNavigationRef.current = null;
        dispatch({ type: "ERROR", message: event.message || "Error during generation." });
        if (sessionIdRef.current) { void refreshAppState(sessionIdRef.current).catch(() => undefined); void refreshFiles(sessionIdRef.current); }
        break;
    }
  }, [refreshAppState, refreshFiles]);

  const handleSend = useCallback(async (content: string) => {
    const requestedNavigationVersion = navigationVersionRef.current;
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
      // Compose the per-turn context bundle (persona, conventions) and inject
      // it as a LEGIBLE preamble — the inspector renders the same bundle, so what the
      // user can audit is exactly what the model received. Precedence is stated inline.
      const label = viewLabel(appStateRef.current, viewRouteRef.current);
      const today = new Date().toISOString().slice(0, 10);
      let preamble = `[Today: ${today}] [Current view: ${label}]`;
      try {
        const bundle = await getContextBundle(viewRouteRef.current);
        dispatch({ type: "BUNDLE_USED", bundle });
        preamble += ` [User: ${bundle.user.displayName}]`;
        const p = bundle.persona || {};
        const personaBits = [p.role, p.tone, p.outputPrefs, p.language && p.language !== "English" ? `writes in ${p.language}` : ""].filter(Boolean);
        if (personaBits.length) preamble += `\n[Persona: ${personaBits.join("; ")}]`;
        if (bundle.conventions.length) preamble += `\n[Engagement conventions — ${bundle.engagementName}: ${bundle.conventions.map((c) => c.text).join(" | ")}]`;
        if (bundle.conventions.length || personaBits.length) {
          preamble += `\n[Precedence: the user's instruction in this message overrides engagement conventions, which override persona defaults.]`;
        }
      } catch {
        // Bundle unavailable (endpoint down): the turn still runs with date+view; the
        // inspector will show that no personalization applied rather than guessing.
        dispatch({ type: "BUNDLE_USED", bundle: null });
      }
      const prompt = `${preamble}\n\n${content}`;
      for await (const event of streamSSE(prompt, controller.signal, state.sessionId, requestedNavigationVersion)) { handleAGUIEvent(event); }
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

  // Re-pull state after a manual Engagement mutation.
  const refresh = useCallback(async () => {
    if (state.sessionId) await refreshAppState(state.sessionId);
  }, [state.sessionId, refreshAppState]);

  const handleStop = useCallback(() => {
    if (streamingRef.current) {  // synchronous — not the render-captured state
      cancelledRef.current = true;  // ignore any buffered events from the cancelled turn
      pendingNavigationRef.current = null;
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
    refresh,
  };
}
