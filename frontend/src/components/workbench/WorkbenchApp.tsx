"use client";

import { useEffect, useRef, useState } from "react";
import {
  FileText, CheckCircle2, Circle, ArrowLeft, Home as HomeIcon, AlertTriangle, Calendar as CalendarIcon, Clock,
  BookMarked, Trash2, Upload, Plus,
} from "lucide-react";
import type { AppFile, AppState, Task, Schedule, LibraryDoc, Engagement } from "@/lib/types";
import { getFileContent, getLibraryContent,
  createTask, updateTask, deleteTask, addSubtask, toggleSubtask, deleteSubtask,
  createEvent, deleteEvent, createSchedule, updateSchedule, deleteSchedule,
  createEngagement, updateEngagement, deleteEngagement, addEngagementItem, updateEngagementItem, deleteEngagementItem } from "@/lib/api";
import { friendlyError } from "@/lib/utils";
import MarkdownRenderer from "../MarkdownRenderer";
import CsvTable from "../CsvTable";
import WorkbenchNav from "./WorkbenchNav";

interface WorkbenchAppProps {
  appState: AppState | null;
  loading: boolean;
  viewRoute: string;
  onNavigate: (route: string) => void;
  sessionId: string | null;
  uploadedFiles: AppFile[];
  generatedFiles: AppFile[];
  newRecordIds: string[];
  agentWorking: boolean;
  onSaveToLibrary: (filename: string) => Promise<void>;
  onRemoveFromLibrary: (filename: string) => Promise<void>;
  onUpload: (file: File) => Promise<void>;
  onRefresh: () => Promise<void>;
}

// A task is overdue iff its due date is past today and it isn't Done — computed
// client-side from the real date (mirrors appdb.is_overdue) so the pane never shows a stale flag.
function isOverdue(t: Task, today: string): boolean {
  if (t.status === "Done") return false;
  const d = (t.dueDate || "").slice(0, 10);
  return !!d && d < today;
}

function statusClass(status: string): string {
  switch (status) {
    case "Done": return "tw-badge-green";
    case "In progress": return "tw-badge-orange";
    case "Blocked": return "tw-badge-red";
    default: return "tw-badge-gray"; // To do
  }
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`tw-badge ${statusClass(status)}`}>{status}</span>;
}

function PriorityBadge({ priority }: { priority: string }) {
  const cls = priority === "High" ? "cell-pill-high" : priority === "Medium" ? "cell-pill-med" : "cell-pill-low";
  return <span className={`cell-pill ${cls}`}>{priority}</span>;
}

function OverdueBadge() {
  return <span className="tw-badge tw-badge-red"><AlertTriangle size={11} strokeWidth={2.5} />Overdue</span>;
}

function healthClass(health: string): string {
  switch (health) {
    case "green": return "tw-badge-green";
    case "amber": return "tw-badge-orange";
    case "red": return "tw-badge-red";
    default: return "tw-badge-gray";
  }
}

function HealthBadge({ health }: { health: string }) {
  const label = health === "green" ? "Green" : health === "amber" ? "Amber" : health === "red" ? "Red" : health;
  return <span className={`tw-badge ${healthClass(health)}`}>{label}</span>;
}

// Engagement sub-item statuses reuse the task badge palette: done-ish → green,
// in-flight → orange, slipped → red, not-started → gray.
function engStatusClass(status: string): string {
  switch (status) {
    case "Done": case "Closed": case "Live": return "tw-badge-green";
    case "In progress": case "Mitigating": return "tw-badge-orange";
    case "Slipped": return "tw-badge-red";
    default: return "tw-badge-gray"; // Planned / Open
  }
}

function EngStatusBadge({ status }: { status: string }) {
  return <span className={`tw-badge ${engStatusClass(status)}`}>{status}</span>;
}

export default function WorkbenchApp({
  appState, loading, viewRoute, onNavigate, sessionId, uploadedFiles, generatedFiles, newRecordIds, agentWorking,
  onSaveToLibrary, onRemoveFromLibrary, onUpload, onRefresh,
}: WorkbenchAppProps) {
  const [doc, setDoc] = useState<{ filename: string; content: string; mime?: string; loading: boolean; error: string | null } | null>(null);
  const [pulse, setPulse] = useState(false);
  const prevRoute = useRef(viewRoute);

  // Briefly pulse the app header when the view changes (e.g. agent navigation) so
  // it's obvious the pane moved. Both flips run from timers (never synchronously in
  // the effect body) so the effect only schedules work.
  useEffect(() => {
    if (prevRoute.current === viewRoute) return;
    prevRoute.current = viewRoute;
    const start = setTimeout(() => setPulse(true), 0);
    const end = setTimeout(() => setPulse(false), 1100);
    return () => { clearTimeout(start); clearTimeout(end); };
  }, [viewRoute]);

  // Leaving the Documents view closes any open document so returning shows the
  // list, not a stale previously-opened doc. Deferred to a timer (the render guard
  // below already hides the doc off-route, so nothing stale can flash meanwhile).
  useEffect(() => {
    if (viewRoute === "/documents") return;
    const id = setTimeout(() => setDoc(null), 0);
    return () => clearTimeout(id);
  }, [viewRoute]);

  const openDoc = async (filename: string, fromLibrary = false) => {
    if (!sessionId) return;
    setDoc({ filename, content: "", mime: undefined, loading: true, error: null });
    try {
      const data = fromLibrary
        ? await getLibraryContent(sessionId, filename)
        : await getFileContent(sessionId, filename);
      setDoc({ filename, content: data.content, mime: data.mime_type, loading: false, error: null });
    } catch (err) {
      setDoc({ filename, content: "", mime: undefined, loading: false, error: friendlyError(err, "Could not open document.") });
    }
  };

  return (
    <div className="tw-app" data-testid="workbench-app">
      {/* Workspace-scoped a11y/polish overrides (kept here, not in the contended globals.css):
          darker muted text for AA contrast, a visible keyboard focus ring, and minor layout fixes.
          Scoped to .tw-app so the co-pilot dock keeps its own styling. */}
      <style>{`
        .tw-app { --text-muted: #6b6e7b; --color-text-muted: #6b6e7b; }
        .tw-app .tw-stat-label { min-height: 0; }
        .tw-app .tw-breadcrumb { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .tw-app :focus-visible { outline: 2px solid var(--brand-primary, #0073ea); outline-offset: 2px; border-radius: 6px; }
        .tw-app .tw-rowlink:focus-visible { outline-offset: -2px; }
      `}</style>
      {/* App header */}
      <div className={`tw-appbar ${pulse ? "tw-appbar-pulse" : ""}`}>
        <div className="tw-appbar-brand">
          <div className="tw-logo"><HomeIcon size={16} strokeWidth={2.5} /></div>
          <div className="flex flex-col leading-tight">
            <span className="tw-appbar-title">Personal Assistant</span>
            <span className="tw-appbar-sub">{agentWorking ? "Assistant working…" : "Ready"}</span>
          </div>
        </div>
        <Breadcrumb appState={appState} viewRoute={viewRoute} />
      </div>

      <div className="tw-body">
        <WorkbenchNav appState={appState} viewRoute={viewRoute} onNavigate={onNavigate} />

        {/* Content */}
        <div className="tw-content" data-testid="workbench-content">
          {loading && !appState ? (
            <div className="tw-empty">Loading workspace…</div>
          ) : doc && viewRoute === "/documents" ? (
            <DocViewer doc={doc} onBack={() => setDoc(null)} />
          ) : (
            <RouteContent
              appState={appState}
              viewRoute={viewRoute}
              onNavigate={onNavigate}
              uploadedFiles={uploadedFiles}
              generatedFiles={generatedFiles}
              newRecordIds={newRecordIds}
              onOpenDoc={openDoc}
              onSaveToLibrary={onSaveToLibrary}
              onRemoveFromLibrary={onRemoveFromLibrary}
              onUpload={onUpload}
              sessionId={sessionId}
              onRefresh={onRefresh}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function Breadcrumb({ appState, viewRoute }: { appState: AppState | null; viewRoute: string }) {
  if (!appState) return null;
  let trail = "Home";
  if (viewRoute.startsWith("/todo/")) {
    const t = appState.tasks.find((x) => x.id === viewRoute.split("/").pop());
    trail = `Tasks › ${t?.title ?? ""}`;
  } else if (viewRoute === "/todo") trail = "Tasks";
  else if (viewRoute.startsWith("/engagements/")) {
    const e = (appState.engagements ?? []).find((x) => x.id === viewRoute.split("/").pop());
    trail = `Engagements › ${e?.title ?? ""}`;
  } else if (viewRoute === "/engagements") trail = "Engagements";
  else if (viewRoute === "/calendar") trail = "Calendar";
  else if (viewRoute === "/documents") trail = "Documents";
  else if (viewRoute === "/reminders") trail = "Reminders";
  return <div className="tw-breadcrumb" data-testid="breadcrumb">{trail}</div>;
}

function RouteContent({ appState, viewRoute, onNavigate, uploadedFiles, generatedFiles, newRecordIds, onOpenDoc, onSaveToLibrary, onRemoveFromLibrary, onUpload, sessionId, onRefresh }: {
  appState: AppState | null; viewRoute: string; onNavigate: (r: string) => void;
  uploadedFiles: AppFile[]; generatedFiles: AppFile[]; newRecordIds: string[];
  onOpenDoc: (f: string, fromLibrary?: boolean) => void;
  onSaveToLibrary: (f: string) => Promise<void>; onRemoveFromLibrary: (f: string) => Promise<void>;
  onUpload: (file: File) => Promise<void>;
  sessionId: string | null; onRefresh: () => Promise<void>;
}) {
  if (!appState) return <div className="tw-empty">No data.</div>;
  const isNew = (id: string) => newRecordIds.includes(id);
  const today = new Date().toISOString().slice(0, 10);
  const tasks = appState.tasks ?? [];
  const events = appState.events ?? [];
  const schedules = appState.schedules ?? [];
  const engagements = appState.engagements ?? [];

  // ── Engagement detail (/engagements/{id}) ─────────────────────────────────
  if (viewRoute.startsWith("/engagements/")) {
    const e = engagements.find((x) => x.id === viewRoute.split("/").pop());
    if (!e) {
      return (
        <div className="tw-screen" data-testid="engagement-detail">
          <button type="button" className="tw-back" onClick={() => onNavigate("/engagements")}><ArrowLeft size={14} /> All engagements</button>
          <div className="tw-empty">Engagement not found.</div>
        </div>
      );
    }
    const milestones = e.milestones ?? [];
    const risks = e.risks ?? [];
    const actions = e.actions ?? [];
    const msDone = milestones.filter((m) => m.status === "Done").length;
    return (
      <div className="tw-screen" data-testid="engagement-detail">
        <button type="button" className="tw-back" onClick={() => onNavigate("/engagements")}><ArrowLeft size={14} /> All engagements</button>
        <h1 className="tw-h1">{e.title}</h1>
        <div className="flex flex-wrap items-center gap-2 mt-1">
          <HealthBadge health={e.health} />
          <span className="tw-badge tw-badge-gray">{e.stage}</span>
          {e.healthNote && <span className="tw-td-sub" style={{ marginTop: 0 }}>{e.healthNote}</span>}
        </div>

        <div className="tw-stats" style={{ marginTop: 18 }}>
          <Stat label="Customer" value={e.customer || "—"} />
          <Stat label="Milestones done" value={`${msDone}/${milestones.length}`} />
          <Stat label="Open risks" value={risks.filter((r) => r.status !== "Closed").length} />
          <Stat label="Open actions" value={actions.filter((a) => a.status !== "Done").length} />
        </div>

        <EngagementDetailEditor engagement={e} sessionId={sessionId} onRefresh={onRefresh} onNavigate={onNavigate} />
        <MilestoneSection engagement={e} sessionId={sessionId} onRefresh={onRefresh} today={today} />
        <RiskSection engagement={e} sessionId={sessionId} onRefresh={onRefresh} />
        <ActionSection engagement={e} sessionId={sessionId} onRefresh={onRefresh} today={today} />
      </div>
    );
  }

  // ── Engagements (/engagements) — customer delivery portfolio ──────────────
  if (viewRoute === "/engagements") {
    const openRisks = engagements.reduce((n, e) => n + (e.risks ?? []).filter((r) => r.status !== "Closed").length, 0);
    return (
      <div className="tw-screen" data-testid="engagements-screen">
        <h1 className="tw-h1">Engagements</h1>
        <p className="tw-subtle">Customer engagements — stage, health, and delivery risk.</p>
        <div className="tw-stats">
          <Stat label="Engagements" value={engagements.length} />
          <Stat label="Red" value={engagements.filter((e) => e.health === "red").length} />
          <Stat label="Amber" value={engagements.filter((e) => e.health === "amber").length} />
          <Stat label="Open risks" value={openRisks} />
        </div>
        <AddEngagementBar sessionId={sessionId} onRefresh={onRefresh} />
        {engagements.length === 0 ? (
          <section className="tw-section"><div className="tw-empty-sm">No engagements yet. Add one above, or ask the assistant.</div></section>
        ) : (
          <section className="tw-section">
            <table className="tw-table" data-testid="engagements-table">
              <thead><tr><th>Engagement</th><th>Customer</th><th>Stage</th><th>Health</th><th>Milestones</th><th>Risks</th><th>Actions</th><th>Target</th><th></th></tr></thead>
              <tbody>
                {engagements.map((e) => {
                  const milestones = e.milestones ?? [];
                  const msDone = milestones.filter((m) => m.status === "Done").length;
                  const note = e.healthNote || "";
                  return (
                    <tr key={e.id} data-testid={`engagement-row-${e.id}`} className={`tw-rowlink ${isNew(e.id) ? "tw-row-new" : ""}`} onClick={() => onNavigate(`/engagements/${e.id}`)}>
                      <td className="tw-td-title"><button type="button" style={rowTitleBtn} onClick={(ev) => { ev.stopPropagation(); onNavigate(`/engagements/${e.id}`); }}>{e.title}</button>{isNew(e.id) && <span className="tw-new">New</span>}</td>
                      <td>{e.customer || "—"}</td>
                      <td>{e.stage}</td>
                      <td><HealthBadge health={e.health} />{note && <span className="tw-td-sub">{note.length > 48 ? `${note.slice(0, 48)}…` : note}</span>}</td>
                      <td className="tw-td-mono">{msDone}/{milestones.length}</td>
                      <td className="tw-td-mono">{(e.risks ?? []).filter((r) => r.status !== "Closed").length}</td>
                      <td className="tw-td-mono">{(e.actions ?? []).filter((a) => a.status !== "Done").length}</td>
                      <td>{e.targetDate ? dayLabel(e.targetDate.slice(0, 10), today) : "—"}</td>
                      <td onClick={(ev) => ev.stopPropagation()}><RowDelete onDelete={() => deleteEngagement(sessionId!, e.id)} onRefresh={onRefresh} testid={`engagement-delete-${e.id}`} label={e.title} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        )}
      </div>
    );
  }

  // ── Task detail (/todo/{id}) ──────────────────────────────────────────────
  if (viewRoute.startsWith("/todo/")) {
    const t = tasks.find((x) => x.id === viewRoute.split("/").pop());
    if (!t) return <div className="tw-empty">Task not found.</div>;
    const subtasks = t.subtasks ?? [];
    const done = subtasks.filter((c) => c.done).length;
    const overdue = isOverdue(t, today);
    return (
      <div className="tw-screen" data-testid="task-detail">
        <button type="button" className="tw-back" onClick={() => onNavigate("/todo")}><ArrowLeft size={14} /> All tasks</button>
        <h1 className="tw-h1">{t.title}</h1>
        <div className="flex flex-wrap items-center gap-2 mt-1">
          <StatusBadge status={t.status} />
          <PriorityBadge priority={t.priority} />
          {overdue && <OverdueBadge />}
        </div>

        <div className="tw-stats" style={{ marginTop: 18 }}>
          <Stat label="Group" value={t.group || "General"} />
          <Stat label="Due" value={t.dueDate ? dayLabel(t.dueDate.slice(0, 10), today) : "—"} />
          <Stat label="Subtasks" value={`${done}/${subtasks.length}`} />
        </div>

        {t.notes && (
          <section className="tw-section">
            <h2 className="tw-h2">Notes</h2>
            <div className="tw-doc"><p className="tw-subtle" style={{ margin: 0 }}>{t.notes}</p></div>
          </section>
        )}

        <TaskDetailEditor task={t} sessionId={sessionId} onRefresh={onRefresh} onNavigate={onNavigate} groups={Array.from(new Set(tasks.map((x) => x.group).filter((g): g is string => !!g)))} />
        <SubtaskEditor task={t} sessionId={sessionId} onRefresh={onRefresh} />
      </div>
    );
  }

  // ── To-Do (/todo) — tasks grouped by bucket ───────────────────────────────
  if (viewRoute === "/todo") {
    const overdueCount = tasks.filter((t) => isOverdue(t, today)).length;
    const groups = Array.from(new Set(tasks.map((t) => t.group || "General")));
    return (
      <div className="tw-screen" data-testid="todo-screen">
        <h1 className="tw-h1">Tasks</h1>
        <p className="tw-subtle">Your tasks, grouped.</p>
        <div className="tw-stats">
          <Stat label="Tasks" value={tasks.length} />
          <Stat label="Open" value={tasks.filter((t) => t.status !== "Done").length} />
          <Stat label="Due today" value={tasks.filter((t) => t.status !== "Done" && (t.dueDate || "").slice(0, 10) === today).length} />
          <Stat label="Overdue" value={overdueCount} />
        </div>
        <AddTaskBar sessionId={sessionId} onRefresh={onRefresh} groups={groups} />
        {tasks.length === 0 ? (
          <section className="tw-section"><div className="tw-empty-sm">No tasks yet. Add one above, or ask the assistant.</div></section>
        ) : (
          groups.map((group) => {
            const rows = tasks.filter((t) => (t.group || "General") === group);
            return (
              <section className="tw-section" key={group} data-testid={`todo-group-${group}`}>
                <h2 className="tw-h2">{group} <span className="tw-count">{rows.length}</span></h2>
                <table className="tw-table" data-testid="tasks-table">
                  <thead><tr><th>Task</th><th>Status</th><th>Priority</th><th>Due</th><th>Subtasks</th><th></th></tr></thead>
                  <tbody>
                    {rows.map((t) => {
                      const subtasks = t.subtasks ?? [];
                      const done = subtasks.filter((c) => c.done).length;
                      const overdue = isOverdue(t, today);
                      return (
                        <tr key={t.id} data-testid={`task-row-${t.id}`} className={`tw-rowlink ${isNew(t.id) ? "tw-row-new" : ""}`} onClick={() => onNavigate(`/todo/${t.id}`)}>
                          <td className="tw-td-title"><button type="button" style={rowTitleBtn} onClick={(e) => { e.stopPropagation(); onNavigate(`/todo/${t.id}`); }}>{t.title}</button>{isNew(t.id) && <span className="tw-new">New</span>}</td>
                          <td><StatusBadge status={t.status} /></td>
                          <td><PriorityBadge priority={t.priority} /></td>
                          <td className={overdue ? "tw-due-overdue" : ""}>{t.dueDate ? dayLabel(t.dueDate.slice(0, 10), today) : "—"}{overdue && <span style={{ fontSize: 11, fontWeight: 600 }}> · overdue</span>}</td>
                          <td className="tw-td-mono">{done}/{subtasks.length}</td>
                          <td onClick={(e) => e.stopPropagation()}><RowDelete onDelete={() => deleteTask(sessionId!, t.id)} onRefresh={onRefresh} testid={`task-delete-${t.id}`} label={t.title} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
            );
          })
        )}
      </div>
    );
  }

  // ── Calendar (/calendar) — agenda by day, merging events + tasks-with-dueDate ──
  if (viewRoute === "/calendar") {
    type AgendaItem = { kind: "event" | "task"; id: string; date: string; sort: string; title: string; meta: string };
    const items: AgendaItem[] = [];
    for (const e of events) {
      if (!e.date) continue;
      items.push({ kind: "event", id: e.id, date: e.date.slice(0, 10), sort: e.start || "00:00", title: e.title, meta: `${e.type || "Event"}${e.start ? ` · ${e.start}${e.end ? `–${e.end}` : ""}` : ""}` });
    }
    for (const t of tasks) {
      if (!t.dueDate || t.status === "Done") continue;
      items.push({ kind: "task", id: t.id, date: t.dueDate.slice(0, 10), sort: "zz", title: t.title, meta: `Task due · ${t.group || "General"}` });
    }
    const days = Array.from(new Set(items.map((i) => i.date))).sort();
    return (
      <div className="tw-screen" data-testid="calendar-screen">
        <h1 className="tw-h1">Calendar</h1>
        <p className="tw-subtle">Events and task deadlines, by day.</p>
        <AddEventBar sessionId={sessionId} onRefresh={onRefresh} />
        {items.length === 0 ? (
          <section className="tw-section"><div className="tw-empty-sm">Nothing scheduled yet. Add an event above, or ask the assistant.</div></section>
        ) : (
          days.map((day) => {
            const dayItems = items.filter((i) => i.date === day).sort((a, b) => (a.sort < b.sort ? -1 : 1));
            return (
              <section className="tw-section" key={day} data-testid={`calendar-day-${day}`}>
                <h2 className="tw-h2">
                  <CalendarIcon size={14} /> {dayLabel(day, today)} <span className="tw-count">{dayItems.length}</span>
                </h2>
                <div className="tw-doclist">
                  {dayItems.map((i) => (
                    <div
                      key={`${i.kind}-${i.id}`}
                      className={`tw-docitem ${i.kind === "task" ? "tw-rowlink" : ""}`}
                      data-testid={`agenda-${i.kind}-${i.id}`}
                      onClick={i.kind === "task" ? () => onNavigate(`/todo/${i.id}`) : undefined}
                      onKeyDown={i.kind === "task" ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNavigate(`/todo/${i.id}`); } } : undefined}
                      role={i.kind === "task" ? "button" : undefined}
                      tabIndex={i.kind === "task" ? 0 : undefined}
                      style={i.kind === "task" ? undefined : { cursor: "default" }}
                    >
                      {i.kind === "event" ? <Clock size={15} /> : <CheckSquareDot />}
                      <span className="flex flex-col min-w-0">
                        <span className="tw-td-title">{i.title}</span>
                        <span className="tw-td-sub">{i.meta}</span>
                      </span>
                      {i.kind === "event" && <span style={{ marginLeft: "auto" }}><RowDelete onDelete={() => deleteEvent(sessionId!, i.id)} onRefresh={onRefresh} testid={`event-delete-${i.id}`} label={i.title} /></span>}
                    </div>
                  ))}
                </div>
              </section>
            );
          })
        )}
      </div>
    );
  }

  // ── Documents (/documents) — Library (persistent KB) vs this session (ephemeral) ──
  if (viewRoute === "/documents") {
    const library = appState.library ?? [];
    const libNames = new Set(library.map((d) => d.filename));
    // Session files that haven't been promoted yet (a promoted file shows under Library).
    const sessionUploaded = uploadedFiles.filter((f) => !libNames.has(f.filename));
    const sessionGenerated = generatedFiles.filter((f) => !libNames.has(f.filename));
    return (
      <div className="tw-screen" data-testid="documents-screen">
        <h1 className="tw-h1">Documents</h1>
        <LibraryGroup docs={library} onOpen={(f) => onOpenDoc(f, true)} onRemove={onRemoveFromLibrary} />
        <SessionDocs label="Uploaded this session" files={sessionUploaded} testid="uploaded-group"
          emptyLabel="No uploads this session. Upload a file to work with it here." onOpen={onOpenDoc} onSave={onSaveToLibrary} onUpload={onUpload} />
        <SessionDocs label="Generated this session" files={sessionGenerated} testid="generated-group"
          emptyLabel="No generated documents yet. Ask the assistant to draft one." onOpen={onOpenDoc} onSave={onSaveToLibrary} />
      </div>
    );
  }

  // ── Reminders (/reminders) — scheduled prompts emailed on a cadence ────────
  if (viewRoute === "/reminders") {
    const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const cadence = (s: Schedule) => {
      const tz = s.timezone || "UTC";
      if (s.frequency === "weekly") {
        const days = (s.daysOfWeek ?? []).slice().sort((a, b) => a - b).map((d) => dayNames[d]).join(", ");
        return `Weekly on ${days || "—"} at ${s.time} (${tz})`;
      }
      return `Daily at ${s.time} (${tz})`;
    };
    const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "—");
    return (
      <div className="tw-screen" data-testid="reminders-screen">
        <h1 className="tw-h1">Reminders</h1>
        <p className="tw-subtle">Recurring check-ins the assistant runs for you and emails the result.</p>
        <AddReminderBar sessionId={sessionId} onRefresh={onRefresh} />
        {schedules.length === 0 ? (
          <section className="tw-section"><div className="tw-empty-sm">No reminders yet. Add one above, or ask the assistant.</div></section>
        ) : (
          <section className="tw-section">
            <table className="tw-table" data-testid="reminders-table">
              <thead><tr><th>Reminder</th><th>Repeats</th><th>Next run</th><th>Last run</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {schedules.map((s) => (
                  <tr key={s.id} data-testid={`reminder-row-${s.id}`} className={isNew(s.id) ? "tw-row-new" : ""}>
                    <td className="tw-td-title">
                      {s.title}{isNew(s.id) && <span className="tw-new">New</span>}
                      <span className="tw-td-sub">{s.prompt}</span>
                    </td>
                    <td>{cadence(s)}</td>
                    <td className="tw-td-mono">{when(s.nextRunAt)}</td>
                    <td className="tw-td-mono">{s.lastRunAt ? when(s.lastRunAt) : "—"}</td>
                    <td>{!s.enabled ? "Paused" : (s.lastStatus ?? "Scheduled")}</td>
                    <td><ReminderActions schedule={s} sessionId={sessionId} onRefresh={onRefresh} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
    );
  }

  // ── Home (default) — today's agenda ───────────────────────────────────────
  const openTasks = tasks.filter((t) => t.status !== "Done");
  const overdue = tasks.filter((t) => isOverdue(t, today));
  const dueToday = openTasks.filter((t) => (t.dueDate || "").slice(0, 10) === today);
  const eventsToday = events.filter((e) => (e.date || "").slice(0, 10) === today)
    .sort((a, b) => ((a.start || "") < (b.start || "") ? -1 : 1));
  const nextEvents = events.filter((e) => (e.date || "").slice(0, 10) >= today)
    .sort((a, b) => (`${a.date}${a.start || ""}` < `${b.date}${b.start || ""}` ? -1 : 1))
    .slice(0, 5);
  return (
    <div className="tw-screen" data-testid="home-screen">
      <h1 className="tw-h1">Home</h1>
      <p className="tw-subtle">Today&apos;s agenda — {absDate(today)}.</p>
      <div className="tw-stats">
        <Stat label="Tasks" value={tasks.length} />
        <Stat label="Open" value={openTasks.length} />
        <Stat label="Due today" value={dueToday.length} />
        <Stat label="Overdue" value={overdue.length} />
      </div>

      {overdue.length > 0 && (
        <section className="tw-section">
          <h2 className="tw-h2">Overdue <span className="tw-count">{overdue.length}</span></h2>
          <table className="tw-table" data-testid="overdue-table">
            <thead><tr><th>Task</th><th>Group</th><th>Status</th><th>Due</th></tr></thead>
            <tbody>
              {overdue.map((t) => (
                <tr key={t.id} className="tw-rowlink" data-testid={`overdue-row-${t.id}`} onClick={() => onNavigate(`/todo/${t.id}`)}>
                  <td className="tw-td-title"><button type="button" style={rowTitleBtn} onClick={(e) => { e.stopPropagation(); onNavigate(`/todo/${t.id}`); }}>{t.title}</button></td>
                  <td>{t.group || "General"}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="tw-due-overdue">{t.dueDate ? dayLabel(t.dueDate.slice(0, 10), today) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="tw-section">
        <h2 className="tw-h2">Due today</h2>
        {dueToday.length === 0 ? <div className="tw-empty-sm">Nothing due today.</div> : (
          <table className="tw-table" data-testid="due-today-table">
            <thead><tr><th>Task</th><th>Group</th><th>Status</th><th>Priority</th></tr></thead>
            <tbody>
              {dueToday.map((t) => (
                <tr key={t.id} className="tw-rowlink" onClick={() => onNavigate(`/todo/${t.id}`)}>
                  <td className="tw-td-title"><button type="button" style={rowTitleBtn} onClick={(e) => { e.stopPropagation(); onNavigate(`/todo/${t.id}`); }}>{t.title}</button></td>
                  <td>{t.group || "General"}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td><PriorityBadge priority={t.priority} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="tw-section">
        <h2 className="tw-h2">{eventsToday.length > 0 ? "Today's events" : "Next up"}</h2>
        {(eventsToday.length > 0 ? eventsToday : nextEvents).length === 0 ? (
          <div className="tw-empty-sm">No upcoming events.</div>
        ) : (
          <div className="tw-doclist" data-testid="home-events">
            {(eventsToday.length > 0 ? eventsToday : nextEvents).map((e) => (
              <div key={e.id} className="tw-docitem" style={{ cursor: "default" }} data-testid={`home-event-${e.id}`}>
                <Clock size={15} />
                <span className="flex flex-col min-w-0">
                  <span className="tw-td-title">{e.title}</span>
                  <span className="tw-td-sub">{dayLabel(e.date, today)}{e.start ? ` · ${e.start}${e.end ? `–${e.end}` : ""}` : ""}{e.type ? ` · ${e.type}` : ""}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

// Small green-dot marker reused for task items in the agenda.
function CheckSquareDot() {
  return <CheckCircle2 size={15} className="text-green-500" />;
}

// "Today" / "Tomorrow" / weekday-date label for an ISO day vs. today.
// Formatted deterministically (fixed UTC + fixed names, no toLocaleDateString) so the
// server prerender and client hydration always produce the identical string regardless
// of locale/timezone — avoids React hydration mismatches on date-derived text.
const _WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const _MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function dayLabel(iso: string, today: string): string {
  if (iso === today) return "Today";
  const d = new Date(`${iso}T00:00:00Z`);
  const t = new Date(`${today}T00:00:00Z`);
  const diff = Math.round((d.getTime() - t.getTime()) / 86_400_000);
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  const [, m, day] = iso.split("-").map(Number);
  return `${_WD[d.getUTCDay()]}, ${_MO[m - 1]} ${day}`;
}

// Absolute "Wed, Jun 25" label (no Today/Tomorrow relativity) — deterministic like dayLabel.
function absDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  const [, m, day] = iso.split("-").map(Number);
  return `${_WD[d.getUTCDay()]}, ${_MO[m - 1]} ${day}`;
}


function Stat({ label, value }: { label: string; value: number | string }) {
  return <div className="tw-stat"><div className="tw-stat-value">{value}</div><div className="tw-stat-label">{label}</div></div>;
}

const docActionBtn: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
  padding: "4px 10px", borderRadius: 8, border: "1px solid var(--border-subtle, #e5e7eb)",
  background: "var(--surface-1, #fff)", color: "var(--text-secondary, #444)", cursor: "pointer", whiteSpace: "nowrap",
};
// A row's title rendered as a real <button> so it's keyboard-focusable and announced as one
// control — the accessible navigation target. The <tr> keeps a mouse-only onClick for convenience
// but is NOT given role=button (which would invalidate its <td> cells and nest the delete button).
const rowTitleBtn: React.CSSProperties = { background: "none", border: "none", padding: 0, margin: 0, font: "inherit", color: "inherit", cursor: "pointer", textAlign: "left", width: "100%" };
const docRow: React.CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const docMainBtn: React.CSSProperties = { display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0, background: "none", border: "none", padding: 0, cursor: "pointer", textAlign: "left", color: "inherit" };

// The persistent Library: documents indexed in the KB, searchable across every session.
function LibraryGroup({ docs, onOpen, onRemove }: { docs: LibraryDoc[]; onOpen: (f: string) => void; onRemove: (f: string) => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  return (
    <section className="tw-section" data-testid="library-group">
      <h2 className="tw-h2">Library <span className="tw-count">{docs.length}</span>
        <span className="tw-td-sub" style={{ marginLeft: 8, fontWeight: 400 }}>persistent · searchable across sessions</span>
      </h2>
      {docs.length === 0 ? (
        <div className="tw-empty-sm">Your Library is empty. Save a session file to keep it permanently and make it searchable.</div>
      ) : (
        <div className="tw-doclist">
          {docs.map((d) => (
            <div key={d.filename} className="tw-docitem" style={docRow} data-testid={`lib-${d.filename}`}>
              <button type="button" style={docMainBtn} onClick={() => onOpen(d.filename)}>
                <BookMarked size={15} />
                <span className="truncate">{d.filename}</span>
                {d.source === "reference" && <span className="tw-td-sub">reference</span>}
              </button>
              <button type="button" style={docActionBtn} aria-label={`Remove ${d.filename} from Library`} title="Remove from Library" data-testid={`lib-remove-${d.filename}`}
                disabled={busy === d.filename}
                onClick={async () => { setBusy(d.filename); try { await onRemove(d.filename); } finally { setBusy(null); } }}>
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// Ephemeral session files (uploads + drafts). Each can be promoted into the Library.
function SessionDocs({ label, files, testid, emptyLabel, onOpen, onSave, onUpload }: {
  label: string; files: AppFile[]; testid: string; emptyLabel: string;
  onOpen: (f: string) => void; onSave: (f: string) => Promise<void>; onUpload?: (file: File) => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  return (
    <section className="tw-section" data-testid={testid}>
      <h2 className="tw-h2">{label} <span className="tw-count">{files.length}</span>
        {onUpload && (
          <>
            <button type="button" style={{ ...docActionBtn, marginLeft: 10 }} data-testid="upload-doc-btn" onClick={() => inputRef.current?.click()}>
              <Upload size={13} /> Upload
            </button>
            <input ref={inputRef} type="file" data-testid="upload-doc-input" style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void onUpload(f); e.target.value = ""; }} />
          </>
        )}
      </h2>
      {files.length === 0 ? <div className="tw-empty-sm">{emptyLabel}</div> : (
        <div className="tw-doclist">
          {files.map((f) => (
            <div key={f.filename} className="tw-docitem" style={docRow} data-testid={`doc-${f.filename}`}>
              <button type="button" style={docMainBtn} onClick={() => onOpen(f.filename)}>
                <FileText size={15} />
                <span className="truncate">{f.filename}</span>
                {f.status === "pending" && <span className="tw-doc-pending">processing…</span>}
              </button>
              {f.status !== "pending" && (
                <button type="button" style={docActionBtn} title="Save to Library" data-testid={`save-lib-${f.filename}`}
                  disabled={busy === f.filename}
                  onClick={async () => { setBusy(f.filename); try { await onSave(f.filename); } finally { setBusy(null); } }}>
                  <BookMarked size={13} /> {busy === f.filename ? "Saving…" : "Save to Library"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function DocViewer({ doc, onBack }: { doc: { filename: string; content: string; mime?: string; loading: boolean; error: string | null }; onBack: () => void }) {
  const isCsv = doc.filename.toLowerCase().endsWith(".csv");
  return (
    <div className="tw-screen" data-testid="doc-viewer">
      <button type="button" className="tw-back" onClick={onBack}><ArrowLeft size={14} /> All documents</button>
      <h1 className="tw-h1">{doc.filename}</h1>
      {doc.loading ? <div className="tw-empty-sm">Loading…</div> :
        doc.error ? <div className="tw-empty-sm">{doc.error}</div> :
        isCsv ? <CsvTable content={doc.content} /> :
        <div className="tw-doc"><MarkdownRenderer content={doc.content} /></div>}
    </div>
  );
}

// ── Manual CRUD controls (AI-free — hit the orchestrator, then refresh) ───────
// Custom down-chevron so native <select> matches the app's design language instead of the OS widget.
const CHEVRON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23676879' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E";
const inputStyle: React.CSSProperties = {
  fontSize: 13, padding: "7px 9px", borderRadius: 8, color: "inherit", minWidth: 0,
  border: "1px solid var(--border-subtle, #e5e7eb)", background: "var(--surface-1, #fff)",
};
const selectStyle: React.CSSProperties = {
  ...inputStyle, appearance: "none", WebkitAppearance: "none", MozAppearance: "none", cursor: "pointer",
  paddingRight: 26, backgroundImage: `url("${CHEVRON}")`, backgroundRepeat: "no-repeat", backgroundPosition: "right 8px center",
};
const primaryBtn: React.CSSProperties = { ...docActionBtn, background: "var(--brand-primary, #0073ea)", color: "#fff", border: "1px solid var(--brand-primary, #0073ea)" };
const primaryBtnOff: React.CSSProperties = { ...docActionBtn, background: "var(--surface-2, #eef0f4)", color: "var(--text-muted, #9699a6)", border: "1px solid var(--border-subtle, #e5e7eb)", cursor: "not-allowed" };
const dangerBtn: React.CSSProperties = { ...docActionBtn, background: "#d6333c", color: "#fff", border: "1px solid #d6333c" };
const formCard: React.CSSProperties = {
  width: "100%", marginTop: 10, marginBottom: 4, padding: 14, borderRadius: 12,
  border: "1px solid var(--border-subtle, #e5e7eb)", background: "var(--surface-2, #f7f8fa)",
  display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end",
};
const fieldLabelStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 4, fontSize: 10.5, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--text-secondary, #676879)" };
const formRow: React.CSSProperties = { display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" };

// A labelled form field — the wrapping <label> gives the control an accessible name (a11y).
// `grow` lets the field absorb horizontal slack so a full-width form card doesn't strand a gutter.
function Field({ label, children, grow }: { label: string; children: React.ReactNode; grow?: boolean }) {
  return <label style={grow ? { ...fieldLabelStyle, flex: "1 1 220px" } : fieldLabelStyle}>{label}{children}</label>;
}

// Inline, role=alert error surfaced when a manual mutation fails (fail loud — never swallow).
function FormErr({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return <div role="alert" style={{ flexBasis: "100%", marginTop: 2, fontSize: 12, color: "#c0344d", display: "flex", alignItems: "center", gap: 6 }}><AlertTriangle size={13} strokeWidth={2.5} /> {msg}</div>;
}

function useMut(onRefresh: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    void (async () => {
      try { await fn(); await onRefresh(); }
      catch (e) { setErr(friendlyError(e, "Something went wrong. Please try again.")); }
      finally { setBusy(false); }
    })();
  };
  return { busy, err, run };
}

function AddTaskBar({ sessionId, onRefresh, groups }: { sessionId: string | null; onRefresh: () => Promise<void>; groups: string[] }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("Medium");
  const [group, setGroup] = useState("General");
  const [due, setDue] = useState("");
  const { busy, err, run } = useMut(onRefresh);
  if (!open) return <button type="button" style={{ ...docActionBtn, marginTop: 4 }} data-testid="add-task-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add task</button>;
  const submit = () => { if (!sessionId || !title.trim()) return; run(async () => { await createTask(sessionId, { title: title.trim(), priority, group: group.trim() || "General", dueDate: due }); setTitle(""); setDue(""); setOpen(false); }); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") submit(); else if (e.key === "Escape") setOpen(false); };
  return (
    <div style={formCard} data-testid="add-task-form" onKeyDown={onKey}>
      <Field label="Title" grow><input autoFocus aria-label="Task title" placeholder="e.g. Draft the Q3 plan" value={title} style={{ ...inputStyle, width: "100%", minWidth: 200 }} data-testid="task-title-input" onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label="Priority"><select aria-label="Priority" value={priority} style={selectStyle} data-testid="task-priority-select" onChange={(e) => setPriority(e.target.value)}>{["Low", "Medium", "High"].map((p) => <option key={p}>{p}</option>)}</select></Field>
      <Field label="Group">
        <input aria-label="Group" list="task-group-options" placeholder="General" value={group} style={{ ...inputStyle, width: 130 }} onChange={(e) => setGroup(e.target.value)} />
        <datalist id="task-group-options">{groups.map((g) => <option key={g} value={g} />)}</datalist>
      </Field>
      <Field label="Due date" grow><input type="date" aria-label="Due date" value={due} style={{ ...inputStyle, width: "100%" }} data-testid="task-due-input" onChange={(e) => setDue(e.target.value)} /></Field>
      <span style={{ display: "inline-flex", gap: 6 }}>
        <button type="button" style={title.trim() && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !title.trim()} data-testid="task-save-btn" onClick={submit}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
      </span>
      <FormErr msg={err} />
    </div>
  );
}

// Destructive deletes require a deliberate two-step confirm (arm → confirm) so a stray
// click can't silently destroy a record; the mutation surfaces failures rather than swallowing them.
function RowDelete({ onDelete, onRefresh, testid, label }: { onDelete: () => Promise<unknown>; onRefresh: () => Promise<void>; testid: string; label: string }) {
  const [armed, setArmed] = useState(false);
  const { busy, err, run } = useMut(onRefresh);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (armed) confirmRef.current?.focus(); }, [armed]);
  if (armed) {
    return (
      <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }} onClick={(e) => e.stopPropagation()}>
        <button ref={confirmRef} type="button" style={{ ...dangerBtn, padding: "3px 8px" }} aria-label={`Confirm delete ${label}`} data-testid={`${testid}-confirm`} disabled={busy}
          onClick={(e) => { e.stopPropagation(); run(onDelete); }}>{busy ? "…" : "Confirm"}</button>
        <button type="button" style={{ ...docActionBtn, padding: "3px 7px" }} aria-label="Cancel delete" disabled={busy}
          onClick={(e) => { e.stopPropagation(); setArmed(false); }}>✕</button>
        {err && <span role="alert" title={err} style={{ fontSize: 11, color: "#c0344d", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{err}</span>}
      </span>
    );
  }
  return <button type="button" style={{ ...docActionBtn, padding: "3px 7px" }} aria-label={`Delete ${label}`} title={`Delete ${label}`} data-testid={testid}
    onClick={(e) => { e.stopPropagation(); setArmed(true); }}><Trash2 size={13} /></button>;
}

function TaskDetailEditor({ task, sessionId, onRefresh, onNavigate, groups }: { task: Task; sessionId: string | null; onRefresh: () => Promise<void>; onNavigate: (r: string) => void; groups: string[] }) {
  const { busy, err, run } = useMut(onRefresh);
  const [saved, setSaved] = useState(false);
  const [armed, setArmed] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  // Auto-save on change (no Save button); show a Saving…/Saved indicator instead of freezing the pane.
  const patch = (body: Partial<{ status: string; priority: string; dueDate: string; title: string; group: string }>) => { if (sessionId) { setSaved(false); run(async () => { await updateTask(sessionId, task.id, body); setSaved(true); }); } };
  // Transient "Saved ✓" — clear it a couple seconds after a save settles.
  useEffect(() => { if (!saved) return; const id = setTimeout(() => setSaved(false), 2200); return () => clearTimeout(id); }, [saved]);
  // Move focus to Confirm when the delete is armed (consistent with RowDelete/ReminderActions).
  useEffect(() => { if (armed) confirmRef.current?.focus(); }, [armed]);
  return (
    <section className="tw-section" data-testid="task-edit">
      <h2 className="tw-h2">Edit{" "}
        <span aria-live="polite" style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary,#676879)" }}>
          {busy ? "Saving…" : saved ? "Saved ✓" : ""}
        </span>
      </h2>
      <div style={{ ...formRow, gap: 14, alignItems: "flex-end" }}>
        <Field label="Title" grow><input aria-label="Task title" defaultValue={task.title} style={{ ...inputStyle, width: "100%", minWidth: 220 }} data-testid="edit-title"
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== task.title) patch({ title: v }); }} /></Field>
        <Field label="Group"><input aria-label="Group" list="edit-group-options" defaultValue={task.group || ""} style={{ ...inputStyle, width: 150 }} data-testid="edit-group"
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v !== (task.group || "")) patch({ group: v || "General" }); }} />
          <datalist id="edit-group-options">{groups.map((g) => <option key={g} value={g} />)}</datalist></Field>
        <Field label="Status"><select value={task.status} style={selectStyle} data-testid="edit-status" onChange={(e) => patch({ status: e.target.value })}>{["To do", "In progress", "Blocked", "Done"].map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Priority"><select value={task.priority} style={selectStyle} data-testid="edit-priority" onChange={(e) => patch({ priority: e.target.value })}>{["Low", "Medium", "High"].map((p) => <option key={p}>{p}</option>)}</select></Field>
        <Field label="Due date"><input type="date" value={task.dueDate || ""} style={inputStyle} data-testid="edit-due" onChange={(e) => { if (e.target.value !== (task.dueDate || "")) patch({ dueDate: e.target.value }); }} /></Field>
        {armed ? (
          <span style={{ marginLeft: "auto", display: "inline-flex", gap: 6, alignItems: "center" }}>
            <button ref={confirmRef} type="button" style={dangerBtn} data-testid="delete-task-confirm" disabled={busy}
              onClick={() => { if (sessionId) run(async () => { await deleteTask(sessionId, task.id); onNavigate("/todo"); }); }}><Trash2 size={13} /> Confirm delete</button>
            <button type="button" style={docActionBtn} disabled={busy} onClick={() => setArmed(false)}>Cancel</button>
          </span>
        ) : (
          <button type="button" style={{ ...docActionBtn, marginLeft: "auto" }} data-testid="delete-task-btn" onClick={() => setArmed(true)}><Trash2 size={13} /> Delete task</button>
        )}
      </div>
      <FormErr msg={err} />
    </section>
  );
}

function SubtaskEditor({ task, sessionId, onRefresh }: { task: Task; sessionId: string | null; onRefresh: () => Promise<void> }) {
  const subtasks = task.subtasks ?? [];
  const [text, setText] = useState("");
  const { busy, err, run } = useMut(onRefresh);
  const add = () => { if (sessionId && text.trim()) run(async () => { await addSubtask(sessionId, task.id, text.trim()); setText(""); }); };
  return (
    <section className="tw-section">
      <h2 className="tw-h2">Subtasks <span className="tw-count">{subtasks.length}</span></h2>
      {subtasks.length > 0 && (
        <div className="tw-doclist" data-testid="task-subtasks">
          {subtasks.map((c, i) => {
            const toggle = () => { if (sessionId && !busy) run(() => toggleSubtask(sessionId, task.id, i, !c.done)); };
            return (
              <div key={i} className="tw-docitem" style={{ gap: 8 }}>
                <button type="button" role="checkbox" aria-checked={c.done} data-testid={`subtask-${i}`} disabled={busy}
                  style={{ background: "none", border: "none", padding: 0, display: "flex", alignItems: "center", gap: 8, cursor: "pointer", color: "inherit", flex: 1, minWidth: 0, textAlign: "left" }}
                  onClick={toggle}>
                  {c.done ? <CheckCircle2 size={15} className="text-green-500" /> : <Circle size={15} />}
                  <span className={c.done ? "line-through opacity-60" : ""}>{c.text}</span>
                </button>
                <button type="button" style={{ ...docActionBtn, padding: "2px 6px" }} aria-label={`Delete subtask: ${c.text}`} title="Delete subtask" data-testid={`subtask-delete-${i}`} disabled={busy}
                  onClick={() => { if (sessionId && !busy) run(() => deleteSubtask(sessionId, task.id, i)); }}><Trash2 size={12} /></button>
              </div>
            );
          })}
        </div>
      )}
      <span style={{ ...formRow, marginTop: 8 }}>
        <input aria-label="New subtask" placeholder="Add a subtask…" value={text} style={{ ...inputStyle, minWidth: 200 }} data-testid="subtask-input" onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
        <button type="button" style={text.trim() && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !text.trim()} data-testid="subtask-add-btn" onClick={add}><Plus size={13} /> Add</button>
      </span>
      <FormErr msg={err} />
    </section>
  );
}

function AddEventBar({ sessionId, onRefresh }: { sessionId: string | null; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const { busy, err, run } = useMut(onRefresh);
  if (!open) return <button type="button" style={{ ...docActionBtn, marginTop: 4 }} data-testid="add-event-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add event</button>;
  const timeBad = !!(start && end && end <= start);
  const ok = !!(title.trim() && date && !timeBad);
  const submit = () => { if (!sessionId || !ok) return; run(async () => { await createEvent(sessionId, { title: title.trim(), date, start, end }); setTitle(""); setDate(""); setStart(""); setEnd(""); setOpen(false); }); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") submit(); else if (e.key === "Escape") setOpen(false); };
  return (
    <div style={formCard} data-testid="add-event-form" onKeyDown={onKey}>
      <Field label="Title" grow><input autoFocus aria-label="Event title" placeholder="e.g. Northstar sync" value={title} style={{ ...inputStyle, width: "100%", minWidth: 180 }} data-testid="event-title-input" onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label="Date"><input type="date" aria-label="Event date" value={date} style={inputStyle} data-testid="event-date-input" onChange={(e) => setDate(e.target.value)} /></Field>
      <Field label="Start"><input type="time" aria-label="Start time" value={start} style={inputStyle} data-testid="event-start-input" onChange={(e) => setStart(e.target.value)} /></Field>
      <Field label="End"><input type="time" aria-label="End time" value={end} style={inputStyle} data-testid="event-end-input" onChange={(e) => setEnd(e.target.value)} /></Field>
      <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
        <button type="button" style={ok && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !ok} data-testid="event-save-btn" onClick={submit}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
        {timeBad && <span style={{ fontSize: 11, color: "var(--text-secondary,#676879)" }}>End must be after start.</span>}
      </span>
      <FormErr msg={err} />
    </div>
  );
}

const DAY_NAMES_UI = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function AddReminderBar({ sessionId, onRefresh }: { sessionId: string | null; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [frequency, setFrequency] = useState("daily");
  const [time, setTime] = useState("08:00");
  const [days, setDays] = useState<number[]>([]);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const { busy, err, run } = useMut(onRefresh);
  if (!open) return <button type="button" style={{ ...docActionBtn, marginTop: 4 }} data-testid="add-reminder-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add reminder</button>;
  const needsDay = frequency === "weekly" && days.length === 0;
  const ok = !!(title.trim() && prompt.trim() && time && !needsDay);
  const submit = () => { if (!sessionId || !ok) return; run(async () => { await createSchedule(sessionId, { title: title.trim(), prompt: prompt.trim(), frequency, time, timezone: tz, daysOfWeek: frequency === "weekly" ? days : [] }); setOpen(false); }); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter" && e.target instanceof HTMLInputElement) submit(); else if (e.key === "Escape") setOpen(false); };
  return (
    <div style={{ ...formCard, alignItems: "flex-start", flexDirection: "column", gap: 10 }} data-testid="add-reminder-form" onKeyDown={onKey}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end", width: "100%" }}>
        <Field label="Name"><input autoFocus aria-label="Reminder name" placeholder="e.g. Weekly digest" value={title} style={{ ...inputStyle, minWidth: 220 }} data-testid="reminder-title-input" onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="What should it do?" grow><input aria-label="What should it do?" placeholder="e.g. summarize what's due this week" value={prompt} style={{ ...inputStyle, width: "100%", minWidth: 240 }} data-testid="reminder-prompt-input" onChange={(e) => setPrompt(e.target.value)} /></Field>
        <Field label="Repeats"><select aria-label="Repeats" value={frequency} style={selectStyle} data-testid="reminder-frequency-select" onChange={(e) => setFrequency(e.target.value)}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></Field>
        <Field label={`Time (${tz})`}><input type="time" aria-label="Time" value={time} style={inputStyle} data-testid="reminder-time-input" onChange={(e) => setTime(e.target.value)} /></Field>
      </div>
      {frequency === "weekly" && (
        <span style={formRow} data-testid="reminder-days" role="group" aria-label="Days of week">
          {DAY_NAMES_UI.map((d, i) => {
            const on = days.includes(i);
            return (
              <button key={d} type="button" aria-pressed={on} style={{ ...inputStyle, padding: "5px 9px", cursor: "pointer", fontWeight: 600, background: on ? "var(--brand-primary,#0073ea)" : "var(--surface-1,#fff)", color: on ? "#fff" : "inherit", border: on ? "1px solid var(--brand-primary,#0073ea)" : inputStyle.border }}
                onClick={() => setDays((cur) => cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i])}>{d}</button>
            );
          })}
        </span>
      )}
      <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
        <button type="button" style={ok && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !ok} data-testid="reminder-save-btn" onClick={submit}>{busy ? "Saving…" : "Save reminder"}</button>
        <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
        {needsDay && <span style={{ fontSize: 11, color: "var(--text-secondary,#676879)" }}>Pick at least one day.</span>}
      </span>
      <FormErr msg={err} />
    </div>
  );
}

function ReminderActions({ schedule, sessionId, onRefresh }: { schedule: Schedule; sessionId: string | null; onRefresh: () => Promise<void> }) {
  const { busy, err, run } = useMut(onRefresh);
  const [armed, setArmed] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (armed) confirmRef.current?.focus(); }, [armed]);
  return (
    <span style={{ ...formRow, gap: 6 }}>
      <button type="button" style={docActionBtn} aria-label={schedule.enabled ? `Pause ${schedule.title}` : `Resume ${schedule.title}`} data-testid={`reminder-toggle-${schedule.id}`} disabled={busy}
        onClick={() => { if (sessionId) run(() => updateSchedule(sessionId, schedule.id, { enabled: !schedule.enabled })); }}>{schedule.enabled ? "Pause" : "Resume"}</button>
      {armed ? (
        <>
          <button ref={confirmRef} type="button" style={{ ...dangerBtn, padding: "4px 9px" }} aria-label={`Confirm delete ${schedule.title}`} data-testid={`reminder-delete-${schedule.id}-confirm`} disabled={busy}
            onClick={() => { if (sessionId) run(() => deleteSchedule(sessionId, schedule.id)); }}>{busy ? "…" : "Confirm"}</button>
          <button type="button" style={docActionBtn} aria-label="Cancel delete" disabled={busy} onClick={() => setArmed(false)}>✕</button>
        </>
      ) : (
        <button type="button" style={docActionBtn} aria-label={`Delete ${schedule.title}`} title="Delete" data-testid={`reminder-delete-${schedule.id}`} disabled={busy}
          onClick={() => setArmed(true)}><Trash2 size={13} /></button>
      )}
      {err && <span role="alert" title={err} style={{ fontSize: 11, color: "#c0344d", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{err}</span>}
    </span>
  );
}

const ENGAGEMENT_STAGES = ["Discovery", "Design", "Build", "Deploy", "Live", "Closed"];

function AddEngagementBar({ sessionId, onRefresh }: { sessionId: string | null; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [customer, setCustomer] = useState("");
  const [stage, setStage] = useState("Discovery");
  const [target, setTarget] = useState("");
  const { busy, err, run } = useMut(onRefresh);
  if (!open) return <button type="button" style={{ ...docActionBtn, marginTop: 4 }} data-testid="add-engagement-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add engagement</button>;
  const submit = () => { if (!sessionId || !title.trim()) return; run(async () => { await createEngagement(sessionId, { title: title.trim(), customer: customer.trim(), stage, targetDate: target }); setTitle(""); setCustomer(""); setTarget(""); setOpen(false); }); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") submit(); else if (e.key === "Escape") setOpen(false); };
  return (
    <div style={formCard} data-testid="add-engagement-form" onKeyDown={onKey}>
      <Field label="Title" grow><input autoFocus aria-label="Engagement title" placeholder="e.g. Contoso rollout" value={title} style={{ ...inputStyle, width: "100%", minWidth: 200 }} data-testid="engagement-title-input" onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label="Customer"><input aria-label="Customer" placeholder="e.g. Contoso" value={customer} style={{ ...inputStyle, width: 150 }} data-testid="engagement-customer-input" onChange={(e) => setCustomer(e.target.value)} /></Field>
      <Field label="Stage"><select aria-label="Stage" value={stage} style={selectStyle} data-testid="engagement-stage-select" onChange={(e) => setStage(e.target.value)}>{ENGAGEMENT_STAGES.map((s) => <option key={s}>{s}</option>)}</select></Field>
      <Field label="Target date" grow><input type="date" aria-label="Target date" value={target} style={{ ...inputStyle, width: "100%" }} data-testid="engagement-target-input" onChange={(e) => setTarget(e.target.value)} /></Field>
      <span style={{ display: "inline-flex", gap: 6 }}>
        <button type="button" style={title.trim() && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !title.trim()} data-testid="engagement-save-btn" onClick={submit}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
      </span>
      <FormErr msg={err} />
    </div>
  );
}

function EngagementDetailEditor({ engagement, sessionId, onRefresh, onNavigate }: { engagement: Engagement; sessionId: string | null; onRefresh: () => Promise<void>; onNavigate: (r: string) => void }) {
  const { busy, err, run } = useMut(onRefresh);
  const [saved, setSaved] = useState(false);
  const [armed, setArmed] = useState(false);
  // Health edits are coupled to the note: the server 422s an Amber/Red health without a
  // healthNote, so an Amber/Red pick is held locally until the note is non-empty, then both save together.
  const [pendingHealth, setPendingHealth] = useState<string | null>(null);
  const [note, setNote] = useState(engagement.healthNote || "");
  const [healthErr, setHealthErr] = useState<string | null>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  // Auto-save on change (no Save button); show a Saving…/Saved indicator instead of freezing the pane.
  const patch = (body: Partial<{ title: string; customer: string; stage: string; health: string; healthNote: string; startDate: string; targetDate: string; notes: string }>) => { if (sessionId) { setSaved(false); run(async () => { await updateEngagement(sessionId, engagement.id, body); setSaved(true); }); } };
  const saveHealth = (health: string, noteVal: string) => {
    if ((health === "amber" || health === "red") && !noteVal.trim()) {
      setHealthErr("Add a health note explaining why before saving an Amber or Red health.");
      return;
    }
    setHealthErr(null);
    if (sessionId) { setSaved(false); run(async () => { await updateEngagement(sessionId, engagement.id, health === "green" ? { health } : { health, healthNote: noteVal.trim() }); setPendingHealth(null); setSaved(true); }); }
  };
  // Transient "Saved ✓" — clear it a couple seconds after a save settles.
  useEffect(() => { if (!saved) return; const id = setTimeout(() => setSaved(false), 2200); return () => clearTimeout(id); }, [saved]);
  // Move focus to Confirm when the delete is armed (consistent with RowDelete/TaskDetailEditor).
  useEffect(() => { if (armed) confirmRef.current?.focus(); }, [armed]);
  return (
    <section className="tw-section" data-testid="engagement-edit">
      <h2 className="tw-h2">Edit{" "}
        <span aria-live="polite" style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary,#676879)" }}>
          {busy ? "Saving…" : saved ? "Saved ✓" : ""}
        </span>
      </h2>
      <div style={{ ...formRow, gap: 14, alignItems: "flex-end" }}>
        <Field label="Title" grow><input aria-label="Engagement title" defaultValue={engagement.title} style={{ ...inputStyle, width: "100%", minWidth: 220 }} data-testid="eng-edit-title"
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== engagement.title) patch({ title: v }); }} /></Field>
        <Field label="Customer"><input aria-label="Customer" defaultValue={engagement.customer || ""} style={{ ...inputStyle, width: 150 }} data-testid="eng-edit-customer"
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v !== (engagement.customer || "")) patch({ customer: v }); }} /></Field>
        <Field label="Stage"><select value={engagement.stage} style={selectStyle} data-testid="eng-edit-stage" onChange={(e) => patch({ stage: e.target.value })}>{ENGAGEMENT_STAGES.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Health"><select value={pendingHealth ?? engagement.health} style={selectStyle} data-testid="eng-edit-health"
          onChange={(e) => { const v = e.target.value; setPendingHealth(v); saveHealth(v, note); }}>
          <option value="green">Green</option><option value="amber">Amber</option><option value="red">Red</option>
        </select></Field>
        <Field label="Health note" grow><input aria-label="Health note" placeholder="Required for Amber/Red" value={note} style={{ ...inputStyle, width: "100%", minWidth: 180 }} data-testid="eng-edit-health-note"
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onChange={(e) => setNote(e.target.value)}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (pendingHealth) { saveHealth(pendingHealth, v); return; }
            if (v === (engagement.healthNote || "")) return;
            if (!v && engagement.health !== "green") { setHealthErr("A health note is required while health is Amber or Red."); return; }
            setHealthErr(null);
            patch({ healthNote: v });
          }} /></Field>
        <Field label="Start date"><input type="date" value={(engagement.startDate || "").slice(0, 10)} style={inputStyle} data-testid="eng-edit-start" onChange={(e) => { if (e.target.value !== (engagement.startDate || "").slice(0, 10)) patch({ startDate: e.target.value }); }} /></Field>
        <Field label="Target date"><input type="date" value={(engagement.targetDate || "").slice(0, 10)} style={inputStyle} data-testid="eng-edit-target" onChange={(e) => { if (e.target.value !== (engagement.targetDate || "").slice(0, 10)) patch({ targetDate: e.target.value }); }} /></Field>
      </div>
      <div style={{ ...formRow, gap: 14, alignItems: "flex-end", marginTop: 10 }}>
        <Field label="Notes" grow><input aria-label="Notes" defaultValue={engagement.notes || ""} style={{ ...inputStyle, width: "100%", minWidth: 220 }} data-testid="eng-edit-notes"
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v !== (engagement.notes || "")) patch({ notes: v }); }} /></Field>
        {armed ? (
          <span style={{ marginLeft: "auto", display: "inline-flex", gap: 6, alignItems: "center" }}>
            <button ref={confirmRef} type="button" style={dangerBtn} data-testid="delete-engagement-confirm" disabled={busy}
              onClick={() => { if (sessionId) run(async () => { await deleteEngagement(sessionId, engagement.id); onNavigate("/engagements"); }); }}><Trash2 size={13} /> Confirm delete</button>
            <button type="button" style={docActionBtn} disabled={busy} onClick={() => setArmed(false)}>Cancel</button>
          </span>
        ) : (
          <button type="button" style={{ ...docActionBtn, marginLeft: "auto" }} data-testid="delete-engagement-btn" onClick={() => setArmed(true)}><Trash2 size={13} /> Delete engagement</button>
        )}
      </div>
      <FormErr msg={healthErr ?? err} />
    </section>
  );
}

function MilestoneSection({ engagement, sessionId, onRefresh, today }: { engagement: Engagement; sessionId: string | null; onRefresh: () => Promise<void>; today: string }) {
  const milestones = engagement.milestones ?? [];
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const { busy, err, run } = useMut(onRefresh);
  const setStatus = (id: string, status: string) => { if (sessionId) run(() => updateEngagementItem(sessionId, engagement.id, "milestones", id, { status })); };
  const add = () => { if (!sessionId || !title.trim()) return; run(async () => { await addEngagementItem(sessionId, engagement.id, "milestones", { title: title.trim(), dueDate: due }); setTitle(""); setDue(""); setOpen(false); }); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") add(); else if (e.key === "Escape") setOpen(false); };
  return (
    <section className="tw-section" data-testid="eng-milestones">
      <h2 className="tw-h2">Milestones <span className="tw-count">{milestones.length}</span></h2>
      {milestones.length === 0 ? <div className="tw-empty-sm">No milestones yet. Add one below.</div> : (
        <table className="tw-table" data-testid="eng-milestones-table">
          <thead><tr><th>Milestone</th><th>Status</th><th>Due</th><th></th></tr></thead>
          <tbody>
            {milestones.map((m) => (
              <tr key={m.id} data-testid={`eng-milestone-row-${m.id}`}>
                <td className="tw-td-title">{m.title}{m.notes && <span className="tw-td-sub">{m.notes}</span>}</td>
                <td>
                  <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                    <EngStatusBadge status={m.status} />
                    <select aria-label={`Status of ${m.title}`} value={m.status} style={selectStyle} data-testid={`eng-milestone-status-${m.id}`} disabled={busy} onChange={(e) => setStatus(m.id, e.target.value)}>
                      {["Planned", "In progress", "Done", "Slipped"].map((s) => <option key={s}>{s}</option>)}
                    </select>
                  </span>
                </td>
                <td>{m.dueDate ? dayLabel(m.dueDate.slice(0, 10), today) : "—"}</td>
                <td><RowDelete onDelete={() => deleteEngagementItem(sessionId!, engagement.id, "milestones", m.id)} onRefresh={onRefresh} testid={`eng-milestone-delete-${m.id}`} label={m.title} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!open ? (
        <button type="button" style={{ ...docActionBtn, marginTop: 8 }} data-testid="add-milestone-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add milestone</button>
      ) : (
        <div style={formCard} data-testid="add-milestone-form" onKeyDown={onKey}>
          <Field label="Title" grow><input autoFocus aria-label="Milestone title" placeholder="e.g. Design sign-off" value={title} style={{ ...inputStyle, width: "100%", minWidth: 200 }} data-testid="milestone-title-input" onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Due date"><input type="date" aria-label="Due date" value={due} style={inputStyle} data-testid="milestone-due-input" onChange={(e) => setDue(e.target.value)} /></Field>
          <span style={{ display: "inline-flex", gap: 6 }}>
            <button type="button" style={title.trim() && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !title.trim()} data-testid="milestone-save-btn" onClick={add}>{busy ? "Saving…" : "Save"}</button>
            <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
          </span>
        </div>
      )}
      <FormErr msg={err} />
    </section>
  );
}

function RiskSection({ engagement, sessionId, onRefresh }: { engagement: Engagement; sessionId: string | null; onRefresh: () => Promise<void> }) {
  const risks = engagement.risks ?? [];
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("Medium");
  const [owner, setOwner] = useState("");
  const [mitigation, setMitigation] = useState("");
  const { busy, err, run } = useMut(onRefresh);
  const setStatus = (id: string, status: string) => { if (sessionId) run(() => updateEngagementItem(sessionId, engagement.id, "risks", id, { status })); };
  const add = () => { if (!sessionId || !title.trim()) return; run(async () => { await addEngagementItem(sessionId, engagement.id, "risks", { title: title.trim(), severity, owner: owner.trim(), notes: mitigation.trim() }); setTitle(""); setOwner(""); setMitigation(""); setOpen(false); }); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") add(); else if (e.key === "Escape") setOpen(false); };
  return (
    <section className="tw-section" data-testid="eng-risks">
      <h2 className="tw-h2">Risks <span className="tw-count">{risks.length}</span></h2>
      {risks.length === 0 ? <div className="tw-empty-sm">No risks logged. Add one below.</div> : (
        <table className="tw-table" data-testid="eng-risks-table">
          <thead><tr><th>Risk</th><th>Severity</th><th>Status</th><th>Owner</th><th>Mitigation</th><th></th></tr></thead>
          <tbody>
            {risks.map((r) => (
              <tr key={r.id} data-testid={`eng-risk-row-${r.id}`}>
                <td className="tw-td-title">{r.title}</td>
                <td><PriorityBadge priority={r.severity} /></td>
                <td>
                  <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                    <EngStatusBadge status={r.status} />
                    <select aria-label={`Status of ${r.title}`} value={r.status} style={selectStyle} data-testid={`eng-risk-status-${r.id}`} disabled={busy} onChange={(e) => setStatus(r.id, e.target.value)}>
                      {["Open", "Mitigating", "Closed"].map((s) => <option key={s}>{s}</option>)}
                    </select>
                  </span>
                </td>
                <td>{r.owner || "—"}</td>
                <td>{r.mitigation || "—"}</td>
                <td><RowDelete onDelete={() => deleteEngagementItem(sessionId!, engagement.id, "risks", r.id)} onRefresh={onRefresh} testid={`eng-risk-delete-${r.id}`} label={r.title} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!open ? (
        <button type="button" style={{ ...docActionBtn, marginTop: 8 }} data-testid="add-risk-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add risk</button>
      ) : (
        <div style={formCard} data-testid="add-risk-form" onKeyDown={onKey}>
          <Field label="Title" grow><input autoFocus aria-label="Risk title" placeholder="e.g. Data migration slips" value={title} style={{ ...inputStyle, width: "100%", minWidth: 200 }} data-testid="risk-title-input" onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Severity"><select aria-label="Severity" value={severity} style={selectStyle} data-testid="risk-severity-select" onChange={(e) => setSeverity(e.target.value)}>{["Low", "Medium", "High"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Owner"><input aria-label="Owner" placeholder="e.g. Dan" value={owner} style={{ ...inputStyle, width: 130 }} data-testid="risk-owner-input" onChange={(e) => setOwner(e.target.value)} /></Field>
          <Field label="Mitigation" grow><input aria-label="Mitigation" placeholder="How it's being handled" value={mitigation} style={{ ...inputStyle, width: "100%", minWidth: 180 }} data-testid="risk-mitigation-input" onChange={(e) => setMitigation(e.target.value)} /></Field>
          <span style={{ display: "inline-flex", gap: 6 }}>
            <button type="button" style={title.trim() && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !title.trim()} data-testid="risk-save-btn" onClick={add}>{busy ? "Saving…" : "Save"}</button>
            <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
          </span>
        </div>
      )}
      <FormErr msg={err} />
    </section>
  );
}

function ActionSection({ engagement, sessionId, onRefresh, today }: { engagement: Engagement; sessionId: string | null; onRefresh: () => Promise<void>; today: string }) {
  const actions = engagement.actions ?? [];
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const { busy, err, run } = useMut(onRefresh);
  const setStatus = (id: string, status: string) => { if (sessionId) run(() => updateEngagementItem(sessionId, engagement.id, "actions", id, { status })); };
  const add = () => { if (!sessionId || !title.trim()) return; run(async () => { await addEngagementItem(sessionId, engagement.id, "actions", { title: title.trim(), owner: owner.trim(), dueDate: due }); setTitle(""); setOwner(""); setDue(""); setOpen(false); }); };
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Enter") add(); else if (e.key === "Escape") setOpen(false); };
  return (
    <section className="tw-section" data-testid="eng-actions">
      <h2 className="tw-h2">Actions <span className="tw-count">{actions.length}</span></h2>
      {actions.length === 0 ? <div className="tw-empty-sm">No action items yet. Add one below.</div> : (
        <table className="tw-table" data-testid="eng-actions-table">
          <thead><tr><th>Action</th><th>Owner</th><th>Due</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {actions.map((a) => (
              <tr key={a.id} data-testid={`eng-action-row-${a.id}`}>
                <td className="tw-td-title">{a.title}{a.notes && <span className="tw-td-sub">{a.notes}</span>}</td>
                <td>{a.owner || "—"}</td>
                <td>{a.dueDate ? dayLabel(a.dueDate.slice(0, 10), today) : "—"}</td>
                <td>
                  <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                    <EngStatusBadge status={a.status} />
                    <select aria-label={`Status of ${a.title}`} value={a.status} style={selectStyle} data-testid={`eng-action-status-${a.id}`} disabled={busy} onChange={(e) => setStatus(a.id, e.target.value)}>
                      {["Open", "Done"].map((s) => <option key={s}>{s}</option>)}
                    </select>
                  </span>
                </td>
                <td><RowDelete onDelete={() => deleteEngagementItem(sessionId!, engagement.id, "actions", a.id)} onRefresh={onRefresh} testid={`eng-action-delete-${a.id}`} label={a.title} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!open ? (
        <button type="button" style={{ ...docActionBtn, marginTop: 8 }} data-testid="add-action-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add action</button>
      ) : (
        <div style={formCard} data-testid="add-action-form" onKeyDown={onKey}>
          <Field label="Title" grow><input autoFocus aria-label="Action title" placeholder="e.g. Send revised SOW" value={title} style={{ ...inputStyle, width: "100%", minWidth: 200 }} data-testid="action-title-input" onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Owner"><input aria-label="Owner" placeholder="e.g. Dan" value={owner} style={{ ...inputStyle, width: 130 }} data-testid="action-owner-input" onChange={(e) => setOwner(e.target.value)} /></Field>
          <Field label="Due date"><input type="date" aria-label="Due date" value={due} style={inputStyle} data-testid="action-due-input" onChange={(e) => setDue(e.target.value)} /></Field>
          <span style={{ display: "inline-flex", gap: 6 }}>
            <button type="button" style={title.trim() && !busy ? primaryBtn : primaryBtnOff} disabled={busy || !title.trim()} data-testid="action-save-btn" onClick={add}>{busy ? "Saving…" : "Save"}</button>
            <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
          </span>
        </div>
      )}
      <FormErr msg={err} />
    </section>
  );
}
