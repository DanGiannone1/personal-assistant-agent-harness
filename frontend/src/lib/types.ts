export type AGUIEvent =
  | { type: "RUN_STARTED"; thread_id: string; run_id: string }
  | { type: "TEXT_MESSAGE_START"; message_id: string; role: string }
  | { type: "TEXT_MESSAGE_CONTENT"; message_id: string; delta: string }
  | { type: "TEXT_MESSAGE_END"; message_id: string }
  | { type: "TOOL_CALL_START"; tool_call_id: string; tool_call_name: string; parent_message_id?: string }
  | { type: "TOOL_CALL_ARGS"; tool_call_id: string; delta: string }
  | { type: "TOOL_CALL_RESULT"; tool_call_id: string; outcome: ToolOutcome; candidates?: NavCandidate[] }
  | { type: "TOOL_CALL_END"; tool_call_id: string }
  | { type: "RUN_FINISHED"; thread_id: string; run_id: string }
  | { type: "RUN_ERROR"; message: string }
  | { type: "REASONING_START" }
  | { type: "REASONING_DELTA"; delta: string }
  | { type: "REASONING_END" };

export type ToolOutcome = "ok" | "noop" | "error";

// A fully-bound navigation candidate surfaced in the trace — ambiguous/not-found pickers, or
// the "decided with alternates" escape hatch on ok outcomes. `path` is click-ready (no round-trip).
export interface NavCandidate {
  title: string;
  path: string;
}

// The signed-in app-level user (spec F1). Shape mirrors the /auth/login + /auth/me payloads.
export interface AuthUser {
  id: string;
  username: string;
  displayName: string;
}

export type MessagePart =
  | { type: "text"; content: string }
  | { type: "reasoning"; content: string }
  | { type: "tool_call"; tool: string; toolCallId: string; status: "running" | "done"; args?: string; outcome?: ToolOutcome; candidates?: NavCandidate[] };

export interface TurnMeta {
  steps: number;       // tool calls in the turn
  durationMs: number;  // wall-clock from run start to finish
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  isStreaming: boolean;
  parts: MessagePart[];
  meta?: TurnMeta;
}

export interface FileInfo {
  filename: string;
  size: number;
  modified_at: string;
  has_markdown: boolean;
  origin?: "uploaded" | "generated";
}

export interface AppFile {
  filename: string;
  size: number;
  modified_at: string;
  origin: "uploaded" | "generated";
  status: "pending" | "ready";
  has_markdown: boolean;
}

// ── Personal Assistant application state (rendered by the right-pane app) ───────────────────
// Two record types: Tasks (a to-do board) and calendar Events.
export type TaskStatus = "To do" | "In progress" | "Blocked" | "Done";
export type TaskPriority = "Low" | "Medium" | "High";

export interface Subtask {
  text: string;
  done: boolean;
}

export interface Task {
  id: string;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  group: string;          // free-form bucket (Work, Personal, …)
  dueDate?: string;       // YYYY-MM-DD
  subtasks?: Subtask[];
  notes?: string;
  createdAt?: string;
}

// Named CalendarEvent so it never clashes with the DOM `Event` type.
export interface CalendarEvent {
  id: string;
  title: string;
  date: string;           // YYYY-MM-DD
  start?: string;         // 24h HH:MM
  end?: string;           // 24h HH:MM
  type?: string;          // Meeting | Reminder | Focus | …
  notes?: string;
}

export interface Schedule {
  id: string;
  title: string;
  prompt: string;
  frequency: "daily" | "weekly";
  time: string;             // 24h HH:MM, in `timezone`
  timezone: string;         // IANA, e.g. America/New_York
  daysOfWeek?: number[];    // weekly only; Mon=0 … Sun=6
  enabled: boolean;
  channel?: string;         // "email"
  lastRunAt?: string | null;
  lastStatus?: string | null;
  nextRunAt?: string | null;
}

export interface LibraryDoc {
  id: string;
  filename: string;
  title: string;
  savedAt?: string;
  source?: string;          // "reference" (seeded) | "upload" (promoted)
}

// ── Projects (shared, membership-scoped spaces) ─────────────────────────────
export type ProjectRole = "owner" | "editor" | "viewer";

export interface ProjectMember {
  userId: string;
  role: ProjectRole;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  archived: boolean;
  members: ProjectMember[];
  conventions: string[];
  tasks: Task[];
  events: CalendarEvent[];
  library: LibraryDoc[];
  createdAt?: string;
  role: ProjectRole;      // the signed-in user's role in this project
}

// A server-ranked quick link (recency + salience, max 5) rendered as one-click nav chips.
export interface QuickLink {
  path: string;
  title: string;
}

export interface AppState {
  currentRoute: string;
  tasks: Task[];
  events: CalendarEvent[];
  routes: { path: string; title: string; keywords?: string[] }[];
  schedules: Schedule[];
  library: LibraryDoc[];
  projects: Project[];
  quickLinks: QuickLink[];
}
