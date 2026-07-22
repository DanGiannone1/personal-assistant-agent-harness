"use client";

import { ArrowRight, Clock } from "lucide-react";
import type { AppState } from "@/lib/types";
import { PriorityBadge, Stat, StatusBadge, absDate, dayLabel, isOverdue } from "./PersonalWorkspaceUI";
import { EngagementPortfolioRow } from "./EngagementScreens";

export default function HomeScreen({ appState, onNavigate }: {
  appState: AppState; onNavigate: (route: string) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const tasks = appState.personalTasks ?? [];
  const events = appState.calendarEvents ?? [];
  const reminders = appState.reminders ?? [];
  const engagements = appState.engagements ?? [];

  const openTasks = tasks.filter((task) => task.status !== "Done");
  const overdue = tasks.filter((task) => isOverdue(task, today));
  const dueToday = openTasks.filter((task) => (task.dueDate || "").slice(0, 10) === today);
  const eventsToday = events.filter((event) => (event.date || "").slice(0, 10) === today)
    .sort((a, b) => ((a.start || "") < (b.start || "") ? -1 : 1));
  const nextEvents = events.filter((event) => (event.date || "").slice(0, 10) >= today)
    .sort((a, b) => (`${a.date}${a.start || ""}` < `${b.date}${b.start || ""}` ? -1 : 1))
    .slice(0, 5);
  const activeReminders = reminders.filter((reminder) => reminder.enabled).length;

  return (
    <div className="tw-screen" data-testid="home-screen">
      <h1 className="tw-h1">{appState.user ? `Welcome back, ${appState.user.displayName}` : "Home"}</h1>
      <p className="tw-subtle">Today&apos;s agenda — {absDate(today)}.</p>

      {/* Engagements are the heart of the workbench, so Home leads with the portfolio
          (the same rows as the Engagements screen) before the personal agenda below. */}
      <section className="tw-section" data-testid="home-engagements">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <h2 className="tw-h2">Engagements <span className="tw-count">{engagements.length}</span></h2>
          <button type="button" className="tw-btn-ghost" data-testid="home-view-all-engagements" onClick={() => onNavigate("/engagements")}>
            View all <ArrowRight size={13} />
          </button>
        </div>
        {engagements.length === 0 ? (
          <div className="tw-empty-sm">
            No engagements yet.{" "}
            <button type="button" className="tw-btn-ghost" data-testid="home-create-engagement" onClick={() => onNavigate("/engagements")}>
              Create your first engagement <ArrowRight size={13} />
            </button>
          </div>
        ) : (
          <div className="tw-doclist tw-engagement-portfolio" data-testid="home-engagement-cards">
            {engagements.map((engagement) => (
              <EngagementPortfolioRow
                key={engagement.id}
                engagement={engagement}
                userId={appState.user?.id}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        )}
      </section>

      <section style={{ marginTop: 12 }} data-testid="home-quicklinks">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="tw-td-sub" style={{ fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", fontSize: 10.5 }}>Jump to</span>
          <button type="button" className="tw-chip" data-testid="quicklink--todo" onClick={() => onNavigate("/todo")}>Tasks</button>
          <button type="button" className="tw-chip" data-testid="quicklink--calendar" onClick={() => onNavigate("/calendar")}>Calendar</button>
          <button type="button" className="tw-chip" data-testid="quicklink--reminders" onClick={() => onNavigate("/reminders")}>Reminders</button>
        </div>
      </section>

      <div className="tw-stats">
        <Stat label="Tasks" value={tasks.length} />
        <Stat label="Open" value={openTasks.length} />
        <Stat label="Due today" value={dueToday.length} />
        <Stat label="Overdue" value={overdue.length} />
        <Stat label="Events today" value={eventsToday.length} />
        <Stat label="Active reminders" value={activeReminders} />
      </div>

      {overdue.length > 0 && (
        <section className="tw-section">
          <h2 className="tw-h2">Overdue <span className="tw-count">{overdue.length}</span></h2>
          <table className="tw-table" data-testid="overdue-table">
            <thead><tr><th>Task</th><th>Group</th><th>Status</th><th>Due</th></tr></thead>
            <tbody>
              {overdue.map((task) => (
                <tr key={task.id} className="tw-rowlink" data-testid={`overdue-row-${task.id}`} onClick={() => onNavigate(`/todo/${task.id}`)}>
                  <td className="tw-td-title">{task.title}</td>
                  <td>{task.group || "General"}</td>
                  <td><StatusBadge status={task.status} /></td>
                  <td className="tw-due-overdue">{task.dueDate ? dayLabel(task.dueDate.slice(0, 10), today) : "—"}</td>
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
              {dueToday.map((task) => (
                <tr key={task.id} className="tw-rowlink" onClick={() => onNavigate(`/todo/${task.id}`)}>
                  <td className="tw-td-title">{task.title}</td>
                  <td>{task.group || "General"}</td>
                  <td><StatusBadge status={task.status} /></td>
                  <td><PriorityBadge priority={task.priority} /></td>
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
            {(eventsToday.length > 0 ? eventsToday : nextEvents).map((event) => (
              <div key={event.id} className="tw-docitem" style={{ cursor: "default" }} data-testid={`home-event-${event.id}`}>
                <Clock size={15} />
                <span className="flex flex-col min-w-0">
                  <span className="tw-td-title">{event.title}</span>
                  <span className="tw-td-sub">{dayLabel(event.date, today)}{event.start ? ` · ${event.start}${event.end ? `–${event.end}` : ""}` : ""}{event.type ? ` · ${event.type}` : ""}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
