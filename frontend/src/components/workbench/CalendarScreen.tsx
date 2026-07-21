"use client";

import { useState } from "react";
import { AlertTriangle, Calendar as CalendarIcon, CheckCircle2, Clock, Plus } from "lucide-react";
import type { AppState, CalendarEvent, Task } from "@/lib/types";
import { createEvent, deleteEvent } from "@/lib/api";
import { ArmedDelete, dayLabel, usePersonalAction } from "./PersonalWorkspaceUI";

type AgendaItem = { kind: "event" | "task"; id: string; date: string; sort: string; title: string; meta: string };

function buildAgenda(events: CalendarEvent[], tasks: Task[]): AgendaItem[] {
  const items: AgendaItem[] = [];
  for (const event of events) {
    if (!event.date) continue;
    items.push({
      kind: "event", id: event.id, date: event.date.slice(0, 10), sort: event.start || "00:00",
      title: event.title, meta: `${event.type || "Event"}${event.start ? ` · ${event.start}${event.end ? `–${event.end}` : ""}` : ""}`,
    });
  }
  for (const task of tasks) {
    if (!task.dueDate || task.status === "Done") continue;
    items.push({ kind: "task", id: task.id, date: task.dueDate.slice(0, 10), sort: "zz", title: task.title, meta: `Task due · ${task.group || "General"}` });
  }
  return items;
}

export default function CalendarScreen({ appState, sessionId, onNavigate, onRefresh }: {
  appState: AppState; sessionId: string | null; onNavigate: (route: string) => void; onRefresh: () => Promise<void>;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const events = appState.calendarEvents ?? [];
  const tasks = appState.personalTasks ?? [];
  const items = buildAgenda(events, tasks);
  const days = Array.from(new Set(items.map((item) => item.date))).sort();
  const { error, run } = usePersonalAction(onRefresh);

  return (
    <div className="tw-screen" data-testid="calendar-screen">
      <h1 className="tw-h1">Calendar</h1>
      <p className="tw-subtle">Events and task deadlines, by day.</p>
      <AddEventBar sessionId={sessionId} onRefresh={onRefresh} />
      {error && <p className="tw-error" role="alert">{error}</p>}
      {items.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">Nothing scheduled yet. Add an event above, or ask the assistant.</div></section>
      ) : (
        days.map((day) => {
          const dayItems = items.filter((item) => item.date === day).sort((a, b) => (a.sort < b.sort ? -1 : 1));
          return (
            <section className="tw-section" key={day} data-testid={`calendar-day-${day}`}>
              <h2 className="tw-h2"><CalendarIcon size={14} /> {dayLabel(day, today)} <span className="tw-count">{dayItems.length}</span></h2>
              <div className="tw-doclist">
                {dayItems.map((item) => (
                  <div
                    key={`${item.kind}-${item.id}`}
                    className={`tw-docitem ${item.kind === "task" ? "tw-rowlink" : ""}`}
                    data-testid={`agenda-${item.kind}-${item.id}`}
                    onClick={item.kind === "task" ? () => onNavigate(`/todo/${item.id}`) : undefined}
                    onKeyDown={item.kind === "task" ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onNavigate(`/todo/${item.id}`); } } : undefined}
                    role={item.kind === "task" ? "button" : undefined}
                    tabIndex={item.kind === "task" ? 0 : undefined}
                    style={item.kind === "event" ? { cursor: "default" } : undefined}
                  >
                    {item.kind === "event" ? <Clock size={15} /> : <CheckCircle2 size={15} className="text-green-500" />}
                    <span className="flex flex-col min-w-0 flex-1">
                      <span className="tw-td-title">{item.title}</span>
                      <span className="tw-td-sub">{item.meta}</span>
                    </span>
                    {item.kind === "event" && (
                      <span onClick={(event) => event.stopPropagation()}>
                        <ArmedDelete testid={`event-delete-${item.id}`} label={item.title} onConfirm={() => void run(() => deleteEvent(sessionId!, item.id))} />
                      </span>
                    )}
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

function AddEventBar({ sessionId, onRefresh }: { sessionId: string | null; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const { busy, error, run } = usePersonalAction(onRefresh);

  if (!open) {
    return <button type="button" className="tw-addbar" data-testid="add-event-btn" onClick={() => setOpen(true)}><Plus size={14} /> Add event</button>;
  }

  const timeBad = !!(start && end && end <= start);
  const ok = !!(title.trim() && date && !timeBad);
  const submit = () => {
    if (!sessionId || !ok) return;
    void run(async () => {
      await createEvent(sessionId, { title: title.trim(), date, start, end });
      setTitle(""); setDate(""); setStart(""); setEnd(""); setOpen(false);
    });
  };

  return (
    <div className="tw-addform" data-testid="add-event-form" onKeyDown={(event) => { if (event.key === "Enter") submit(); else if (event.key === "Escape") setOpen(false); }}>
      <label>
        Title
        <input autoFocus className="tw-input" placeholder="e.g. Northstar sync" value={title} data-testid="event-title-input" onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>
        Date
        <input type="date" className="tw-input" value={date} data-testid="event-date-input" onChange={(event) => setDate(event.target.value)} />
      </label>
      <label>
        Start
        <input type="time" className="tw-input" value={start} data-testid="event-start-input" onChange={(event) => setStart(event.target.value)} />
      </label>
      <label>
        End
        <input type="time" className="tw-input" value={end} data-testid="event-end-input" onChange={(event) => setEnd(event.target.value)} />
      </label>
      <div className="tw-form-actions">
        <button type="button" className="tw-btn" disabled={busy || !ok} data-testid="event-save-btn" onClick={submit}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" className="tw-btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {timeBad && <p className="tw-td-sub">End must be after start.</p>}
      {error && <p className="tw-error" role="alert"><AlertTriangle size={13} strokeWidth={2.5} /> {error}</p>}
    </div>
  );
}
