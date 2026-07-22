"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Circle, Plus, Trash2 } from "lucide-react";
import type { AppState, Task, TaskPriority, TaskStatus } from "@/lib/types";
import { addSubtask, createTask, deleteSubtask, deleteTask, toggleSubtask, updateTask } from "@/lib/api";
import {
  ArmedDelete, OverdueBadge, PriorityBadge, Stat, StatusBadge, dayLabel, isOverdue, usePersonalAction,
} from "./PersonalWorkspaceUI";

const STATUSES: TaskStatus[] = ["To do", "In progress", "Blocked", "Done"];
const PRIORITIES: TaskPriority[] = ["Low", "Medium", "High"];

function groupsOf(tasks: Task[]): string[] {
  return Array.from(new Set(tasks.map((task) => task.group || "General")));
}

export default function TasksScreen({ appState, viewRoute, sessionId, onNavigate, onRefresh }: {
  appState: AppState;
  viewRoute: string;
  sessionId: string | null;
  onNavigate: (route: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const tasks = appState.personalTasks ?? [];
  const recordId = viewRoute.startsWith("/todo/") ? viewRoute.slice("/todo/".length) : null;

  if (recordId) {
    const task = tasks.find((candidate) => candidate.id === recordId);
    return (
      <div className="tw-screen" data-testid="task-detail">
        <button type="button" className="tw-back" onClick={() => onNavigate("/todo")}>
          <ArrowLeft size={14} /> All tasks
        </button>
        {!task ? (
          <div className="tw-empty-sm">Task not found.</div>
        ) : (
          <TaskDetail
            task={task}
            sessionId={sessionId}
            groups={groupsOf(tasks)}
            onNavigate={onNavigate}
            onRefresh={onRefresh}
          />
        )}
      </div>
    );
  }

  return <TasksList tasks={tasks} sessionId={sessionId} onNavigate={onNavigate} onRefresh={onRefresh} />;
}

function TasksList({ tasks, sessionId, onNavigate, onRefresh }: {
  tasks: Task[]; sessionId: string | null; onNavigate: (route: string) => void; onRefresh: () => Promise<void>;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const groups = groupsOf(tasks);
  const { error, run } = usePersonalAction(onRefresh);

  return (
    <div className="tw-screen" data-testid="todo-screen">
      <h1 className="tw-h1">Tasks</h1>
      <p className="tw-subtle">Your tasks, grouped.</p>
      <div className="tw-stats">
        <Stat label="Tasks" value={tasks.length} />
        <Stat label="Open" value={tasks.filter((task) => task.status !== "Done").length} />
        <Stat label="Due today" value={tasks.filter((task) => task.status !== "Done" && (task.dueDate || "").slice(0, 10) === today).length} />
        <Stat label="Overdue" value={tasks.filter((task) => isOverdue(task, today)).length} />
      </div>
      <AddTaskBar sessionId={sessionId} groups={groups} onRefresh={onRefresh} />
      {error && <p className="tw-error" role="alert">{error}</p>}
      {tasks.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">No tasks yet. Add one above, or ask the assistant.</div></section>
      ) : (
        groups.map((group) => {
          const rows = tasks.filter((task) => (task.group || "General") === group);
          return (
            <section className="tw-section" key={group} data-testid={`todo-group-${group}`}>
              <h2 className="tw-h2">{group} <span className="tw-count">{rows.length}</span></h2>
              <table className="tw-table" data-testid="tasks-table">
                <thead>
                  <tr><th>Task</th><th>Status</th><th>Priority</th><th>Due</th><th>Subtasks</th><th></th></tr>
                </thead>
                <tbody>
                  {rows.map((task) => {
                    const subtasks = task.subtasks ?? [];
                    const done = subtasks.filter((subtask) => subtask.done).length;
                    const overdue = isOverdue(task, today);
                    return (
                      <tr
                        key={task.id}
                        data-testid={`task-row-${task.id}`}
                        className="tw-rowlink"
                        onClick={() => onNavigate(`/todo/${task.id}`)}
                      >
                        <td className="tw-td-title">{task.title}</td>
                        <td><StatusBadge status={task.status} /></td>
                        <td><PriorityBadge priority={task.priority} /></td>
                        <td className={overdue ? "tw-due-overdue" : ""}>
                          {task.dueDate ? dayLabel(task.dueDate.slice(0, 10), today) : "—"}{overdue && <OverdueBadge />}
                        </td>
                        <td className="tw-td-mono">{done}/{subtasks.length}</td>
                        <td onClick={(event) => event.stopPropagation()}>
                          <ArmedDelete
                            testid={`task-delete-${task.id}`}
                            label={task.title}
                            onConfirm={() => void run(() => deleteTask(sessionId!, task.id))}
                          />
                        </td>
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

function AddTaskBar({ sessionId, groups, onRefresh }: { sessionId: string | null; groups: string[]; onRefresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [titleError, setTitleError] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("Medium");
  const [group, setGroup] = useState("General");
  const [dueDate, setDueDate] = useState("");
  const titleRef = useRef<HTMLInputElement>(null);
  const { busy, error, run } = usePersonalAction(onRefresh);

  if (!open) {
    return (
      <button type="button" className="tw-addbar" data-testid="add-task-btn" onClick={() => setOpen(true)}>
        <Plus size={14} /> Add task
      </button>
    );
  }

  const submit = () => {
    if (!title.trim()) {
      setTitleError("Enter a task title.");
      requestAnimationFrame(() => titleRef.current?.focus());
      return;
    }
    if (!sessionId) return;
    setTitleError("");
    void run(async () => {
      await createTask(sessionId, { title: title.trim(), priority, group: group.trim() || "General", dueDate });
      setTitle(""); setDueDate(""); setOpen(false);
    });
  };

  return (
    <div className="tw-addform" data-testid="add-task-form" onKeyDown={(event) => { if (event.key === "Enter") submit(); else if (event.key === "Escape") setOpen(false); }}>
      <label>
        Title
        <input
          ref={titleRef}
          autoFocus
          className="tw-input"
          placeholder="e.g. Draft the Q3 plan"
          value={title}
          data-testid="task-title-input"
          aria-invalid={!!titleError}
          aria-describedby={titleError ? "task-title-error" : undefined}
          onChange={(event) => { setTitle(event.target.value); if (titleError) setTitleError(""); }}
        />
      </label>
      <label>
        Priority
        <select className="tw-input" value={priority} data-testid="task-priority-select" onChange={(event) => setPriority(event.target.value as TaskPriority)}>
          {PRIORITIES.map((value) => <option key={value}>{value}</option>)}
        </select>
      </label>
      <label>
        Group
        <input className="tw-input" list="task-group-options" placeholder="General" value={group} onChange={(event) => setGroup(event.target.value)} />
        <datalist id="task-group-options">{groups.map((value) => <option key={value} value={value} />)}</datalist>
      </label>
      <label>
        Due date
        <input type="date" className="tw-input" value={dueDate} data-testid="task-due-input" onChange={(event) => setDueDate(event.target.value)} />
      </label>
      <div className="tw-form-actions">
        <button type="button" className="tw-btn" disabled={busy} data-testid="task-save-btn" onClick={submit}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" className="tw-btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {titleError && (
        <p id="task-title-error" className="tw-error" role="alert">
          <AlertTriangle size={13} strokeWidth={2.5} /> {titleError}
        </p>
      )}
      {error && <p className="tw-error" role="alert">{error}</p>}
    </div>
  );
}

function TaskDetail({ task, sessionId, groups, onNavigate, onRefresh }: {
  task: Task; sessionId: string | null; groups: string[]; onNavigate: (route: string) => void; onRefresh: () => Promise<void>;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const subtasks = task.subtasks ?? [];
  const done = subtasks.filter((subtask) => subtask.done).length;
  const overdue = isOverdue(task, today);
  const { busy, error, run } = usePersonalAction(onRefresh);
  const [saved, setSaved] = useState(false);
  const [armed, setArmed] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const [subtaskText, setSubtaskText] = useState("");

  const patch = (body: Partial<{ title: string; status: string; priority: string; group: string; dueDate: string }>) => {
    if (!sessionId) return;
    setSaved(false);
    void run(async () => { await updateTask(sessionId, task.id, body); setSaved(true); });
  };
  useEffect(() => { if (!saved) return; const id = setTimeout(() => setSaved(false), 2200); return () => clearTimeout(id); }, [saved]);
  useEffect(() => { if (armed) confirmRef.current?.focus(); }, [armed]);

  return (
    <>
      <h1 className="tw-h1">{task.title}</h1>
      <div className="flex flex-wrap items-center gap-2 mt-1">
        <StatusBadge status={task.status} />
        <PriorityBadge priority={task.priority} />
        {overdue && <OverdueBadge />}
      </div>

      <div className="tw-stats">
        <Stat label="Group" value={task.group || "General"} />
        <Stat label="Due" value={task.dueDate ? dayLabel(task.dueDate.slice(0, 10), today) : "—"} />
        <Stat label="Subtasks" value={`${done}/${subtasks.length}`} />
      </div>

      {task.notes && (
        <section className="tw-section">
          <h2 className="tw-h2">Notes</h2>
          <div className="tw-doc"><p className="tw-subtle" style={{ margin: 0 }}>{task.notes}</p></div>
        </section>
      )}

      <section className="tw-section" data-testid="task-edit">
        <h2 className="tw-h2">
          Edit <span aria-live="polite" className="tw-td-sub">{busy ? "Saving…" : saved ? "Saved ✓" : ""}</span>
        </h2>
        <div className="tw-edit-grid">
          <label>
            Title
            <input
              className="tw-input"
              defaultValue={task.title}
              data-testid="edit-title"
              disabled={busy}
              onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }}
              onBlur={(event) => { const value = event.target.value.trim(); if (value && value !== task.title) patch({ title: value }); }}
            />
          </label>
          <label>
            Group
            <input
              className="tw-input"
              list="edit-group-options"
              defaultValue={task.group || ""}
              data-testid="edit-group"
              disabled={busy}
              onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }}
              onBlur={(event) => { const value = event.target.value.trim(); if (value !== (task.group || "")) patch({ group: value || "General" }); }}
            />
            <datalist id="edit-group-options">{groups.map((value) => <option key={value} value={value} />)}</datalist>
          </label>
          <label>
            Status
            <select className="tw-input" value={task.status} data-testid="edit-status" disabled={busy} onChange={(event) => patch({ status: event.target.value })}>
              {STATUSES.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>
            Priority
            <select className="tw-input" value={task.priority} data-testid="edit-priority" disabled={busy} onChange={(event) => patch({ priority: event.target.value })}>
              {PRIORITIES.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>
            Due date
            <input
              type="date"
              className="tw-input"
              value={task.dueDate || ""}
              data-testid="edit-due"
              disabled={busy}
              onChange={(event) => { if (event.target.value !== (task.dueDate || "")) patch({ dueDate: event.target.value }); }}
            />
          </label>
        </div>
        {error && <p className="tw-error" role="alert">{error}</p>}
        <div className="tw-form-actions">
          {armed ? (
            <span className="tw-confirm-actions">
              <button
                ref={confirmRef}
                type="button"
                className="tw-btn"
                data-testid="delete-task-confirm"
                disabled={busy}
                onClick={() => { if (sessionId) void run(async () => { await deleteTask(sessionId, task.id); onNavigate("/todo"); }); }}
              >
                <Trash2 size={13} /> Confirm delete
              </button>
              <button type="button" className="tw-btn-ghost" disabled={busy} onClick={() => setArmed(false)}>Cancel</button>
            </span>
          ) : (
            <button type="button" className="tw-btn-ghost" data-testid="delete-task-btn" onClick={() => setArmed(true)}>
              <Trash2 size={13} /> Delete task
            </button>
          )}
        </div>
      </section>

      <section className="tw-section">
        <h2 className="tw-h2">Subtasks <span className="tw-count">{subtasks.length}</span></h2>
        {subtasks.length > 0 && (
          <div className="tw-doclist" data-testid="task-subtasks">
            {subtasks.map((subtask, index) => (
              <div key={index} className="tw-docitem" style={{ gap: 8 }}>
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={subtask.done}
                  data-testid={`subtask-${index}`}
                  disabled={busy}
                  style={{ background: "none", border: "none", padding: 0, display: "flex", alignItems: "center", gap: 8, cursor: "pointer", color: "inherit", flex: 1, minWidth: 0, textAlign: "left" }}
                  onClick={() => { if (sessionId && !busy) void run(() => toggleSubtask(sessionId, task.id, index, !subtask.done)); }}
                >
                  {subtask.done ? <CheckCircle2 size={15} className="text-green-500" /> : <Circle size={15} />}
                  <span className={subtask.done ? "line-through opacity-60" : ""}>{subtask.text}</span>
                </button>
                <button
                  type="button"
                  className="tw-btn-ghost"
                  style={{ padding: "2px 6px" }}
                  aria-label={`Delete subtask: ${subtask.text}`}
                  data-testid={`subtask-delete-${index}`}
                  disabled={busy}
                  onClick={() => { if (sessionId && !busy) void run(() => deleteSubtask(sessionId, task.id, index)); }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="tw-form-actions" style={{ marginTop: 8 }}>
          <input
            className="tw-input"
            placeholder="Add a subtask…"
            value={subtaskText}
            data-testid="subtask-input"
            style={{ minWidth: 200 }}
            onChange={(event) => setSubtaskText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || !sessionId || !subtaskText.trim()) return;
              void run(async () => { await addSubtask(sessionId, task.id, subtaskText.trim()); setSubtaskText(""); });
            }}
          />
          <button
            type="button"
            className="tw-btn"
            disabled={busy || !subtaskText.trim()}
            data-testid="subtask-add-btn"
            onClick={() => { if (sessionId && subtaskText.trim()) void run(async () => { await addSubtask(sessionId, task.id, subtaskText.trim()); setSubtaskText(""); }); }}
          >
            <Plus size={13} /> Add
          </button>
        </div>
      </section>
    </>
  );
}
