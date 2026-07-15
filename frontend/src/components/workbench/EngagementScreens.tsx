"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckSquare,
  Download,
  Files,
  FolderKanban,
  Plus,
  Settings as SettingsIcon,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import type {
  AppState,
  Artifact,
  Engagement,
  EngagementRole,
  EngagementStatus,
  Task,
} from "@/lib/types";
import {
  addConvention,
  addEngagementMember,
  createEngagement,
  createEngagementTask,
  deleteEngagementArtifact,
  deleteEngagementTask,
  listUsers,
  openEngagementArtifact,
  removeConvention,
  removeEngagementMember,
  updateEngagement,
  updateEngagementTask,
  uploadEngagementArtifact,
} from "@/lib/api";
import { parseEngagementRoute } from "@/lib/engagementRoute";
import { friendlyError } from "@/lib/utils";

const statusLabel: Record<EngagementStatus, string> = {
  green: "Green",
  yellow: "Yellow",
  red: "Red",
};

function statusClass(status: EngagementStatus) {
  return status === "red"
    ? "tw-badge-red"
    : status === "yellow"
      ? "tw-badge-orange"
      : "tw-badge-green";
}

function StatusBadge({
  status,
  testid,
}: {
  status: EngagementStatus;
  testid?: string;
}) {
  return (
    <span className={`tw-badge ${statusClass(status)}`} data-testid={testid}>
      {statusLabel[status]}
    </span>
  );
}

function openTasks(engagement: Engagement) {
  return (engagement.tasks ?? []).filter((task) => task.status !== "Done")
    .length;
}

function roleOf(
  engagement: Engagement,
  userId: string | undefined,
): EngagementRole | null {
  return (
    engagement.members.find((member) => member.userId === userId)?.role ?? null
  );
}

function canEdit(role: EngagementRole | null) {
  return role === "owner" || role === "editor";
}

function isOverdue(task: Task, today: string) {
  return (
    task.status !== "Done" &&
    !!task.dueDate &&
    task.dueDate.slice(0, 10) < today
  );
}

function useBusy(onRefresh: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<unknown>) => {
    if (busy) return false;
    setBusy(true);
    setError(null);
    try {
      await action();
      await onRefresh();
      return true;
    } catch (err) {
      setError(friendlyError(err, "Action failed."));
      return false;
    } finally {
      setBusy(false);
    }
  };

  return { busy, error, run, setError };
}

export function EngagementsList({
  appState,
  onNavigate,
  onRefresh,
}: {
  appState: AppState;
  onNavigate: (route: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const engagements = appState.engagements ?? [];
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [customer, setCustomer] = useState("");
  const [description, setDescription] = useState("");
  const { busy, error, run, setError } = useBusy(onRefresh);

  const create = async () => {
    if (!name.trim()) {
      setError("Enter an engagement name.");
      return;
    }

    let createdId = "";
    const saved = await run(async () => {
      const created = await createEngagement({
        name: name.trim(),
        customer: customer.trim(),
        description: description.trim(),
      });
      createdId = created.id;
    });
    if (!saved || !createdId) return;

    setAdding(false);
    setName("");
    setCustomer("");
    setDescription("");
    onNavigate(`/engagements/${createdId}`);
  };

  return (
    <div className="tw-screen" data-testid="engagements-screen">
      <h1 className="tw-h1">Engagements</h1>
      <p className="tw-subtle">
        Shared customer-delivery workspaces — status, durable artifacts, and the
        team&apos;s record in one place.
      </p>

      <div className="tw-stats" style={{ marginTop: 14 }}>
        <StatBox
          label="Engagements"
          value={engagements.length}
          testid="eng-stat-total"
        />
        <StatBox
          label="Red"
          value={
            engagements.filter((engagement) => engagement.status === "red")
              .length
          }
          testid="eng-stat-red"
        />
        <StatBox
          label="Yellow"
          value={
            engagements.filter((engagement) => engagement.status === "yellow")
              .length
          }
          testid="eng-stat-yellow"
        />
        <StatBox
          label="Open tasks"
          value={engagements.reduce(
            (count, engagement) => count + openTasks(engagement),
            0,
          )}
          testid="eng-stat-tasks"
        />
      </div>

      {!adding ? (
        <button
          type="button"
          className="tw-addbar"
          data-testid="add-engagement-btn"
          onClick={() => setAdding(true)}
        >
          <Plus size={14} /> New engagement
        </button>
      ) : (
        <div className="tw-addform" data-testid="add-engagement-form">
          <label>
            Engagement name
            <input
              autoFocus
              className="tw-input"
              value={name}
              data-testid="engagement-name-input"
              onChange={(event) => setName(event.target.value)}
              aria-invalid={!!error && !name.trim()}
            />
          </label>
          <label>
            Customer <span className="tw-optional">optional</span>
            <input
              className="tw-input"
              value={customer}
              data-testid="engagement-customer-input"
              onChange={(event) => setCustomer(event.target.value)}
            />
          </label>
          <label>
            Description <span className="tw-optional">optional</span>
            <input
              className="tw-input"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <div className="tw-form-actions">
            <button
              type="button"
              className="tw-btn"
              data-testid="engagement-save-btn"
              disabled={busy}
              onClick={() => void create()}
            >
              Create
            </button>
            <button
              type="button"
              className="tw-btn-ghost"
              onClick={() => setAdding(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && (
        <p className="tw-error" data-testid="engagement-error" role="alert">
          {error}
        </p>
      )}

      {engagements.length === 0 ? (
        <section className="tw-section">
          <div className="tw-empty-card" data-testid="engagement-empty">
            <FolderKanban size={24} />
            <div>
              <strong>Your Engagement portfolio is empty.</strong>
              <p>
                Create an Engagement to keep customer status, delivery work,
                people, and durable artifacts together. You can also ask the
                assistant to create one.
              </p>
            </div>
          </div>
        </section>
      ) : (
        <section className="tw-section">
          <div className="tw-doclist tw-engagement-portfolio">
            {engagements.map((engagement) => (
              <EngagementPortfolioRow
                key={engagement.id}
                engagement={engagement}
                userId={appState.user?.id}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function EngagementPortfolioRow({
  engagement,
  userId,
  onNavigate,
}: {
  engagement: Engagement;
  userId?: string;
  onNavigate: (route: string) => void;
}) {
  const role = roleOf(engagement, userId);
  return (
    <button
      type="button"
      className="tw-docitem tw-rowlink tw-engagement-card"
      data-testid={`engagement-row-${engagement.id}`}
      onClick={() => onNavigate(`/engagements/${engagement.id}`)}
    >
      <FolderKanban size={16} />
      <span className="tw-engagement-main">
        <span className="tw-td-title">
          {engagement.name}
          {engagement.customer ? (
            <span className="tw-td-sub"> · {engagement.customer}</span>
          ) : null}
        </span>
        <span className="tw-td-sub">
          {engagement.status !== "green" && engagement.statusNote
            ? `Why: ${engagement.statusNote}`
            : engagement.description || "No description"}
        </span>
      </span>
      <span className="tw-engagement-meta">
        <StatusBadge
          status={engagement.status}
          testid={`engagement-status-${engagement.id}`}
        />
        <span
          className="tw-badge tw-badge-gray"
          data-testid={`engagement-role-${engagement.id}`}
        >
          {role ?? "member"}
        </span>
        <span className="tw-td-sub">
          <CheckSquare size={12} /> {openTasks(engagement)} open
        </span>
        <span className="tw-td-sub">
          <Files size={12} /> {(engagement.library ?? []).length}
        </span>
        {engagement.targetDate && (
          <span className="tw-td-sub">Target {engagement.targetDate}</span>
        )}
      </span>
    </button>
  );
}

export function EngagementScreen({
  appState,
  viewRoute,
  onNavigate,
  onRefresh,
}: {
  appState: AppState;
  viewRoute: string;
  onNavigate: (route: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const route = parseEngagementRoute(viewRoute);
  if (!route)
    return (
      <div className="tw-empty">
        Engagement not found (or you are not a member).
      </div>
    );

  const { id, sub, recordId } = route;
  const engagement = (appState.engagements ?? []).find(
    (candidate) => candidate.id === id,
  );
  if (!engagement)
    return (
      <div className="tw-empty">
        Engagement not found (or you are not a member).
      </div>
    );

  const role = roleOf(engagement, appState.user?.id);
  const editable = canEdit(role);
  const base = `/engagements/${engagement.id}`;
  const today = new Date().toISOString().slice(0, 10);
  const header = (
    <EngagementHeader
      engagement={engagement}
      role={role}
      sub={sub}
      base={base}
      editable={editable}
      onNavigate={onNavigate}
    />
  );

  if (sub === "tasks" && recordId) {
    const task = engagement.tasks.find(
      (candidate) => candidate.id === recordId,
    );
    return (
      <div className="tw-screen" data-testid="engagement-task-detail">
        {header}
        {task ? (
          <EngagementTaskDetail
            engagement={engagement}
            task={task}
            editable={editable}
            onRefresh={onRefresh}
            onNavigate={onNavigate}
          />
        ) : (
          <div className="tw-empty">Task not found.</div>
        )}
      </div>
    );
  }
  if (sub === "tasks")
    return (
      <div className="tw-screen" data-testid="engagement-tasks-screen">
        {header}
        <EngagementTasks
          engagement={engagement}
          editable={editable}
          today={today}
          onNavigate={onNavigate}
          onRefresh={onRefresh}
        />
      </div>
    );
  if (sub === "documents")
    return (
      <div className="tw-screen" data-testid="engagement-documents-screen">
        {header}
        <EngagementDocuments
          engagement={engagement}
          editable={editable}
          onRefresh={onRefresh}
        />
      </div>
    );
  if (sub === "settings")
    return (
      <div className="tw-screen" data-testid="engagement-settings-screen">
        {header}
        <EngagementSettings
          engagement={engagement}
          myRole={role}
          onRefresh={onRefresh}
        />
      </div>
    );

  const overdue = engagement.tasks.filter((task) =>
    isOverdue(task, today),
  ).length;
  const editorKey = JSON.stringify([
    engagement.id,
    engagement.name,
    engagement.description,
    engagement.customer,
    engagement.startDate,
    engagement.targetDate,
    engagement.status,
    engagement.statusNote,
  ]);
  return (
    <div className="tw-screen" data-testid="engagement-overview">
      {header}
      <div className="tw-stats" style={{ marginTop: 14 }}>
        <StatBox label="Open tasks" value={openTasks(engagement)} />
        <StatBox label="Overdue" value={overdue} />
        <StatBox label="Artifacts" value={(engagement.library ?? []).length} />
        <StatBox label="Members" value={engagement.members.length} />
      </div>
      <EngagementDetailEditor
        key={editorKey}
        engagement={engagement}
        role={role}
        onRefresh={onRefresh}
      />
      <ActivityFeed engagement={engagement} />
    </div>
  );
}

function EngagementHeader({
  engagement,
  role,
  sub,
  base,
  editable,
  onNavigate,
}: {
  engagement: Engagement;
  role: EngagementRole | null;
  sub: string;
  base: string;
  editable: boolean;
  onNavigate: (route: string) => void;
}) {
  const tabs: [string, string][] = [
    ["", "Overview"],
    ["tasks", "Tasks"],
    ["documents", "Artifacts"],
    ["settings", "Team & conventions"],
  ];
  return (
    <>
      <button
        type="button"
        className="tw-back"
        onClick={() => onNavigate("/engagements")}
      >
        <ArrowLeft size={14} /> All engagements
      </button>
      <h1 className="tw-h1">{engagement.name}</h1>
      <div className="tw-engagement-header">
        <StatusBadge
          status={engagement.status}
          testid="engagement-status-badge"
        />
        <span className="tw-badge tw-badge-gray" data-testid="my-role">
          {role ?? "viewer"}
        </span>
        {engagement.customer && (
          <span className="tw-td-sub">{engagement.customer}</span>
        )}
        {engagement.targetDate && (
          <span className="tw-td-sub">Target {engagement.targetDate}</span>
        )}
      </div>
      {engagement.status !== "green" && engagement.statusNote && (
        <p className="tw-subtle" data-testid="engagement-status-note">
          Why: {engagement.statusNote}
        </p>
      )}
      {!editable && (
        <p className="tw-role-note" data-testid="viewer-note">
          View-only: your role lets you review this Engagement but not change
          its delivery record, team, tasks, conventions, or artifacts.
        </p>
      )}
      <div className="tw-tabs" data-testid="engagement-tabs">
        {tabs.map(([tab, label]) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={sub === tab}
            className={`tw-tab ${sub === tab ? "tw-tab-active" : ""}`}
            data-testid={`engagement-tab-${tab || "overview"}`}
            onClick={() => onNavigate(tab ? `${base}/${tab}` : base)}
          >
            {label}
          </button>
        ))}
      </div>
    </>
  );
}

function ActivityFeed({ engagement }: { engagement: Engagement }) {
  return (
    <section className="tw-section">
      <h2 className="tw-h2">Recent activity</h2>
      {engagement.activity.length ? (
        <div className="tw-doclist" data-testid="activity-feed">
          {engagement.activity.slice(0, 8).map((entry, index) => (
            <div
              key={`${entry.ts}-${index}`}
              className="tw-docitem tw-activity"
            >
              <span className="tw-td-sub">{entry.userId}</span>
              <span className="tw-td-title">{entry.detail}</span>
              <span className="tw-td-sub">
                {entry.ts.slice(5, 16).replace("T", " ")}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="tw-empty-sm">No activity yet.</div>
      )}
    </section>
  );
}

function StatBox({
  label,
  value,
  testid,
}: {
  label: string;
  value: number | string;
  testid?: string;
}) {
  return (
    <div className="tw-stat" data-testid={testid}>
      <div className="tw-stat-value">{value}</div>
      <div className="tw-stat-label">{label}</div>
    </div>
  );
}

function EngagementDetailEditor({
  engagement,
  role,
  onRefresh,
}: {
  engagement: Engagement;
  role: EngagementRole | null;
  onRefresh: () => Promise<void>;
}) {
  const editable = canEdit(role);
  const owner = role === "owner";
  const { busy, error, run } = useBusy(onRefresh);
  const reasonRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(engagement.name);
  const [description, setDescription] = useState(engagement.description);
  const [customer, setCustomer] = useState(engagement.customer);
  const [startDate, setStartDate] = useState(engagement.startDate);
  const [targetDate, setTargetDate] = useState(engagement.targetDate);
  const [status, setStatus] = useState<EngagementStatus>(engagement.status);
  const [statusNote, setStatusNote] = useState(engagement.statusNote);
  const [statusError, setStatusError] = useState("");
  if (!editable)
    return (
      <section className="tw-section">
        <h2 className="tw-h2">Delivery record</h2>
        <p className="tw-subtle">
          {engagement.description || "No description provided."}
        </p>
      </section>
    );
  const save = async () => {
    if ((status === "yellow" || status === "red") && !statusNote.trim()) {
      setStatusError(
        `${statusLabel[status]} needs a reason before it can be saved.`,
      );
      requestAnimationFrame(() => reasonRef.current?.focus());
      return;
    }
    setStatusError("");
    await run(() =>
      updateEngagement(engagement.id, {
        ...(owner && name.trim() !== engagement.name
          ? { name: name.trim() }
          : {}),
        description: description.trim(),
        customer: customer.trim(),
        startDate,
        targetDate,
        status,
        statusNote: status === "green" ? "" : statusNote.trim(),
      }),
    );
  };
  return (
    <section className="tw-section" data-testid="engagement-detail-editor">
      <h2 className="tw-h2">Delivery record</h2>
      <div className="tw-edit-grid">
        {owner && (
          <label>
            Engagement name
            <input
              className="tw-input"
              value={name}
              data-testid="engagement-name-edit"
              disabled={busy}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
        )}
        <label>
          Description
          <textarea
            className="tw-input"
            value={description}
            data-testid="engagement-description-edit"
            disabled={busy}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label>
          Customer
          <input
            className="tw-input"
            value={customer}
            data-testid="engagement-customer-edit"
            disabled={busy}
            onChange={(event) => setCustomer(event.target.value)}
          />
        </label>
        <label>
          Start date
          <input
            type="date"
            className="tw-input"
            value={startDate}
            disabled={busy}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </label>
        <label>
          Target date
          <input
            type="date"
            className="tw-input"
            value={targetDate}
            data-testid="engagement-target-edit"
            disabled={busy}
            onChange={(event) => setTargetDate(event.target.value)}
          />
        </label>
        <label>
          Status
          <select
            className="tw-input"
            value={status}
            data-testid="status-select"
            disabled={busy}
            onChange={(event) => {
              const next = event.target.value as EngagementStatus;
              setStatus(next);
              if (next === "green") {
                setStatusNote("");
                setStatusError("");
              } else requestAnimationFrame(() => reasonRef.current?.focus());
            }}
          >
            <option value="green">Green</option>
            <option value="yellow">Yellow</option>
            <option value="red">Red</option>
          </select>
        </label>
        {status !== "green" && (
          <label>
            Reason <span className="tw-required">required</span>
            <input
              ref={reasonRef}
              className="tw-input"
              value={statusNote}
              data-testid="status-note-input"
              aria-invalid={!!statusError}
              aria-describedby={statusError ? "status-note-error" : undefined}
              disabled={busy}
              onChange={(event) => {
                setStatusNote(event.target.value);
                setStatusError("");
              }}
            />
          </label>
        )}
      </div>
      {statusError && (
        <p id="status-note-error" className="tw-error" role="alert">
          {statusError}
        </p>
      )}
      {error && (
        <p className="tw-error" data-testid="detail-error" role="alert">
          {error}
        </p>
      )}
      <div className="tw-form-actions">
        <button
          type="button"
          className="tw-btn"
          disabled={busy || (owner && !name.trim())}
          onClick={() => void save()}
        >
          {busy ? "Saving…" : "Save delivery record"}
        </button>
      </div>
    </section>
  );
}

function EngagementTasks({
  engagement,
  editable,
  today,
  onNavigate,
  onRefresh,
}: {
  engagement: Engagement;
  editable: boolean;
  today: string;
  onNavigate: (route: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [dueDate, setDueDate] = useState("");
  const { busy, error, run, setError } = useBusy(onRefresh);
  const create = async () => {
    if (!title.trim()) {
      setError("Enter a task title.");
      return;
    }
    await createEngagementTask(engagement.id, { title: title.trim(), dueDate });
    setAdding(false);
    setTitle("");
    setDueDate("");
  };
  return (
    <section className="tw-section">
      <div className="tw-section-heading">
        <h2 className="tw-h2">Tasks</h2>
        {editable && !adding && (
          <button
            type="button"
            className="tw-btn"
            data-testid="engagement-add-task-btn"
            onClick={() => setAdding(true)}
          >
            <Plus size={14} /> Add task
          </button>
        )}
      </div>
      {editable && adding && (
        <div className="tw-addform" data-testid="engagement-add-task-form">
          <label>
            Task title
            <input
              autoFocus
              className="tw-input"
              value={title}
              data-testid="engagement-task-title-input"
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label>
            Due date
            <input
              type="date"
              className="tw-input"
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
            />
          </label>
          <div className="tw-form-actions">
            <button
              type="button"
              className="tw-btn"
              data-testid="engagement-task-save-btn"
              disabled={busy}
              onClick={() => void run(create)}
            >
              Save
            </button>
            <button
              type="button"
              className="tw-btn-ghost"
              onClick={() => setAdding(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && (
        <p className="tw-error" role="alert">
          {error}
        </p>
      )}
      {!engagement.tasks.length ? (
        <div className="tw-empty-sm">No tasks in this Engagement yet.</div>
      ) : (
        <div className="tw-task-list" data-testid="engagement-tasks-table">
          {engagement.tasks.map((task) => (
            <div
              key={task.id}
              className="tw-task-row"
              data-testid={`engagement-task-row-${task.id}`}
            >
              <button
                type="button"
                className="tw-task-open"
                onClick={() =>
                  onNavigate(`/engagements/${engagement.id}/tasks/${task.id}`)
                }
              >
                <span className="tw-td-title">{task.title}</span>
                <span
                  className={`tw-badge ${task.status === "Done" ? "tw-badge-green" : task.status === "Blocked" ? "tw-badge-red" : "tw-badge-gray"}`}
                >
                  {task.status}
                </span>
                <span className="tw-td-sub">
                  {task.dueDate || "No due date"}
                  {isOverdue(task, today) ? " · overdue" : ""}
                </span>
              </button>
              {editable && (
                <ArmedDelete
                  testid={`engagement-task-delete-${task.id}`}
                  onConfirm={() =>
                    void run(() => deleteEngagementTask(engagement.id, task.id))
                  }
                />
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function EngagementTaskDetail({
  engagement,
  task,
  editable,
  onRefresh,
  onNavigate,
}: {
  engagement: Engagement;
  task: Task;
  editable: boolean;
  onRefresh: () => Promise<void>;
  onNavigate: (route: string) => void;
}) {
  const { busy, error, run } = useBusy(onRefresh);
  return (
    <section className="tw-section" data-testid="engagement-task-editor">
      <button
        type="button"
        className="tw-back"
        onClick={() => onNavigate(`/engagements/${engagement.id}/tasks`)}
      >
        <ArrowLeft size={14} /> All tasks
      </button>
      <h2 className="tw-h2">{task.title}</h2>
      {editable ? (
        <div className="tw-addform">
          <label>
            Status
            <select
              className="tw-input"
              value={task.status}
              data-testid="engagement-task-status"
              disabled={busy}
              onChange={(event) =>
                void run(() =>
                  updateEngagementTask(engagement.id, task.id, {
                    status: event.target.value,
                  }),
                )
              }
            >
              {["To do", "In progress", "Blocked", "Done"].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Priority
            <select
              className="tw-input"
              value={task.priority}
              data-testid="engagement-task-priority"
              disabled={busy}
              onChange={(event) =>
                void run(() =>
                  updateEngagementTask(engagement.id, task.id, {
                    priority: event.target.value,
                  }),
                )
              }
            >
              {["Low", "Medium", "High"].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Due date
            <input
              type="date"
              className="tw-input"
              value={(task.dueDate || "").slice(0, 10)}
              disabled={busy}
              onChange={(event) =>
                void run(() =>
                  updateEngagementTask(engagement.id, task.id, {
                    dueDate: event.target.value,
                  }),
                )
              }
            />
          </label>
        </div>
      ) : (
        <p className="tw-subtle">View-only task details.</p>
      )}
      {error && (
        <p className="tw-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function EngagementSettings({
  engagement,
  myRole,
  onRefresh,
}: {
  engagement: Engagement;
  myRole: EngagementRole | null;
  onRefresh: () => Promise<void>;
}) {
  const owner = myRole === "owner";
  const editable = canEdit(myRole);
  const [directory, setDirectory] = useState<
    { id: string; username: string; displayName: string }[]
  >([]);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<EngagementRole>("viewer");
  const [convention, setConvention] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  useEffect(() => {
    void listUsers()
      .then(setDirectory)
      .catch(() => setDirectory([]));
  }, []);
  const displayUser = (id: string) => {
    const user = directory.find((candidate) => candidate.id === id);
    return user?.displayName || user?.username || id;
  };
  const candidates = directory.filter(
    (user) => !engagement.members.some((member) => member.userId === user.id),
  );
  return (
    <>
      <section className="tw-section">
        <h2 className="tw-h2">
          <Users size={14} /> Members
        </h2>
        <div className="tw-doclist" data-testid="member-list">
          {engagement.members.map((member) => (
            <div
              key={member.userId}
              className="tw-docitem tw-member-row"
              data-testid={`member-${member.userId}`}
            >
              <span>
                <span className="tw-td-title">
                  {displayUser(member.userId)}
                </span>
                <span className="tw-td-sub tw-stable-id">{member.userId}</span>
              </span>
              <span className="tw-badge tw-badge-gray">{member.role}</span>
              {owner && <OwnerMemberControls key={`${member.userId}-${member.role}`} engagementId={engagement.id} member={member} busy={busy} run={run} />}
            </div>
          ))}
        </div>
        {owner && (
          <div className="tw-addform" data-testid="add-member-form">
            <label>
              Add member
              <select
                className="tw-input"
                value={userId}
                data-testid="member-user-select"
                onChange={(event) => setUserId(event.target.value)}
              >
                <option value="">Choose a user…</option>
                {candidates.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.displayName || user.username} (
                    {user.username || user.id})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Role
              <select
                className="tw-input"
                value={role}
                data-testid="member-role-select"
                onChange={(event) =>
                  setRole(event.target.value as EngagementRole)
                }
              >
                {(["viewer", "editor", "owner"] as const).map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <div className="tw-form-actions">
              <button
                type="button"
                className="tw-btn"
                data-testid="member-add-btn"
                disabled={busy || !userId}
                onClick={() =>
                  void run(async () => {
                    await addEngagementMember(engagement.id, userId, role);
                    setUserId("");
                  })
                }
              >
                Add member
              </button>
            </div>
          </div>
        )}
      </section>
      <section className="tw-section">
        <h2 className="tw-h2">
          <SettingsIcon size={14} /> Conventions
        </h2>
        <div className="tw-doclist">
          {engagement.conventions.map((item) => (
            <div
              key={item.id}
              className="tw-docitem"
              data-testid={`convention-row-${item.id}`}
            >
              <span className="tw-td-sub">{item.text}</span>
              {editable && (
                <ArmedDelete
                  testid={`convention-delete-${item.id}`}
                  onConfirm={() =>
                    void run(() => removeConvention(engagement.id, item.id))
                  }
                />
              )}
            </div>
          ))}
        </div>
        {editable && (
          <div className="tw-addform">
            <label>
              Working agreement
              <input
                className="tw-input"
                value={convention}
                data-testid="convention-input"
                onChange={(event) => setConvention(event.target.value)}
              />
            </label>
            <div className="tw-form-actions">
              <button
                type="button"
                className="tw-btn"
                data-testid="convention-add-btn"
                disabled={busy || !convention.trim()}
                onClick={() =>
                  void run(async () => {
                    await addConvention(engagement.id, convention.trim());
                    setConvention("");
                  })
                }
              >
                Add convention
              </button>
            </div>
          </div>
        )}
      </section>
      {error && (
        <p className="tw-error" data-testid="settings-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function OwnerMemberControls({ engagementId, member, busy, run }: { engagementId: string; member: Engagement["members"][number]; busy: boolean; run: (action: () => Promise<unknown>) => Promise<boolean> }) {
  const [role, setRole] = useState<EngagementRole>(member.role);
  return (
    <span className="tw-member-actions">
      <label className="tw-visually-hidden" htmlFor={`member-role-${member.userId}`}>Role for {member.userId}</label>
      <select id={`member-role-${member.userId}`} className="tw-input" aria-label={`Role for ${member.userId}`} value={role} disabled={busy} onChange={(event) => setRole(event.target.value as EngagementRole)}>
        {(["viewer", "editor", "owner"] as const).map((value) => <option key={value}>{value}</option>)}
      </select>
      <button type="button" className="tw-btn-ghost" disabled={busy || role === member.role} onClick={() => void run(() => addEngagementMember(engagementId, member.userId, role))}>Update role</button>
      <ArmedDelete testid={`member-remove-${member.userId}`} onConfirm={() => void run(() => removeEngagementMember(engagementId, member.userId))} />
    </span>
  );
}

function EngagementDocuments({
  engagement,
  editable,
  onRefresh,
}: {
  engagement: Engagement;
  editable: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const artifacts: Artifact[] = engagement.library ?? [];
  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await uploadEngagementArtifact(engagement.id, file);
      await onRefresh();
    } catch (err) {
      setError(friendlyError(err, "Artifact action failed."));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };
  const open = async (artifact: Artifact) => {
    setError("");
    try {
      const blob = await openEngagementArtifact(engagement.id, artifact.id);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(friendlyError(err, "Artifact action failed."));
    }
  };
  const remove = async (artifact: Artifact) => {
    setError("");
    try {
      await deleteEngagementArtifact(engagement.id, artifact.id);
      await onRefresh();
    } catch (err) {
      setError(friendlyError(err, "Artifact action failed."));
    }
  };
  return (
    <section className="tw-section">
      <div className="tw-section-heading">
        <h2 className="tw-h2">Artifacts</h2>
        {editable && (
          <>
            <input
              ref={fileInput}
              type="file"
              data-testid="artifact-upload-input"
              className="tw-visually-hidden"
              onChange={(event) => void upload(event.target.files?.[0])}
            />
            <button
              type="button"
              className="tw-btn"
              data-testid="artifact-upload-btn"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              <Upload size={13} /> {busy ? "Uploading…" : "Upload"}
            </button>
          </>
        )}
      </div>
      {error && (
        <div className="tw-error" data-testid="artifact-error" role="alert">
          {error}
        </div>
      )}
      {!artifacts.length ? (
        <div className="tw-empty-sm">No artifacts on this Engagement yet.</div>
      ) : (
        <div className="tw-doclist">
          {artifacts.map((artifact) => (
            <div
              key={artifact.id}
              className="tw-docitem tw-artifact-row"
              data-testid={`artifact-row-${artifact.id}`}
            >
              <Files size={15} />
              <span className="tw-td-title">{artifact.name}</span>
              <span className="tw-td-sub">{humanSize(artifact.size)}</span>
              <span className="tw-td-sub">{artifact.uploadedBy}</span>
              <button
                type="button"
                className="tw-btn-ghost"
                data-testid={`artifact-open-${artifact.id}`}
                title={`Open ${artifact.name}`}
                onClick={() => void open(artifact)}
              >
                <Download size={13} />
              </button>
              {editable && (
                <ArmedDelete
                  testid={`artifact-delete-${artifact.id}`}
                  onConfirm={() => void remove(artifact)}
                />
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function humanSize(bytes: number) {
  return bytes < 1024
    ? `${bytes} B`
    : bytes < 1024 * 1024
      ? `${(bytes / 1024).toFixed(1)} KB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function ArmedDelete({
  onConfirm,
  testid,
}: {
  onConfirm: () => void;
  testid: string;
}) {
  const [armed, setArmed] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (armed) requestAnimationFrame(() => confirmRef.current?.focus());
  }, [armed]);
  const cancel = () => {
    setArmed(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };
  if (!armed)
    return (
      <button
        ref={triggerRef}
        type="button"
        className="tw-btn-ghost"
        data-testid={testid}
        title="Delete"
        aria-label="Delete"
        onClick={(event) => {
          event.stopPropagation();
          setArmed(true);
        }}
      >
        <Trash2 size={13} />
      </button>
    );
  return (
    <span className="tw-confirm-actions">
      <button
        ref={confirmRef}
        type="button"
        className="tw-btn"
        data-testid={`${testid}-confirm`}
        onClick={(event) => {
          event.stopPropagation();
          cancel();
          onConfirm();
        }}
      >
        Confirm
      </button>
      <button
        type="button"
        className="tw-btn-ghost"
        data-testid={`${testid}-cancel`}
        onClick={(event) => {
          event.stopPropagation();
          cancel();
        }}
      >
        Cancel
      </button>
    </span>
  );
}
