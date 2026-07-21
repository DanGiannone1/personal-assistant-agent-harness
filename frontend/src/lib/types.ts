export type AGUIEvent =
  | { type: "RUN_STARTED"; thread_id: string; run_id: string }
  | { type: "TEXT_MESSAGE_START"; message_id: string; role: string }
  | { type: "TEXT_MESSAGE_CONTENT"; message_id: string; delta: string }
  | { type: "TEXT_MESSAGE_END"; message_id: string }
  | { type: "TOOL_CALL_START"; tool_call_id: string; tool_call_name: string; parent_message_id?: string }
  | { type: "TOOL_CALL_ARGS"; tool_call_id: string; delta: string }
  | { type: "TOOL_CALL_RESULT"; tool_call_id: string; result: ProductToolResult }
  | { type: "TOOL_CALL_END"; tool_call_id: string }
  | { type: "NAVIGATION_RESOLVED"; runId: string; destination: Destination; requestedAtNavigationVersion: number }
  | { type: "RUN_FINISHED"; thread_id: string; run_id: string }
  | { type: "RUN_ERROR"; message: string }
  | { type: "REASONING_START" }
  | { type: "REASONING_DELTA"; delta: string }
  | { type: "REASONING_END" };

export type ProductToolStatus = "committed" | "resolved" | "succeeded" | "noop" | "needs_confirmation" | "ambiguous" | "invalid" | "not_found" | "forbidden" | "conflict" | "failed";

export interface Destination {
  id: "engagements" | "engagement_overview" | "engagement_tasks" | "engagement_artifacts";
  path: string;
  label?: string;
  engagementId?: string;
}

export interface ProductToolResult {
  status: ProductToolStatus;
  code: string;
  operation: string;
  message?: string;
  resource?: Record<string, unknown>;
  destination?: Destination;
}

export type MessagePart =
  | { type: "text"; content: string }
  | { type: "reasoning"; content: string }
  | { type: "tool_call"; tool: string; toolCallId: string; status: "running" | "done"; args?: string; result?: ProductToolResult };

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

// ── CSA Workbench application state ─────────────────────────────────────────
// Tasks are nested inside Engagements; there is no personal task surface.
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

// The MVP delivery record is deliberately slim: a G/Y/R status that always carries
// a reason. Stage, milestones, risks, and actions are parked.
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

export interface AppUserRecord {
  id: string;
  username: string;
  displayName: string;
  persona?: { role?: string; tone?: string; outputPrefs?: string; language?: string };
}

export interface AppState {
  currentRoute: string;
  engagements: Engagement[];
  user: AppUserRecord;
}
