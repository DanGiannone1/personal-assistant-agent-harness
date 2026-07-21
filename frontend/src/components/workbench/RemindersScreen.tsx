"use client";

import { useState } from "react";
import { AlertTriangle, Plus } from "lucide-react";
import type { AppState, Reminder, ReminderFrequency } from "@/lib/types";
import { createReminder, deleteReminder, updateReminder } from "@/lib/api";
import { ArmedDelete, usePersonalAction } from "./PersonalWorkspaceUI";

// daysOfWeek matches the backend cadence math: 0=Mon .. 6=Sun (Python weekday()).
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function cadence(reminder: Reminder): string {
  const tz = reminder.timezone || "UTC";
  if (reminder.frequency === "weekly") {
    const days = (reminder.daysOfWeek ?? []).slice().sort((a, b) => a - b).map((day) => DAY_NAMES[day]).join(", ");
    return `Weekly on ${days || "—"} at ${reminder.time} (${tz})`;
  }
  if (reminder.frequency === "once") return `Once on ${reminder.dueDate} at ${reminder.time} (${tz})`;
  return `Daily at ${reminder.time} (${tz})`;
}

function when(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function deliveryStatus(reminder: Reminder): string {
  if (!reminder.enabled) return "Paused";
  if (!reminder.lastStatus) return reminder.nextDueAt ? "Scheduled" : "—";
  return reminder.lastStatus;
}

export default function RemindersScreen({ appState, sessionId, onRefresh }: {
  appState: AppState; sessionId: string | null; onRefresh: () => Promise<void>;
}) {
  const reminders = appState.reminders ?? [];
  const { error, run } = usePersonalAction(onRefresh);

  return (
    <div className="tw-screen" data-testid="reminders-screen">
      <h1 className="tw-h1">Reminders</h1>
      <p className="tw-subtle">Recurring reminders, emailed to you on the schedule you set.</p>
      <AddReminderBar sessionId={sessionId} onRefresh={onRefresh} />
      {error && <p className="tw-error" role="alert">{error}</p>}
      {reminders.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">No reminders yet. Add one above, or ask the assistant.</div></section>
      ) : (
        <section className="tw-section">
          <table className="tw-table" data-testid="reminders-table">
            <thead><tr><th>Reminder</th><th>Repeats</th><th>Next</th><th>Last delivery</th><th></th><th></th></tr></thead>
            <tbody>
              {reminders.map((reminder) => (
                <tr key={reminder.id} data-testid={`reminder-row-${reminder.id}`}>
                  <td className="tw-td-title">
                    {reminder.title}
                    {reminder.message && <span className="tw-td-sub" style={{ display: "block" }}>{reminder.message}</span>}
                  </td>
                  <td>{cadence(reminder)}</td>
                  <td className="tw-td-mono">{when(reminder.nextDueAt)}</td>
                  <td>
                    <span className="tw-td-sub">{deliveryStatus(reminder)}</span>
                    {reminder.lastSentAt && <span className="tw-td-mono tw-td-sub" style={{ display: "block" }}>{when(reminder.lastSentAt)}</span>}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="tw-btn-ghost"
                      aria-label={reminder.enabled ? `Pause ${reminder.title}` : `Resume ${reminder.title}`}
                      data-testid={`reminder-toggle-${reminder.id}`}
                      onClick={() => void run(() => updateReminder(sessionId!, reminder.id, { enabled: !reminder.enabled }))}
                    >
                      {reminder.enabled ? "Pause" : "Resume"}
                    </button>
                  </td>
                  <td>
                    <ArmedDelete
                      testid={`reminder-delete-${reminder.id}`}
                      label={reminder.title}
                      onConfirm={() => void run(() => deleteReminder(sessionId!, reminder.id))}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function AddReminderBar({ sessionId, onRefresh }: { sessionId: string | null; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [frequency, setFrequency] = useState<ReminderFrequency>("daily");
  const [dueDate, setDueDate] = useState("");
  const [time, setTime] = useState("08:00");
  const [days, setDays] = useState<number[]>([]);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const { busy, error, run } = usePersonalAction(onRefresh);

  if (!open) {
    return <button type="button" className="tw-addbar" data-testid="add-reminder-btn" onClick={() => setOpen(true)}><Plus size={14} /> Add reminder</button>;
  }

  const needsDay = frequency === "weekly" && days.length === 0;
  const ok = !!(title.trim() && dueDate && time && !needsDay);
  const submit = () => {
    if (!sessionId || !ok) return;
    void run(async () => {
      await createReminder(sessionId, {
        title: title.trim(), message: message.trim(), frequency, dueDate, time, timezone: tz,
        daysOfWeek: frequency === "weekly" ? days : [],
      });
      setTitle(""); setMessage(""); setDueDate(""); setDays([]); setOpen(false);
    });
  };

  return (
    <div className="tw-addform" data-testid="add-reminder-form" onKeyDown={(event) => { if (event.key === "Enter" && event.target instanceof HTMLInputElement) submit(); else if (event.key === "Escape") setOpen(false); }}>
      <label>
        Name
        <input autoFocus className="tw-input" placeholder="e.g. Weekly digest" value={title} data-testid="reminder-title-input" onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>
        Message <span className="tw-optional">optional</span>
        <input className="tw-input" placeholder="What should the email say?" value={message} data-testid="reminder-message-input" onChange={(event) => setMessage(event.target.value)} />
      </label>
      <label>
        Repeats
        <select className="tw-input" value={frequency} data-testid="reminder-frequency-select" onChange={(event) => setFrequency(event.target.value as ReminderFrequency)}>
          <option value="once">Once</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
        </select>
      </label>
      <label>
        Date
        <input type="date" className="tw-input" value={dueDate} data-testid="reminder-date-input" onChange={(event) => setDueDate(event.target.value)} />
      </label>
      <label>
        {`Time (${tz})`}
        <input type="time" className="tw-input" value={time} data-testid="reminder-time-input" onChange={(event) => setTime(event.target.value)} />
      </label>
      {frequency === "weekly" && (
        <div className="tw-form-actions" data-testid="reminder-days" role="group" aria-label="Days of week">
          {DAY_NAMES.map((label, index) => {
            const dayValue = index;
            const on = days.includes(dayValue);
            return (
              <button
                key={label}
                type="button"
                aria-pressed={on}
                className={on ? "tw-btn" : "tw-btn-ghost"}
                onClick={() => setDays((current) => (current.includes(dayValue) ? current.filter((value) => value !== dayValue) : [...current, dayValue]))}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
      <div className="tw-form-actions">
        <button type="button" className="tw-btn" disabled={busy || !ok} data-testid="reminder-save-btn" onClick={submit}>{busy ? "Saving…" : "Save reminder"}</button>
        <button type="button" className="tw-btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {needsDay && <p className="tw-td-sub">Pick at least one day.</p>}
      {error && <p className="tw-error" role="alert"><AlertTriangle size={13} strokeWidth={2.5} /> {error}</p>}
    </div>
  );
}
