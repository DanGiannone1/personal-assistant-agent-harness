"use client";

// Project screens: list, overview, tasks, calendar, documents, settings.
// Role-aware: mutation controls render only for editor+; member management for owners.
// All mutations go through the typed REST API then onRefresh() re-reads /app/state —
// the pane never renders from its own optimism (same invariant as everywhere else).

import { useState } from "react";
import {
  ArrowLeft, Calendar as CalendarIcon, CheckSquare, Files, FolderKanban,
  Plus, Settings as SettingsIcon, Trash2, Users,
} from "lucide-react";
import type { AppState, Project, ProjectRole, Task } from "@/lib/types";
import {
  addConvention, addProjectMember, createProject, createProjectEvent, createProjectTask,
  deleteProjectEvent, deleteProjectTask, removeConvention, removeProjectMember, updateProjectTask,
} from "@/lib/api";
import { friendlyError } from "@/lib/utils";

const KNOWN_USERS = ["dan", "ava", "sam"];

function roleOf(p: Project, userId: string | undefined): ProjectRole | null {
  const m = p.members.find((m) => m.userId === userId);
  return m ? m.role : null;
}

function canEdit(role: ProjectRole | null): boolean {
  return role === "owner" || role === "editor";
}

function isOverdue(t: Task, today: string): boolean {
  if (t.status === "Done") return false;
  const d = (t.dueDate || "").slice(0, 10);
  return !!d && d < today;
}

function useBusy(onRefresh: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
      await onRefresh();
    } catch (err) {
      setError(friendlyError(err, "Action failed."));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, setError };
}

// ── /projects — the list ─────────────────────────────────────────────────────
export function ProjectsList({ appState, onNavigate, onRefresh }: {
  appState: AppState; onNavigate: (r: string) => void; onRefresh: () => Promise<void>;
}) {
  const projects = appState.projects ?? [];
  const me = appState.user?.id;
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const { busy, error, run } = useBusy(onRefresh);

  return (
    <div className="tw-screen" data-testid="projects-screen">
      <h1 className="tw-h1">Projects</h1>
      <p className="tw-subtle">Shared workspaces — each with its own tasks, calendar, documents, and members.</p>

      {!adding ? (
        <button type="button" className="tw-addbar" data-testid="add-project-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> New project
        </button>
      ) : (
        <div className="tw-addform" data-testid="add-project-form">
          <input autoFocus placeholder="Project name" value={name} data-testid="project-name-input"
            onChange={(e) => setName(e.target.value)}
            style={{ minWidth: 220 }} className="tw-input" />
          <input placeholder="Description (optional)" value={description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ minWidth: 260 }} className="tw-input" />
          <button type="button" className="tw-btn" data-testid="project-save-btn" disabled={busy || !name.trim()}
            onClick={() => run(async () => { await createProject({ name: name.trim(), description: description.trim() }); setAdding(false); setName(""); setDescription(""); })}>
            Create
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      )}
      {error && <p className="tw-error" data-testid="project-error">{error}</p>}

      {projects.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">No projects yet. Create one above, or ask the assistant.</div></section>
      ) : (
        <section className="tw-section">
          <div className="tw-doclist">
            {projects.map((p) => {
              const role = roleOf(p, me);
              return (
                <div key={p.id} className="tw-docitem tw-rowlink" data-testid={`project-row-${p.id}`}
                  role="button" tabIndex={0}
                  onClick={() => onNavigate(`/projects/${p.id}`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNavigate(`/projects/${p.id}`); } }}>
                  <FolderKanban size={16} />
                  <span className="flex min-w-0 flex-col">
                    <span className="tw-td-title">{p.name}</span>
                    <span className="tw-td-sub">{p.description || "—"}</span>
                  </span>
                  <span style={{ marginLeft: "auto" }} className="flex items-center gap-2">
                    <span className="tw-badge tw-badge-gray" data-testid={`project-role-${p.id}`}>{role}</span>
                    <span className="tw-td-sub"><Users size={12} style={{ display: "inline" }} /> {p.members.length}</span>
                    <span className="tw-td-sub"><CheckSquare size={12} style={{ display: "inline" }} /> {p.tasks.length}</span>
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

// ── /projects/{id}(/*) — everything inside one project ──────────────────────
export function ProjectScreen({ appState, viewRoute, onNavigate, onRefresh }: {
  appState: AppState; viewRoute: string; onNavigate: (r: string) => void; onRefresh: () => Promise<void>;
}) {
  const me = appState.user?.id;
  const parts = viewRoute.split("/").filter(Boolean); // ["projects", pid, sub?, recordId?]
  const pid = parts[1];
  const sub = parts[2] ?? "";
  const recordId = parts[3] ?? "";
  const project = (appState.projects ?? []).find((p) => p.id === pid);
  if (!project) return <div className="tw-empty">Project not found (or you are not a member).</div>;
  const role = roleOf(project, me);
  const editable = canEdit(role);
  const base = `/projects/${project.id}`;
  const today = new Date().toISOString().slice(0, 10);

  const tabs = (
    <div className="tw-tabs" data-testid="project-tabs">
      {[["", "Overview"], ["tasks", "Tasks"], ["calendar", "Calendar"], ["documents", "Documents"], ["settings", "Settings"]].map(([key, label]) => (
        <button key={key} type="button"
          className={`tw-tab ${sub === key || (key === "tasks" && sub === "tasks") ? "tw-tab-active" : ""}`}
          data-testid={`project-tab-${key || "overview"}`}
          onClick={() => onNavigate(key ? `${base}/${key}` : base)}>
          {label}
        </button>
      ))}
    </div>
  );

  const header = (
    <>
      <button type="button" className="tw-back" onClick={() => onNavigate("/projects")}><ArrowLeft size={14} /> All projects</button>
      <h1 className="tw-h1">{project.name}</h1>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className="tw-badge tw-badge-gray" data-testid="my-role">{role}</span>
        <span className="tw-subtle">{project.description}</span>
      </div>
      {tabs}
    </>
  );

  if (sub === "tasks" && recordId) {
    const t = project.tasks.find((x) => x.id === recordId);
    if (!t) return <div className="tw-empty">Task not found.</div>;
    return (
      <div className="tw-screen" data-testid="project-task-detail">
        {header}
        <ProjectTaskDetail project={project} task={t} editable={editable} onRefresh={onRefresh} onNavigate={onNavigate} />
      </div>
    );
  }

  if (sub === "tasks") {
    return (
      <div className="tw-screen" data-testid="project-tasks-screen">
        {header}
        <ProjectTasks project={project} editable={editable} today={today} onNavigate={onNavigate} onRefresh={onRefresh} />
      </div>
    );
  }

  if (sub === "calendar") {
    return (
      <div className="tw-screen" data-testid="project-calendar-screen">
        {header}
        <ProjectCalendar project={project} editable={editable} today={today} onRefresh={onRefresh} />
      </div>
    );
  }

  if (sub === "documents") {
    return (
      <div className="tw-screen" data-testid="project-documents-screen">
        {header}
        <section className="tw-section">
          <h2 className="tw-h2">Project documents</h2>
          {project.library.length === 0 ? (
            <div className="tw-empty-sm">No documents saved to this project yet.</div>
          ) : (
            <div className="tw-doclist">
              {project.library.map((d) => (
                <div key={d.id} className="tw-docitem"><Files size={15} /> <span className="tw-td-title">{d.filename}</span></div>
              ))}
            </div>
          )}
        </section>
      </div>
    );
  }

  if (sub === "settings") {
    return (
      <div className="tw-screen" data-testid="project-settings-screen">
        {header}
        <ProjectSettings project={project} myRole={role} onRefresh={onRefresh} />
      </div>
    );
  }

  // Overview
  const overdue = project.tasks.filter((t) => isOverdue(t, today)).length;
  return (
    <div className="tw-screen" data-testid="project-overview">
      {header}
      <div className="tw-stats" style={{ marginTop: 14 }}>
        <StatBox label="Tasks" value={project.tasks.length} />
        <StatBox label="Open" value={project.tasks.filter((t) => t.status !== "Done").length} />
        <StatBox label="Overdue" value={overdue} />
        <StatBox label="Members" value={project.members.length} />
      </div>
      {project.conventions.length > 0 && (
        <section className="tw-section">
          <h2 className="tw-h2">Conventions</h2>
          <div className="tw-doclist">
            {project.conventions.map((c) => (
              <div key={c.id} className="tw-docitem" data-testid={`convention-${c.id}`}>
                <SettingsIcon size={14} /> <span className="tw-td-sub">{c.text}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="tw-section">
        <h2 className="tw-h2">Recent activity</h2>
        {project.activity.length === 0 ? (
          <div className="tw-empty-sm">No activity yet.</div>
        ) : (
          <div className="tw-doclist" data-testid="activity-feed">
            {project.activity.slice(0, 8).map((a, i) => (
              <div key={i} className="tw-docitem">
                <span className="tw-td-sub" style={{ minWidth: 70 }}>{a.userId}</span>
                <span className="tw-td-sub">{a.action}</span>
                <span className="tw-td-title" style={{ fontSize: 13 }}>{a.detail}</span>
                <span className="tw-td-sub" style={{ marginLeft: "auto" }}>{a.ts.slice(5, 16).replace("T", " ")}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="tw-stat">
      <div className="tw-stat-value">{value}</div>
      <div className="tw-stat-label">{label}</div>
    </div>
  );
}

function ProjectTasks({ project, editable, today, onNavigate, onRefresh }: {
  project: Project; editable: boolean; today: string;
  onNavigate: (r: string) => void; onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const base = `/projects/${project.id}`;

  return (
    <>
      {editable && (!adding ? (
        <button type="button" className="tw-addbar" data-testid="project-add-task-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add task
        </button>
      ) : (
        <div className="tw-addform" data-testid="project-add-task-form">
          <input autoFocus placeholder="Task title" value={title} data-testid="project-task-title-input"
            onChange={(e) => setTitle(e.target.value)} className="tw-input" style={{ minWidth: 240 }} />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="tw-input" />
          <button type="button" className="tw-btn" data-testid="project-task-save-btn" disabled={busy || !title.trim()}
            onClick={() => run(async () => { await createProjectTask(project.id, { title: title.trim(), dueDate: due }); setAdding(false); setTitle(""); setDue(""); })}>
            Save
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ))}
      {!editable && <p className="tw-subtle" data-testid="viewer-note">You have view-only access to this project.</p>}
      {error && <p className="tw-error">{error}</p>}

      {project.tasks.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">No tasks in this project yet.</div></section>
      ) : (
        <section className="tw-section">
          <table className="tw-table" data-testid="project-tasks-table">
            <thead><tr><th>Task</th><th>Status</th><th>Priority</th><th>Due</th>{editable && <th></th>}</tr></thead>
            <tbody>
              {project.tasks.map((t) => {
                const od = isOverdue(t, today);
                return (
                  <tr key={t.id} className="tw-rowlink" data-testid={`project-task-row-${t.id}`}
                    onClick={() => onNavigate(`${base}/tasks/${t.id}`)}>
                    <td className="tw-td-title">{t.title}</td>
                    <td><span className={`tw-badge ${t.status === "Done" ? "tw-badge-green" : t.status === "In progress" ? "tw-badge-orange" : t.status === "Blocked" ? "tw-badge-red" : "tw-badge-gray"}`}>{t.status}</span></td>
                    <td>{t.priority}</td>
                    <td className={od ? "tw-due-overdue" : ""}>{t.dueDate || "—"}{od ? " · overdue" : ""}</td>
                    {editable && (
                      <td onClick={(e) => e.stopPropagation()}>
                        <ArmedDelete testid={`project-task-delete-${t.id}`}
                          onConfirm={() => run(() => deleteProjectTask(project.id, t.id))} />
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}

function ProjectTaskDetail({ project, task, editable, onRefresh, onNavigate }: {
  project: Project; task: Task; editable: boolean;
  onRefresh: () => Promise<void>; onNavigate: (r: string) => void;
}) {
  const { busy, error, run } = useBusy(onRefresh);
  const base = `/projects/${project.id}`;
  return (
    <section className="tw-section" data-testid="project-task-editor">
      <button type="button" className="tw-back" onClick={() => onNavigate(`${base}/tasks`)}><ArrowLeft size={14} /> All tasks</button>
      <h2 className="tw-h2" style={{ marginTop: 8 }}>{task.title}</h2>
      <div className="tw-stats">
        <StatBox label="Status" value={task.status} />
        <StatBox label="Priority" value={task.priority} />
        <StatBox label="Due" value={task.dueDate || "—"} />
      </div>
      {editable ? (
        <div className="tw-addform" style={{ marginTop: 12 }}>
          <select className="tw-input" value={task.status} data-testid="project-task-status" disabled={busy}
            onChange={(e) => run(() => updateProjectTask(project.id, task.id, { status: e.target.value }))}>
            {["To do", "In progress", "Blocked", "Done"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className="tw-input" value={task.priority} data-testid="project-task-priority" disabled={busy}
            onChange={(e) => run(() => updateProjectTask(project.id, task.id, { priority: e.target.value }))}>
            {["Low", "Medium", "High"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <input type="date" className="tw-input" value={(task.dueDate || "").slice(0, 10)} disabled={busy}
            onChange={(e) => run(() => updateProjectTask(project.id, task.id, { dueDate: e.target.value }))} />
        </div>
      ) : (
        <p className="tw-subtle" data-testid="viewer-note">View-only: your role on this project is viewer.</p>
      )}
      {error && <p className="tw-error">{error}</p>}
    </section>
  );
}

function ProjectCalendar({ project, editable, today, onRefresh }: {
  project: Project; editable: boolean; today: string; onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const events = [...project.events].sort((a, b) => ((a.date || "") < (b.date || "") ? -1 : 1));

  return (
    <>
      {editable && (!adding ? (
        <button type="button" className="tw-addbar" data-testid="project-add-event-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add event
        </button>
      ) : (
        <div className="tw-addform">
          <input autoFocus placeholder="Event title" value={title} data-testid="project-event-title-input"
            onChange={(e) => setTitle(e.target.value)} className="tw-input" style={{ minWidth: 220 }} />
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="tw-input" data-testid="project-event-date-input" />
          <button type="button" className="tw-btn" data-testid="project-event-save-btn" disabled={busy || !title.trim() || !date}
            onClick={() => run(async () => { await createProjectEvent(project.id, { title: title.trim(), date }); setAdding(false); setTitle(""); setDate(""); })}>
            Save
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ))}
      {error && <p className="tw-error">{error}</p>}
      {events.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">Nothing scheduled in this project yet.</div></section>
      ) : (
        <section className="tw-section">
          <div className="tw-doclist">
            {events.map((e) => (
              <div key={e.id} className="tw-docitem" data-testid={`project-event-${e.id}`}>
                <CalendarIcon size={15} />
                <span className="flex min-w-0 flex-col">
                  <span className="tw-td-title">{e.title}</span>
                  <span className="tw-td-sub">{e.date}{e.start ? ` · ${e.start}${e.end ? `–${e.end}` : ""}` : ""} · {e.type || "Meeting"}{e.date === today ? " · today" : ""}</span>
                </span>
                {editable && (
                  <span style={{ marginLeft: "auto" }}>
                    <ArmedDelete testid={`project-event-delete-${e.id}`} onConfirm={() => run(() => deleteProjectEvent(project.id, e.id))} />
                  </span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function ProjectSettings({ project, myRole, onRefresh }: {
  project: Project; myRole: ProjectRole | null; onRefresh: () => Promise<void>;
}) {
  const isOwner = myRole === "owner";
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<ProjectRole>("viewer");
  const [convText, setConvText] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const candidates = KNOWN_USERS.filter((u) => !project.members.some((m) => m.userId === u));

  return (
    <>
      <section className="tw-section">
        <h2 className="tw-h2"><Users size={14} /> Members</h2>
        <div className="tw-doclist" data-testid="member-list">
          {project.members.map((m) => (
            <div key={m.userId} className="tw-docitem" data-testid={`member-${m.userId}`}>
              <span className="tw-td-title">{m.userId}</span>
              <span className="tw-badge tw-badge-gray">{m.role}</span>
              {isOwner && m.role !== "owner" && (
                <span style={{ marginLeft: "auto" }}>
                  <ArmedDelete testid={`member-remove-${m.userId}`} onConfirm={() => run(() => removeProjectMember(project.id, m.userId))} />
                </span>
              )}
            </div>
          ))}
        </div>
        {isOwner && (
          <div className="tw-addform" style={{ marginTop: 10 }} data-testid="add-member-form">
            <select className="tw-input" value={userId} onChange={(e) => setUserId(e.target.value)} data-testid="member-user-select">
              <option value="">Add member…</option>
              {candidates.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
            <select className="tw-input" value={role} onChange={(e) => setRole(e.target.value as ProjectRole)} data-testid="member-role-select">
              {(["viewer", "editor", "owner"] as const).map((r) => <option key={r}>{r}</option>)}
            </select>
            <button type="button" className="tw-btn" data-testid="member-add-btn" disabled={busy || !userId}
              onClick={() => run(async () => { await addProjectMember(project.id, userId, role); setUserId(""); })}>
              Add
            </button>
          </div>
        )}
      </section>

      <section className="tw-section">
        <h2 className="tw-h2"><SettingsIcon size={14} /> Conventions</h2>
        <p className="tw-subtle">Working agreements the assistant applies when it works in this project.</p>
        <div className="tw-doclist">
          {project.conventions.map((c) => (
            <div key={c.id} className="tw-docitem" data-testid={`convention-row-${c.id}`}>
              <span className="tw-td-sub">{c.text}</span>
              {canEdit(myRole) && (
                <span style={{ marginLeft: "auto" }}>
                  <ArmedDelete testid={`convention-delete-${c.id}`} onConfirm={() => run(() => removeConvention(project.id, c.id))} />
                </span>
              )}
            </div>
          ))}
        </div>
        {canEdit(myRole) && (
          <div className="tw-addform" style={{ marginTop: 10 }}>
            <input className="tw-input" placeholder="e.g. Status docs are written in French" value={convText}
              data-testid="convention-input" onChange={(e) => setConvText(e.target.value)} style={{ minWidth: 300 }} />
            <button type="button" className="tw-btn" data-testid="convention-add-btn" disabled={busy || !convText.trim()}
              onClick={() => run(async () => { await addConvention(project.id, convText.trim()); setConvText(""); })}>
              Add
            </button>
          </div>
        )}
      </section>
      {error && <p className="tw-error" data-testid="settings-error">{error}</p>}
    </>
  );
}

// Two-click delete (armed pattern shared with the personal screens).
function ArmedDelete({ onConfirm, testid }: { onConfirm: () => void; testid: string }) {
  const [armed, setArmed] = useState(false);
  if (!armed) {
    return (
      <button type="button" className="tw-btn-ghost" data-testid={testid} title="Delete"
        onClick={(e) => { e.stopPropagation(); setArmed(true); }}>
        <Trash2 size={13} />
      </button>
    );
  }
  return (
    <button type="button" className="tw-btn" data-testid={`${testid}-confirm`}
      onClick={(e) => { e.stopPropagation(); setArmed(false); onConfirm(); }}>
      Confirm
    </button>
  );
}
