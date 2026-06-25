"use client";

import { useEffect, useRef, useState } from "react";
import {
  FileText, CheckCircle2, Circle, ArrowLeft, Home as HomeIcon, AlertTriangle, Calendar as CalendarIcon, Clock,
  BookMarked, Trash2, Upload, Plus,
} from "lucide-react";
import type { AppFile, AppState, Task, CalendarEvent, Schedule, LibraryDoc } from "@/lib/types";
import { getFileContent, getLibraryContent,
  createTask, updateTask, deleteTask, addSubtask, toggleSubtask,
  createEvent, deleteEvent, createSchedule, updateSchedule, deleteSchedule } from "@/lib/api";
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

export default function WorkbenchApp({
  appState, loading, viewRoute, onNavigate, sessionId, uploadedFiles, generatedFiles, newRecordIds, agentWorking,
  onSaveToLibrary, onRemoveFromLibrary, onUpload, onRefresh,
}: WorkbenchAppProps) {
  const [doc, setDoc] = useState<{ filename: string; content: string; mime?: string; loading: boolean; error: string | null } | null>(null);
  const [pulse, setPulse] = useState(false);
  const prevRoute = useRef(viewRoute);

  // Briefly pulse the app header when the view changes (e.g. agent navigation) so
  // it's obvious the pane moved.
  useEffect(() => {
    if (prevRoute.current !== viewRoute) {
      prevRoute.current = viewRoute;
      setPulse(true);
      const id = setTimeout(() => setPulse(false), 1100);
      return () => clearTimeout(id);
    }
  }, [viewRoute]);

  // Leaving the Documents view closes any open document so returning shows the
  // list, not a stale previously-opened doc.
  useEffect(() => {
    if (viewRoute !== "/documents") setDoc(null);
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
    trail = `To-Do  ›  ${t?.title ?? ""}`;
  } else if (viewRoute === "/todo") trail = "To-Do";
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
  // Fire-and-refresh helper for row-level deletes (no per-row hooks needed).
  const mutate = (fn: () => Promise<unknown>) => { void (async () => { await fn(); await onRefresh(); })(); };

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
          <Stat label="Group" value={t.group || "—"} />
          <Stat label="Due" value={t.dueDate || "—"} />
          <Stat label="Subtasks" value={`${done}/${subtasks.length}`} />
        </div>

        {t.notes && (
          <section className="tw-section">
            <h2 className="tw-h2">Notes</h2>
            <div className="tw-doc"><p className="tw-subtle" style={{ margin: 0 }}>{t.notes}</p></div>
          </section>
        )}

        <TaskDetailEditor task={t} sessionId={sessionId} onRefresh={onRefresh} onNavigate={onNavigate} />
        <SubtaskEditor task={t} sessionId={sessionId} onRefresh={onRefresh} />
      </div>
    );
  }

  // ── To-Do (/todo) — tasks grouped by bucket ───────────────────────────────
  if (viewRoute === "/todo") {
    const overdueCount = tasks.filter((t) => isOverdue(t, today)).length;
    const groups = Array.from(new Set(tasks.map((t) => t.group || "Ungrouped")));
    return (
      <div className="tw-screen" data-testid="todo-screen">
        <div style={{ display: "flex", alignItems: "center" }}>
          <h1 className="tw-h1">To-Do</h1>
          <AddTaskBar sessionId={sessionId} onRefresh={onRefresh} />
        </div>
        <p className="tw-subtle">Your tasks, grouped by bucket.</p>
        <div className="tw-stats">
          <Stat label="Tasks" value={tasks.length} />
          <Stat label="Open" value={tasks.filter((t) => t.status !== "Done").length} />
          <Stat label="Overdue" value={overdueCount} />
        </div>
        {tasks.length === 0 ? (
          <section className="tw-section"><div className="tw-empty-sm">No tasks yet — use “Add task” above, or ask the assistant.</div></section>
        ) : (
          groups.map((group) => {
            const rows = tasks.filter((t) => (t.group || "Ungrouped") === group);
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
                          <td className="tw-td-title">{t.title}{isNew(t.id) && <span className="tw-new">New</span>}</td>
                          <td><StatusBadge status={t.status} /></td>
                          <td><PriorityBadge priority={t.priority} /></td>
                          <td className={`tw-td-mono ${overdue ? "tw-due-overdue" : ""}`} title={overdue ? "Overdue" : undefined}>{t.dueDate || "—"}</td>
                          <td className="tw-td-mono">{done}/{subtasks.length}</td>
                          <td onClick={(e) => e.stopPropagation()}><RowDelete onConfirm={() => mutate(() => deleteTask(sessionId!, t.id))} testid={`task-delete-${t.id}`} /></td>
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
      items.push({ kind: "task", id: t.id, date: t.dueDate.slice(0, 10), sort: "zz", title: t.title, meta: `Task due · ${t.group || "Ungrouped"}` });
    }
    const days = Array.from(new Set(items.map((i) => i.date))).sort();
    return (
      <div className="tw-screen" data-testid="calendar-screen">
        <div style={{ display: "flex", alignItems: "center" }}>
          <h1 className="tw-h1">Calendar</h1>
          <AddEventBar sessionId={sessionId} onRefresh={onRefresh} />
        </div>
        <p className="tw-subtle">Events and task deadlines, by day.</p>
        {items.length === 0 ? (
          <section className="tw-section"><div className="tw-empty-sm">Nothing scheduled. Ask the assistant to add an event.</div></section>
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
                      style={i.kind === "task" ? undefined : { cursor: "default" }}
                    >
                      {i.kind === "event" ? <Clock size={15} /> : <CheckSquareDot />}
                      <span className="flex flex-col min-w-0">
                        <span className="tw-td-title">{i.title}</span>
                        <span className="tw-td-sub">{i.meta}</span>
                      </span>
                      {i.kind === "event" && <span style={{ marginLeft: "auto" }}><RowDelete onConfirm={() => mutate(() => deleteEvent(sessionId!, i.id))} testid={`event-delete-${i.id}`} /></span>}
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
        <div style={{ display: "flex", alignItems: "center" }}>
          <h1 className="tw-h1">Reminders</h1>
          <AddReminderBar sessionId={sessionId} onRefresh={onRefresh} />
        </div>
        <p className="tw-subtle">Scheduled prompts that run on a cadence and email you the result.</p>
        {schedules.length === 0 ? (
          <section className="tw-section"><div className="tw-empty-sm">No reminders yet — use “Add reminder” above, or ask the assistant.</div></section>
        ) : (
          <section className="tw-section">
            <table className="tw-table" data-testid="reminders-table">
              <thead><tr><th>Reminder</th><th>Cadence</th><th>Next run</th><th>Last run</th><th>Status</th><th></th></tr></thead>
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
      <p className="tw-subtle">Today&apos;s agenda — {dayLabel(today, today)}.</p>
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
                  <td className="tw-td-title">{t.title}</td>
                  <td>{t.group || "—"}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="tw-td-mono">{t.dueDate}</td>
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
                  <td className="tw-td-title">{t.title}</td>
                  <td>{t.group || "—"}</td>
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

function Stat({ label, value }: { label: string; value: number | string }) {
  return <div className="tw-stat"><div className="tw-stat-value">{value}</div><div className="tw-stat-label">{label}</div></div>;
}

const docActionBtn: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, fontWeight: 700,
  padding: "4px 10px", borderRadius: 8, border: "1px solid var(--border-subtle, #e5e7eb)",
  background: "var(--surface-1, #fff)", color: "var(--text-secondary, #444)", cursor: "pointer", whiteSpace: "nowrap",
};
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
              <button type="button" style={docActionBtn} title="Remove from Library" data-testid={`lib-remove-${d.filename}`}
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
const fieldStyle: React.CSSProperties = {
  fontSize: 12, padding: "5px 8px", borderRadius: 7,
  border: "1px solid var(--border-subtle, #e5e7eb)", background: "var(--surface-1, #fff)", color: "inherit",
};
const formRow: React.CSSProperties = { display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap" };

function useMut(onRefresh: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const run = (fn: () => Promise<unknown>) => {
    setBusy(true);
    void (async () => { try { await fn(); await onRefresh(); } finally { setBusy(false); } })();
  };
  return { busy, run };
}

function AddTaskBar({ sessionId, onRefresh }: { sessionId: string | null; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("Medium");
  const [group, setGroup] = useState("General");
  const [due, setDue] = useState("");
  const { busy, run } = useMut(onRefresh);
  if (!open) return <button type="button" style={{ ...docActionBtn, marginLeft: 10 }} data-testid="add-task-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add task</button>;
  const submit = () => { if (!sessionId || !title.trim()) return; run(async () => { await createTask(sessionId, { title: title.trim(), priority, group: group.trim() || "General", dueDate: due }); setTitle(""); setDue(""); setOpen(false); }); };
  return (
    <span style={{ ...formRow, marginLeft: 10 }} data-testid="add-task-form">
      <input autoFocus placeholder="Task title" value={title} style={{ ...fieldStyle, minWidth: 170 }} data-testid="task-title-input" onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
      <select value={priority} style={fieldStyle} data-testid="task-priority-select" onChange={(e) => setPriority(e.target.value)}>{["Low", "Medium", "High"].map((p) => <option key={p}>{p}</option>)}</select>
      <input placeholder="Group" value={group} style={{ ...fieldStyle, width: 90 }} onChange={(e) => setGroup(e.target.value)} />
      <input type="date" value={due} style={fieldStyle} data-testid="task-due-input" onChange={(e) => setDue(e.target.value)} />
      <button type="button" style={{ ...docActionBtn, opacity: title.trim() ? 1 : 0.5 }} disabled={busy || !title.trim()} data-testid="task-save-btn" onClick={submit}>{busy ? "…" : "Save"}</button>
      <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
    </span>
  );
}

function RowDelete({ onConfirm, testid }: { onConfirm: () => void; testid: string }) {
  return <button type="button" style={{ ...docActionBtn, padding: "3px 7px" }} title="Delete" data-testid={testid}
    onClick={(e) => { e.stopPropagation(); onConfirm(); }}><Trash2 size={13} /></button>;
}

function TaskDetailEditor({ task, sessionId, onRefresh, onNavigate }: { task: Task; sessionId: string | null; onRefresh: () => Promise<void>; onNavigate: (r: string) => void }) {
  const { busy, run } = useMut(onRefresh);
  const patch = (body: Partial<{ status: string; priority: string; dueDate: string }>) => { if (sessionId) run(() => updateTask(sessionId, task.id, body)); };
  return (
    <section className="tw-section" data-testid="task-edit">
      <h2 className="tw-h2">Edit</h2>
      <div style={{ ...formRow, gap: 10 }}>
        <label style={{ fontSize: 12, color: "var(--text-secondary,#555)" }}>Status{" "}
          <select value={task.status} style={fieldStyle} data-testid="edit-status" disabled={busy} onChange={(e) => patch({ status: e.target.value })}>{["To do", "In progress", "Blocked", "Done"].map((s) => <option key={s}>{s}</option>)}</select>
        </label>
        <label style={{ fontSize: 12, color: "var(--text-secondary,#555)" }}>Priority{" "}
          <select value={task.priority} style={fieldStyle} data-testid="edit-priority" disabled={busy} onChange={(e) => patch({ priority: e.target.value })}>{["Low", "Medium", "High"].map((p) => <option key={p}>{p}</option>)}</select>
        </label>
        <label style={{ fontSize: 12, color: "var(--text-secondary,#555)" }}>Due{" "}
          <input type="date" value={task.dueDate || ""} style={fieldStyle} data-testid="edit-due" disabled={busy} onChange={(e) => patch({ dueDate: e.target.value })} />
        </label>
        <button type="button" style={{ ...docActionBtn, marginLeft: "auto" }} data-testid="delete-task-btn" disabled={busy}
          onClick={() => { if (sessionId) run(async () => { await deleteTask(sessionId, task.id); onNavigate("/todo"); }); }}><Trash2 size={13} /> Delete task</button>
      </div>
    </section>
  );
}

function SubtaskEditor({ task, sessionId, onRefresh }: { task: Task; sessionId: string | null; onRefresh: () => Promise<void> }) {
  const subtasks = task.subtasks ?? [];
  const [text, setText] = useState("");
  const { busy, run } = useMut(onRefresh);
  const add = () => { if (sessionId && text.trim()) run(async () => { await addSubtask(sessionId, task.id, text.trim()); setText(""); }); };
  return (
    <section className="tw-section">
      <h2 className="tw-h2">Subtasks <span className="tw-count">{subtasks.length}</span></h2>
      {subtasks.length > 0 && (
        <div className="tw-doclist" data-testid="task-subtasks">
          {subtasks.map((c, i) => (
            <div key={i} className="tw-docitem" data-testid={`subtask-${i}`} style={{ cursor: "pointer" }}
              onClick={() => { if (sessionId && !busy) run(() => toggleSubtask(sessionId, task.id, i, !c.done)); }} role="checkbox" aria-checked={c.done}>
              {c.done ? <CheckCircle2 size={15} className="text-green-500" /> : <Circle size={15} />}
              <span className={c.done ? "line-through opacity-60" : ""}>{c.text}</span>
            </div>
          ))}
        </div>
      )}
      <span style={{ ...formRow, marginTop: 8 }}>
        <input placeholder="Add a subtask…" value={text} style={{ ...fieldStyle, minWidth: 200 }} data-testid="subtask-input" onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }} />
        <button type="button" style={{ ...docActionBtn, opacity: text.trim() ? 1 : 0.5 }} disabled={busy || !text.trim()} data-testid="subtask-add-btn" onClick={add}><Plus size={13} /> Add</button>
      </span>
    </section>
  );
}

function AddEventBar({ sessionId, onRefresh }: { sessionId: string | null; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const { busy, run } = useMut(onRefresh);
  if (!open) return <button type="button" style={{ ...docActionBtn, marginLeft: 10 }} data-testid="add-event-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add event</button>;
  const ok = title.trim() && date;
  const submit = () => { if (!sessionId || !ok) return; run(async () => { await createEvent(sessionId, { title: title.trim(), date, start, end }); setTitle(""); setDate(""); setStart(""); setEnd(""); setOpen(false); }); };
  return (
    <span style={{ ...formRow, marginLeft: 10 }} data-testid="add-event-form">
      <input autoFocus placeholder="Event title" value={title} style={{ ...fieldStyle, minWidth: 160 }} data-testid="event-title-input" onChange={(e) => setTitle(e.target.value)} />
      <input type="date" value={date} style={fieldStyle} data-testid="event-date-input" onChange={(e) => setDate(e.target.value)} />
      <input type="time" value={start} style={fieldStyle} data-testid="event-start-input" onChange={(e) => setStart(e.target.value)} />
      <input type="time" value={end} style={fieldStyle} onChange={(e) => setEnd(e.target.value)} />
      <button type="button" style={{ ...docActionBtn, opacity: ok ? 1 : 0.5 }} disabled={busy || !ok} data-testid="event-save-btn" onClick={submit}>{busy ? "…" : "Save"}</button>
      <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
    </span>
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
  const { busy, run } = useMut(onRefresh);
  if (!open) return <button type="button" style={{ ...docActionBtn, marginLeft: 10 }} data-testid="add-reminder-btn" onClick={() => setOpen(true)}><Plus size={13} /> Add reminder</button>;
  const ok = title.trim() && prompt.trim() && time && (frequency === "daily" || days.length > 0);
  const submit = () => { if (!sessionId || !ok) return; run(async () => { await createSchedule(sessionId, { title: title.trim(), prompt: prompt.trim(), frequency, time, timezone: tz, daysOfWeek: frequency === "weekly" ? days : [] }); setOpen(false); }); };
  return (
    <div style={{ ...formRow, marginTop: 12, alignItems: "flex-start" }} data-testid="add-reminder-form">
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <input autoFocus placeholder="Reminder name" value={title} style={{ ...fieldStyle, minWidth: 240 }} data-testid="reminder-title-input" onChange={(e) => setTitle(e.target.value)} />
        <input placeholder="What should it do? (e.g. summarize what's due this week)" value={prompt} style={{ ...fieldStyle, minWidth: 320 }} data-testid="reminder-prompt-input" onChange={(e) => setPrompt(e.target.value)} />
        <span style={formRow}>
          <select value={frequency} style={fieldStyle} data-testid="reminder-frequency-select" onChange={(e) => setFrequency(e.target.value)}><option value="daily">Daily</option><option value="weekly">Weekly</option></select>
          <input type="time" value={time} style={fieldStyle} data-testid="reminder-time-input" onChange={(e) => setTime(e.target.value)} />
          <span style={{ fontSize: 11, color: "var(--text-secondary,#666)" }}>{tz}</span>
        </span>
        {frequency === "weekly" && (
          <span style={formRow} data-testid="reminder-days">
            {DAY_NAMES_UI.map((d, i) => (
              <button key={d} type="button" style={{ ...fieldStyle, padding: "3px 7px", background: days.includes(i) ? "var(--brand-primary,#2563eb)" : "var(--surface-1,#fff)", color: days.includes(i) ? "#fff" : "inherit" }}
                onClick={() => setDays((cur) => cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i])}>{d}</button>
            ))}
          </span>
        )}
        <span style={formRow}>
          <button type="button" style={{ ...docActionBtn, opacity: ok ? 1 : 0.5 }} disabled={busy || !ok} data-testid="reminder-save-btn" onClick={submit}>{busy ? "…" : "Save reminder"}</button>
          <button type="button" style={docActionBtn} onClick={() => setOpen(false)}>Cancel</button>
        </span>
      </div>
    </div>
  );
}

function ReminderActions({ schedule, sessionId, onRefresh }: { schedule: Schedule; sessionId: string | null; onRefresh: () => Promise<void> }) {
  const { busy, run } = useMut(onRefresh);
  return (
    <span style={{ ...formRow, gap: 6 }}>
      <button type="button" style={docActionBtn} data-testid={`reminder-toggle-${schedule.id}`} disabled={busy}
        onClick={() => { if (sessionId) run(() => updateSchedule(sessionId, schedule.id, { enabled: !schedule.enabled })); }}>{schedule.enabled ? "Pause" : "Resume"}</button>
      <button type="button" style={docActionBtn} title="Delete" data-testid={`reminder-delete-${schedule.id}`} disabled={busy}
        onClick={() => { if (sessionId) run(() => deleteSchedule(sessionId, schedule.id)); }}><Trash2 size={13} /></button>
    </span>
  );
}
