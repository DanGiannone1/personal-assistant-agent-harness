export type AGUIEvent =
  | { type: "RUN_STARTED"; thread_id: string; run_id: string }
  | { type: "TEXT_MESSAGE_START"; message_id: string; role: string }
  | { type: "TEXT_MESSAGE_CONTENT"; message_id: string; delta: string }
  | { type: "TEXT_MESSAGE_END"; message_id: string }
  | { type: "TOOL_CALL_START"; tool_call_id: string; tool_call_name: string; parent_message_id?: string }
  | { type: "TOOL_CALL_ARGS"; tool_call_id: string; delta: string }
  | { type: "TOOL_CALL_RESULT"; tool_call_id: string; outcome: ToolOutcome; candidates?: NavCandidate[]; card?: ToolCard }
  | { type: "TOOL_CALL_END"; tool_call_id: string }
  | { type: "RUN_FINISHED"; thread_id: string; run_id: string }
  | { type: "RUN_ERROR"; message: string }
  | { type: "REASONING_START" }
  | { type: "REASONING_DELTA"; delta: string }
  | { type: "REASONING_END" };

export type ToolOutcome = "ok" | "noop" | "error";

// A navigate chip, fully bound to a real route by the resolver. Clicking one is a
// plain manual navigation — no second resolution pass, no chat round-trip.
export interface NavCandidate {
  title: string;
  path: string;
}

export type MessagePart =
  | { type: "text"; content: string }
  | { type: "reasoning"; content: string }
  | { type: "tool_call"; tool: string; toolCallId: string; status: "running" | "done"; args?: string; outcome?: ToolOutcome; candidates?: NavCandidate[]; card?: ToolCard };

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

// ── CSA Workbench application state (rendered by the right-pane app) ───────────────────────
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

// Structured preview card a mutating tool attaches to its result: the UI renders the
// record (or the pending action) so prose can never stand in for what happened.
export interface ToolCard {
  kind: "confirm" | "record";
  action?: string;      // confirm: the tool to re-call with confirmed=true
  title?: string;
  detail?: string;
  recordKind?: string;  // record: task | event | …
  scope?: string;       // record: personal | engagement name
  fields?: Record<string, string>;
}

export interface ContextBundle {
  user: { id: string; displayName: string };
  persona: { role?: string; tone?: string; outputPrefs?: string; language?: string };
  conventions: { id: string; text: string }[];
  engagementName: string | null;
  workingContext: { activeEngagementId?: string; lastRoute?: string };
  precedence: string[];
}

export type EngagementRole = "owner" | "editor" | "viewer";

export interface EngagementMember {
  userId: string;
  role: EngagementRole;
}

export interface Convention {
  id: string;
  text: string;
  createdBy: string;
  createdAt: string;
}

export interface ActivityEntry {
  ts: string;
  userId: string;
  action: string;
  detail: string;
}

// The v1 delivery record is deliberately slim: a G/Y/R status that always carries a
// why. (Stage, milestones, risks, and actions are parked — docs/mvp-requirements.md R7.)
export type EngagementStatus = "green" | "yellow" | "red";

// Artifact metadata (bytes live in the orchestrator's artifact store; open/download
// always goes through the authed API, never a public URL).
export interface Artifact {
  id: string;
  name: string;
  size: number;
  contentType: string;
  uploadedBy: string;
  uploadedAt: string;
}

export interface Engagement {
  id: string;
  name: string;
  description: string;
  customer: string;
  status: EngagementStatus;
  statusNote: string;
  startDate: string;
  targetDate: string;
  members: EngagementMember[];
  conventions: Convention[];
  tasks: Task[];
  library: Artifact[];
  activity: ActivityEntry[];
  createdAt: string;
  createdBy: string;
}

export interface VisitEntry {
  path: string;
  title: string;
  ts: string;
}

export interface UserContext {
  visits: VisitEntry[];
  workingContext: { activeEngagementId?: string; lastRoute?: string };
}

export interface AppUserRecord {
  id: string;
  username: string;
  displayName: string;
  persona?: { role?: string; tone?: string; outputPrefs?: string; language?: string };
}

export interface QuickLink {
  path: string;
  title: string;
  kind: string;
}

export interface AppState {
  currentRoute: string;
  tasks: Task[];
  events: CalendarEvent[];
  routes: { path: string; title: string; keywords?: string[] }[];
  schedules: Schedule[];
  library: LibraryDoc[];
  // Multi-user additions (served by /app/state in one fetch)
  engagements?: Engagement[];
  user?: AppUserRecord;
  context?: UserContext;
}
