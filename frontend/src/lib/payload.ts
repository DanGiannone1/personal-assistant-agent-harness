import type { AppState, ContextBundle, Engagement, FileInfo } from "./types";

type ObjectValue = Record<string, unknown>;

function object(value: unknown, label: string): ObjectValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`Malformed ${label} payload`);
  return value as ObjectValue;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`Malformed ${label} payload`);
  return value;
}

function optionalString(value: unknown, label: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  return string(value, label);
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`Malformed ${label} payload`);
  return value;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`Malformed ${label} payload`);
  return value;
}

function decodeFile(value: unknown): FileInfo {
  const file = object(value, "file");
  const origin = file.origin;
  if (origin !== undefined && origin !== "uploaded" && origin !== "generated") throw new Error("Malformed file payload");
  if (typeof file.size !== "number" || !Number.isFinite(file.size) || file.size < 0) throw new Error("Malformed file payload");
  if (typeof file.has_markdown !== "boolean") throw new Error("Malformed file payload");
  return {
    filename: string(file.filename, "file.filename"),
    size: file.size,
    modified_at: string(file.modified_at, "file.modified_at"),
    has_markdown: file.has_markdown,
    ...(origin ? { origin } : {}),
  };
}

export function decodeSessionMetadata(value: unknown): { session_id: string; status: string; files?: FileInfo[] } {
  const session = object(value, "session");
  const files = session.files === undefined ? undefined : array(session.files, "session.files").map(decodeFile);
  return { session_id: string(session.session_id, "session_id"), status: string(session.status, "status"), ...(files ? { files } : {}) };
}

export function decodeFilesPayload(value: unknown): { files: FileInfo[] } {
  const response = object(value, "files");
  return { files: array(response.files, "files").map(decodeFile) };
}

export function decodeFileContent(value: unknown): { filename: string; size: number; mime_type: string; content: string } {
  const response = object(value, "file content");
  if (typeof response.size !== "number" || !Number.isFinite(response.size) || response.size < 0) throw new Error("Malformed file content payload");
  return {
    filename: string(response.filename, "file content.filename"),
    size: response.size,
    mime_type: string(response.mime_type, "file content.mime_type"),
    content: string(response.content, "file content.content"),
  };
}

export function decodeSessionUpload(value: unknown): { path: string; filename: string; size: number; markdown_ready: boolean } {
  const upload = object(value, "session upload");
  if (typeof upload.size !== "number" || !Number.isFinite(upload.size) || upload.size < 0 || typeof upload.markdown_ready !== "boolean") throw new Error("Malformed session upload payload");
  return { path: string(upload.path, "session upload.path"), filename: string(upload.filename, "session upload.filename"), size: upload.size, markdown_ready: upload.markdown_ready };
}

export function decodeFileWrite(value: unknown): { filename: string; size: number } {
  const write = object(value, "file write");
  if (typeof write.size !== "number" || !Number.isFinite(write.size) || write.size < 0) throw new Error("Malformed file write payload");
  return { filename: string(write.filename, "file write.filename"), size: write.size };
}

export function decodeContextBundle(value: unknown): ContextBundle {
  const bundle = object(value, "context bundle");
  const user = object(bundle.user, "context user");
  const persona = object(bundle.persona, "context persona");
  const workingContext = object(bundle.workingContext, "working context");
  return {
    user: { id: string(user.id, "context user.id"), displayName: string(user.displayName, "context user.displayName") },
    persona: {
      ...(optionalString(persona.role, "persona.role") ? { role: optionalString(persona.role, "persona.role") } : {}),
      ...(optionalString(persona.tone, "persona.tone") ? { tone: optionalString(persona.tone, "persona.tone") } : {}),
      ...(optionalString(persona.outputPrefs, "persona.outputPrefs") ? { outputPrefs: optionalString(persona.outputPrefs, "persona.outputPrefs") } : {}),
      ...(optionalString(persona.language, "persona.language") ? { language: optionalString(persona.language, "persona.language") } : {}),
    },
    conventions: array(bundle.conventions, "context conventions").map((entry) => {
      const convention = object(entry, "context convention");
      return { id: string(convention.id, "context convention.id"), text: string(convention.text, "context convention.text") };
    }),
    engagementName: bundle.engagementName === null ? null : string(bundle.engagementName, "engagementName"),
    workingContext: {
      ...(optionalString(workingContext.activeEngagementId, "activeEngagementId") ? { activeEngagementId: optionalString(workingContext.activeEngagementId, "activeEngagementId") } : {}),
      ...(optionalString(workingContext.lastRoute, "lastRoute") ? { lastRoute: optionalString(workingContext.lastRoute, "lastRoute") } : {}),
    },
    precedence: array(bundle.precedence, "context precedence").map((entry) => string(entry, "context precedence entry")),
  };
}

function decodeEngagement(value: unknown): Engagement {
  const engagement = object(value, "engagement");
  const status = string(engagement.status, "engagement.status");
  if (status !== "green" && status !== "yellow" && status !== "red") throw new Error("Malformed engagement payload");
  const members = array(engagement.members, "engagement.members").map((entry) => {
    const member = object(entry, "engagement.member");
    const role = string(member.role, "engagement.member.role");
    if (role !== "owner" && role !== "editor" && role !== "viewer") throw new Error("Malformed engagement member payload");
    return { userId: string(member.userId, "engagement.member.userId"), role };
  });
  const conventions = array(engagement.conventions, "engagement.conventions").map((entry) => {
    const convention = object(entry, "engagement.convention");
    return { id: string(convention.id, "engagement.convention.id"), text: text(convention.text, "engagement.convention.text"), createdBy: string(convention.createdBy, "engagement.convention.createdBy"), createdAt: string(convention.createdAt, "engagement.convention.createdAt") };
  });
  const tasks = array(engagement.tasks, "engagement.tasks").map((entry) => {
    const task = object(entry, "engagement.task");
    const statusValue = string(task.status, "engagement.task.status");
    const priority = string(task.priority, "engagement.task.priority");
    if (!["To do", "In progress", "Blocked", "Done"].includes(statusValue) || !["Low", "Medium", "High"].includes(priority)) throw new Error("Malformed engagement task payload");
    const subtasks = task.subtasks === undefined ? undefined : array(task.subtasks, "engagement.task.subtasks").map((item) => {
      const subtask = object(item, "engagement.subtask");
      if (typeof subtask.done !== "boolean") throw new Error("Malformed engagement subtask payload");
      return { text: text(subtask.text, "engagement.subtask.text"), done: subtask.done };
    });
    return { id: string(task.id, "engagement.task.id"), title: text(task.title, "engagement.task.title"), status: statusValue, priority, group: text(task.group, "engagement.task.group"), ...(task.dueDate === undefined ? {} : { dueDate: text(task.dueDate, "engagement.task.dueDate") }), ...(subtasks ? { subtasks } : {}), ...(task.notes === undefined ? {} : { notes: text(task.notes, "engagement.task.notes") }), ...(task.createdAt === undefined ? {} : { createdAt: text(task.createdAt, "engagement.task.createdAt") }) };
  });
  const library = array(engagement.library, "engagement.library").map((entry) => {
    const artifact = object(entry, "engagement.artifact");
    if (typeof artifact.size !== "number" || !Number.isFinite(artifact.size) || artifact.size < 0) throw new Error("Malformed engagement artifact payload");
    return { id: string(artifact.id, "engagement.artifact.id"), name: string(artifact.name, "engagement.artifact.name"), size: artifact.size, contentType: text(artifact.contentType, "engagement.artifact.contentType"), uploadedBy: string(artifact.uploadedBy, "engagement.artifact.uploadedBy"), uploadedAt: string(artifact.uploadedAt, "engagement.artifact.uploadedAt") };
  });
  const activity = array(engagement.activity, "engagement.activity").map((entry) => {
    const item = object(entry, "engagement.activity entry");
    return { ts: string(item.ts, "engagement.activity.ts"), userId: string(item.userId, "engagement.activity.userId"), action: string(item.action, "engagement.activity.action"), detail: text(item.detail, "engagement.activity.detail") };
  });
  return {
    id: string(engagement.id, "engagement.id"), name: string(engagement.name, "engagement.name"), description: text(engagement.description, "engagement.description"), customer: text(engagement.customer, "engagement.customer"), status,
    statusNote: text(engagement.statusNote, "engagement.statusNote"), startDate: text(engagement.startDate, "engagement.startDate"), targetDate: text(engagement.targetDate, "engagement.targetDate"),
    members: members as Engagement["members"], conventions: conventions as Engagement["conventions"], tasks: tasks as Engagement["tasks"], library: library as Engagement["library"], activity: activity as Engagement["activity"], createdAt: string(engagement.createdAt, "engagement.createdAt"), createdBy: string(engagement.createdBy, "engagement.createdBy"),
  };
}

export { decodeEngagement };
export function decodeEngagementList(value: unknown): Engagement[] { return array(value, "engagement list").map(decodeEngagement); }

// The UI needs a complete Engagement record before it can render or authorize a route from it.
export function decodeAppState(value: unknown): AppState {
  const state = object(value, "application state");
  const engagements = decodeEngagementList(state.engagements);
  const user = object(state.user, "application user");
  const persona = user.persona === undefined ? undefined : object(user.persona, "user.persona");
  return {
    currentRoute: string(state.currentRoute, "currentRoute"),
    engagements,
    user: {
      id: string(user.id, "user.id"), username: string(user.username, "user.username"), displayName: string(user.displayName, "user.displayName"),
      ...(persona ? {
        persona: {
          ...(optionalString(persona.role, "user.persona.role") ? { role: optionalString(persona.role, "user.persona.role") } : {}),
          ...(optionalString(persona.tone, "user.persona.tone") ? { tone: optionalString(persona.tone, "user.persona.tone") } : {}),
          ...(optionalString(persona.outputPrefs, "user.persona.outputPrefs") ? { outputPrefs: optionalString(persona.outputPrefs, "user.persona.outputPrefs") } : {}),
          ...(optionalString(persona.language, "user.persona.language") ? { language: optionalString(persona.language, "user.persona.language") } : {}),
        },
      } : {}),
    },
  };
}
