"use client";

// Engagement screens: list, overview, tasks, documents, settings.
// Role-aware: mutation controls render only for editor+; member management for owners.
// All mutations go through the typed REST API then onRefresh() re-reads /app/state —
// the pane never renders from its own optimism (same invariant as everywhere else).
// v1 delivery record is deliberately slim: a G/Y/R status that always carries a why
// (stage, milestones, risks, and actions are parked — docs/mvp-requirements.md R7).

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft, CheckSquare, Download, Files, FolderKanban,
  Plus, Settings as SettingsIcon, Trash2, Upload, Users,
} from "lucide-react";
import type {
  AppState, Artifact, Engagement, EngagementStatus, EngagementRole, Task,
} from "@/lib/types";
import {
  addConvention, addEngagementMember, createEngagement,
  createEngagementTask, deleteEngagementArtifact, deleteEngagementTask,
  listUsers, openEngagementArtifact, removeConvention, removeEngagementMember,
  updateEngagement, updateEngagementTask, uploadEngagementArtifact,
} from "@/lib/api";
import { friendlyError } from "@/lib/utils";

function statusClass(status: EngagementStatus): string {
  return status === "red" ? "tw-badge-red" : status === "yellow" ? "tw-badge-orange" : "tw-badge-green";
}

function StatusBadge({ status, testid }: { status: EngagementStatus; testid?: string }) {
  return <span className={`tw-badge ${statusClass(status)}`} data-testid={testid}>{status}</span>;
}

const openTasks = (p: Engagement) => (p.tasks ?? []).filter((t) => t.status !== "Done").length;

function roleOf(p: Engagement, userId: string | undefined): EngagementRole | null {
  const m = p.members.find((m) => m.userId === userId);
  return m ? m.role : null;
}

function canEdit(role: EngagementRole | null): boolean {
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

// ── /engagements — the list ─────────────────────────────────────────────────────
export function EngagementsList({ appState, onNavigate, onRefresh }: {
  appState: AppState; onNavigate: (r: string) => void; onRefresh: () => Promise<void>;
}) {
  const engagements = appState.engagements ?? [];
  const me = appState.user?.id;
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [customer, setCustomer] = useState("");
  const { busy, error, run } = useBusy(onRefresh);

  return (
    <div className="tw-screen" data-testid="engagements-screen">
      <h1 className="tw-h1">Engagements</h1>
      <p className="tw-subtle">Shared customer-delivery workspaces — status, documents, and the team&apos;s records in one place.</p>

      <div className="tw-stats" style={{ marginTop: 14 }}>
        <StatBox label="Engagements" value={engagements.length} testid="eng-stat-total" />
        <StatBox label="Red" value={engagements.filter((p) => p.status === "red").length} testid="eng-stat-red" />
        <StatBox label="Yellow" value={engagements.filter((p) => p.status === "yellow").length} testid="eng-stat-yellow" />
        <StatBox label="Open tasks" value={engagements.reduce((n, p) => n + openTasks(p), 0)} testid="eng-stat-tasks" />
      </div>

      {!adding ? (
        <button type="button" className="tw-addbar" data-testid="add-engagement-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> New engagement
        </button>
      ) : (
        <div className="tw-addform" data-testid="add-engagement-form">
          <input autoFocus placeholder="Engagement name" value={name} data-testid="engagement-name-input"
            onChange={(e) => setName(e.target.value)}
            style={{ minWidth: 220 }} className="tw-input" />
          <input placeholder="Customer (optional)" value={customer} data-testid="engagement-customer-input"
            onChange={(e) => setCustomer(e.target.value)}
            style={{ minWidth: 180 }} className="tw-input" />
          <input placeholder="Description (optional)" value={description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ minWidth: 260 }} className="tw-input" />
          <button type="button" className="tw-btn" data-testid="engagement-save-btn" disabled={busy || !name.trim()}
            onClick={() => run(async () => { await createEngagement({ name: name.trim(), description: description.trim(), customer: customer.trim() }); setAdding(false); setName(""); setDescription(""); setCustomer(""); })}>
            Create
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      )}
      {error && <p className="tw-error" data-testid="engagement-error">{error}</p>}

      {engagements.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">No engagements yet. Create one above, or ask the assistant.</div></section>
      ) : (
        <section className="tw-section">
          <div className="tw-doclist">
            {engagements.map((p) => {
              const role = roleOf(p, me);
              return (
                <div key={p.id} className="tw-docitem tw-rowlink" data-testid={`engagement-row-${p.id}`}
                  role="button" tabIndex={0}
                  onClick={() => onNavigate(`/engagements/${p.id}`)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNavigate(`/engagements/${p.id}`); } }}>
                  <FolderKanban size={16} />
                  <span className="flex min-w-0 flex-col">
                    <span className="tw-td-title">{p.name}{p.customer ? <span className="tw-td-sub"> · {p.customer}</span> : null}</span>
                    <span className="tw-td-sub">
                      {p.statusNote ? `${p.statusNote.slice(0, 80)}${p.statusNote.length > 80 ? "…" : ""}` : p.description || "—"}
                    </span>
                  </span>
                  <span style={{ marginLeft: "auto" }} className="flex items-center gap-2">
                    <StatusBadge status={p.status} testid={`engagement-status-${p.id}`} />
                    <span className="tw-badge tw-badge-gray" data-testid={`engagement-role-${p.id}`}>{role}</span>
                    <span className="tw-td-sub"><Users size={12} style={{ display: "inline" }} /> {p.members.length}</span>
                    <span className="tw-td-sub"><CheckSquare size={12} style={{ display: "inline" }} /> {p.tasks.length}</span>
                    <span className="tw-td-sub"><Files size={12} style={{ display: "inline" }} /> {(p.library ?? []).length}</span>
                    <span className="tw-td-sub">{p.targetDate ? `→ ${p.targetDate}` : ""}</span>
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

// ── /engagements/{id}(/*) — everything inside one engagement ──────────────────────
export function EngagementScreen({ appState, viewRoute, onNavigate, onRefresh }: {
  appState: AppState; viewRoute: string; onNavigate: (r: string) => void; onRefresh: () => Promise<void>;
}) {
  const me = appState.user?.id;
  const parts = viewRoute.split("/").filter(Boolean); // ["engagements", pid, sub?, recordId?]
  const pid = parts[1];
  const sub = parts[2] ?? "";
  const recordId = parts[3] ?? "";
  const engagement = (appState.engagements ?? []).find((p) => p.id === pid);
  if (!engagement) return <div className="tw-empty">Engagement not found (or you are not a member).</div>;
  const role = roleOf(engagement, me);
  const editable = canEdit(role);
  const base = `/engagements/${engagement.id}`;
  const today = new Date().toISOString().slice(0, 10);

  const tabs = (
    <div className="tw-tabs" data-testid="engagement-tabs">
      {[["", "Overview"], ["tasks", "Tasks"], ["documents", "Documents"], ["settings", "Settings"]].map(([key, label]) => (
        <button key={key} type="button"
          className={`tw-tab ${sub === key || (key === "tasks" && sub === "tasks") ? "tw-tab-active" : ""}`}
          data-testid={`engagement-tab-${key || "overview"}`}
          onClick={() => onNavigate(key ? `${base}/${key}` : base)}>
          {label}
        </button>
      ))}
    </div>
  );

  const header = (
    <>
      <button type="button" className="tw-back" onClick={() => onNavigate("/engagements")}><ArrowLeft size={14} /> All engagements</button>
      <h1 className="tw-h1">{engagement.name}</h1>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <StatusBadge status={engagement.status} testid="engagement-status-badge" />
        <span className="tw-badge tw-badge-gray" data-testid="my-role">{role}</span>
        {engagement.customer && <span className="tw-td-sub">{engagement.customer}</span>}
        <span className="tw-subtle">{engagement.description}</span>
      </div>
      {engagement.statusNote && (
        <p className="tw-subtle" data-testid="engagement-status-note" style={{ marginTop: 4 }}>
          {engagement.status !== "green" ? "Why: " : ""}{engagement.statusNote}
        </p>
      )}
      {tabs}
    </>
  );

  if (sub === "tasks" && recordId) {
    const t = engagement.tasks.find((x) => x.id === recordId);
    if (!t) return <div className="tw-empty">Task not found.</div>;
    return (
      <div className="tw-screen" data-testid="engagement-task-detail">
        {header}
        <EngagementTaskDetail engagement={engagement} task={t} editable={editable} onRefresh={onRefresh} onNavigate={onNavigate} />
      </div>
    );
  }

  if (sub === "tasks") {
    return (
      <div className="tw-screen" data-testid="engagement-tasks-screen">
        {header}
        <EngagementTasks engagement={engagement} editable={editable} today={today} onNavigate={onNavigate} onRefresh={onRefresh} />
      </div>
    );
  }

  if (sub === "documents") {
    return (
      <div className="tw-screen" data-testid="engagement-documents-screen">
        {header}
        <EngagementDocuments engagement={engagement} editable={editable} onRefresh={onRefresh} />
      </div>
    );
  }

  if (sub === "settings") {
    return (
      <div className="tw-screen" data-testid="engagement-settings-screen">
        {header}
        <EngagementSettings engagement={engagement} myRole={role} onRefresh={onRefresh} />
      </div>
    );
  }

  // Overview
  const overdue = engagement.tasks.filter((t) => isOverdue(t, today)).length;
  return (
    <div className="tw-screen" data-testid="engagement-overview">
      {header}
      <div className="tw-stats" style={{ marginTop: 14 }}>
        <StatBox label="Open tasks" value={openTasks(engagement)} testid="stat-open-tasks" />
        <StatBox label="Overdue" value={overdue} testid="stat-overdue" />
        <StatBox label="Documents" value={(engagement.library ?? []).length} testid="stat-documents" />
        <StatBox label="Members" value={engagement.members.length} testid="stat-members" />
      </div>
      <EngagementDetailEditor key={engagement.id} engagement={engagement} editable={editable} onRefresh={onRefresh} />
      {engagement.conventions.length > 0 && (
        <section className="tw-section">
          <h2 className="tw-h2">Conventions</h2>
          <div className="tw-doclist">
            {engagement.conventions.map((c) => (
              <div key={c.id} className="tw-docitem" data-testid={`convention-${c.id}`}>
                <SettingsIcon size={14} /> <span className="tw-td-sub">{c.text}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="tw-section">
        <h2 className="tw-h2">Recent activity</h2>
        {engagement.activity.length === 0 ? (
          <div className="tw-empty-sm">No activity yet.</div>
        ) : (
          <div className="tw-doclist" data-testid="activity-feed">
            {engagement.activity.slice(0, 8).map((a, i) => (
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

function StatBox({ label, value, testid }: { label: string; value: number | string; testid?: string }) {
  return (
    <div className="tw-stat" data-testid={testid}>
      <div className="tw-stat-value">{value}</div>
      <div className="tw-stat-label">{label}</div>
    </div>
  );
}

// Delivery-record editor: customer/dates save on change; status is HELD locally
// when moving to yellow/red until a non-empty why is entered, then both commit together —
// the same rule the tool layer (NOTE_REQUIRED) and REST (422) enforce.
function EngagementDetailEditor({ engagement, editable, onRefresh }: {
  engagement: Engagement; editable: boolean; onRefresh: () => Promise<void>;
}) {
  const { busy, error, run } = useBusy(onRefresh);
  const [saved, setSaved] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<EngagementStatus | null>(null);
  const [note, setNote] = useState(engagement.statusNote);
  if (!editable) return null;

  const save = async (fn: () => Promise<unknown>) => {
    setSaved(false);
    await run(fn);
    setSaved(true);
  };
  const shownStatus = pendingStatus ?? engagement.status;
  const noteVisible = pendingStatus !== null || engagement.status !== "green";

  return (
    <section className="tw-section" data-testid="engagement-detail-editor">
      <h2 className="tw-h2">Delivery record</h2>
      <div className="tw-addform">
        <input className="tw-input" placeholder="Customer" defaultValue={engagement.customer}
          data-testid="engagement-customer-edit" disabled={busy} style={{ minWidth: 180 }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v !== engagement.customer) save(() => updateEngagement(engagement.id, { customer: v })); }} />
        <input type="date" className="tw-input" title="Start date" defaultValue={engagement.startDate} disabled={busy}
          onChange={(e) => save(() => updateEngagement(engagement.id, { startDate: e.target.value }))} />
        <input type="date" className="tw-input" title="Target date" defaultValue={engagement.targetDate} disabled={busy}
          data-testid="engagement-target-edit"
          onChange={(e) => save(() => updateEngagement(engagement.id, { targetDate: e.target.value }))} />
        <span className="tw-td-sub" data-testid="detail-save-state">{busy ? "Saving…" : error ? "" : saved ? "Saved ✓" : ""}</span>
      </div>
      <div className="tw-addform" style={{ marginTop: 8 }}>
        <select className="tw-input" value={shownStatus} data-testid="status-select" disabled={busy}
          onChange={(e) => {
            const v = e.target.value as EngagementStatus;
            if (v === "green") { setPendingStatus(null); save(() => updateEngagement(engagement.id, { status: "green", statusNote: "" })); }
            else { setPendingStatus(v); setNote(engagement.statusNote); }
          }}>
          {(["green", "yellow", "red"] as const).map((h) => <option key={h}>{h}</option>)}
        </select>
        {noteVisible && (
          <input className="tw-input" placeholder="Why? (required for yellow/red)" value={note}
            data-testid="status-note-input" disabled={busy} style={{ minWidth: 320 }}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => {
              if (pendingStatus === null && note.trim() && note.trim() !== engagement.statusNote)
                save(() => updateEngagement(engagement.id, { statusNote: note.trim() }));
            }} />
        )}
        {pendingStatus !== null && (
          <>
            <button type="button" className="tw-btn" data-testid="status-commit-btn" disabled={busy || !note.trim()}
              onClick={() => { const h = pendingStatus; setPendingStatus(null); save(() => updateEngagement(engagement.id, { status: h, statusNote: note.trim() })); }}>
              Set {pendingStatus}
            </button>
            <button type="button" className="tw-btn-ghost" onClick={() => { setPendingStatus(null); setNote(engagement.statusNote); }}>Cancel</button>
            {!note.trim() && <span className="tw-td-sub" data-testid="status-note-hint">A {pendingStatus} needs a why before it saves.</span>}
          </>
        )}
      </div>
      {error && <p className="tw-error" data-testid="detail-error">{error}</p>}
    </section>
  );
}

function EngagementTasks({ engagement, editable, today, onNavigate, onRefresh }: {
  engagement: Engagement; editable: boolean; today: string;
  onNavigate: (r: string) => void; onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const base = `/engagements/${engagement.id}`;

  return (
    <>
      {editable && (!adding ? (
        <button type="button" className="tw-addbar" data-testid="engagement-add-task-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add task
        </button>
      ) : (
        <div className="tw-addform" data-testid="engagement-add-task-form">
          <input autoFocus placeholder="Task title" value={title} data-testid="engagement-task-title-input"
            onChange={(e) => setTitle(e.target.value)} className="tw-input" style={{ minWidth: 240 }} />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="tw-input" />
          <button type="button" className="tw-btn" data-testid="engagement-task-save-btn" disabled={busy || !title.trim()}
            onClick={() => run(async () => { await createEngagementTask(engagement.id, { title: title.trim(), dueDate: due }); setAdding(false); setTitle(""); setDue(""); })}>
            Save
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ))}
      {!editable && <p className="tw-subtle" data-testid="viewer-note">You have view-only access to this engagement.</p>}
      {error && <p className="tw-error">{error}</p>}

      {engagement.tasks.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">No tasks in this engagement yet.</div></section>
      ) : (
        <section className="tw-section">
          <table className="tw-table" data-testid="engagement-tasks-table">
            <thead><tr><th>Task</th><th>Status</th><th>Priority</th><th>Due</th>{editable && <th></th>}</tr></thead>
            <tbody>
              {engagement.tasks.map((t) => {
                const od = isOverdue(t, today);
                return (
                  <tr key={t.id} className="tw-rowlink" data-testid={`engagement-task-row-${t.id}`}
                    onClick={() => onNavigate(`${base}/tasks/${t.id}`)}>
                    <td className="tw-td-title">{t.title}</td>
                    <td><span className={`tw-badge ${t.status === "Done" ? "tw-badge-green" : t.status === "In progress" ? "tw-badge-orange" : t.status === "Blocked" ? "tw-badge-red" : "tw-badge-gray"}`}>{t.status}</span></td>
                    <td>{t.priority}</td>
                    <td className={od ? "tw-due-overdue" : ""}>{t.dueDate || "—"}{od ? " · overdue" : ""}</td>
                    {editable && (
                      <td onClick={(e) => e.stopPropagation()}>
                        <ArmedDelete testid={`engagement-task-delete-${t.id}`}
                          onConfirm={() => run(() => deleteEngagementTask(engagement.id, t.id))} />
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

function EngagementTaskDetail({ engagement, task, editable, onRefresh, onNavigate }: {
  engagement: Engagement; task: Task; editable: boolean;
  onRefresh: () => Promise<void>; onNavigate: (r: string) => void;
}) {
  const { busy, error, run } = useBusy(onRefresh);
  const base = `/engagements/${engagement.id}`;
  return (
    <section className="tw-section" data-testid="engagement-task-editor">
      <button type="button" className="tw-back" onClick={() => onNavigate(`${base}/tasks`)}><ArrowLeft size={14} /> All tasks</button>
      <h2 className="tw-h2" style={{ marginTop: 8 }}>{task.title}</h2>
      <div className="tw-stats">
        <StatBox label="Status" value={task.status} />
        <StatBox label="Priority" value={task.priority} />
        <StatBox label="Due" value={task.dueDate || "—"} />
      </div>
      {editable ? (
        <div className="tw-addform" style={{ marginTop: 12 }}>
          <select className="tw-input" value={task.status} data-testid="engagement-task-status" disabled={busy}
            onChange={(e) => run(() => updateEngagementTask(engagement.id, task.id, { status: e.target.value }))}>
            {["To do", "In progress", "Blocked", "Done"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className="tw-input" value={task.priority} data-testid="engagement-task-priority" disabled={busy}
            onChange={(e) => run(() => updateEngagementTask(engagement.id, task.id, { priority: e.target.value }))}>
            {["Low", "Medium", "High"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <input type="date" className="tw-input" value={(task.dueDate || "").slice(0, 10)} disabled={busy}
            onChange={(e) => run(() => updateEngagementTask(engagement.id, task.id, { dueDate: e.target.value }))} />
        </div>
      ) : (
        <p className="tw-subtle" data-testid="viewer-note">View-only: your role on this engagement is viewer.</p>
      )}
      {error && <p className="tw-error">{error}</p>}
    </section>
  );
}

function EngagementSettings({ engagement, myRole, onRefresh }: {
  engagement: Engagement; myRole: EngagementRole | null; onRefresh: () => Promise<void>;
}) {
  const isOwner = myRole === "owner";
  const [userId, setUserId] = useState("");
  const [userText, setUserText] = useState("");
  const [role, setRole] = useState<EngagementRole>("viewer");
  const [convText, setConvText] = useState("");
  const [directory, setDirectory] = useState<{ id: string; username: string; displayName: string }[]>([]);
  const { busy, error, run } = useBusy(onRefresh);
  useEffect(() => {
    if (!isOwner) return;
    listUsers().then(setDirectory).catch(() => setDirectory([]));
  }, [isOwner]);
  const candidates = directory.filter((u) => !engagement.members.some((m) => m.userId === u.id));
  // Free-text (username or u-<oid>) wins over the dropdown so Entra users are
  // reachable even before they appear in the directory the owner has loaded.
  const memberRef = userText.trim() || userId;

  return (
    <>
      <section className="tw-section">
        <h2 className="tw-h2"><Users size={14} /> Members</h2>
        <div className="tw-doclist" data-testid="member-list">
          {engagement.members.map((m) => (
            <div key={m.userId} className="tw-docitem" data-testid={`member-${m.userId}`}>
              <span className="tw-td-title">{m.userId}</span>
              <span className="tw-badge tw-badge-gray">{m.role}</span>
              {isOwner && m.role !== "owner" && (
                <span style={{ marginLeft: "auto" }}>
                  <ArmedDelete testid={`member-remove-${m.userId}`} onConfirm={() => run(() => removeEngagementMember(engagement.id, m.userId))} />
                </span>
              )}
            </div>
          ))}
        </div>
        {isOwner && (
          <div className="tw-addform" style={{ marginTop: 10 }} data-testid="add-member-form">
            <select className="tw-input" value={userId} onChange={(e) => setUserId(e.target.value)} data-testid="member-user-select">
              <option value="">Add member…</option>
              {candidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.displayName ? `${u.displayName} (${u.username || u.id})` : (u.username || u.id)}
                </option>
              ))}
            </select>
            <input className="tw-input" value={userText} placeholder="or username / user id"
              onChange={(e) => setUserText(e.target.value)} data-testid="member-user-input" />
            <select className="tw-input" value={role} onChange={(e) => setRole(e.target.value as EngagementRole)} data-testid="member-role-select">
              {(["viewer", "editor", "owner"] as const).map((r) => <option key={r}>{r}</option>)}
            </select>
            <button type="button" className="tw-btn" data-testid="member-add-btn" disabled={busy || !memberRef}
              onClick={() => run(async () => { await addEngagementMember(engagement.id, memberRef, role); setUserId(""); setUserText(""); })}>
              Add
            </button>
          </div>
        )}
      </section>

      <section className="tw-section">
        <h2 className="tw-h2"><SettingsIcon size={14} /> Conventions</h2>
        <p className="tw-subtle">Working agreements the assistant applies when it works in this engagement.</p>
        <div className="tw-doclist">
          {engagement.conventions.map((c) => (
            <div key={c.id} className="tw-docitem" data-testid={`convention-row-${c.id}`}>
              <span className="tw-td-sub">{c.text}</span>
              {canEdit(myRole) && (
                <span style={{ marginLeft: "auto" }}>
                  <ArmedDelete testid={`convention-delete-${c.id}`} onConfirm={() => run(() => removeConvention(engagement.id, c.id))} />
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
              onClick={() => run(async () => { await addConvention(engagement.id, convText.trim()); setConvText(""); })}>
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
function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Artifacts: durable files on the engagement. Any member can add and open (R10);
// removing needs editor+. Open streams through the authed API into an object URL —
// bytes never travel on an unauthenticated path.
function EngagementDocuments({ engagement, editable, onRefresh }: {
  engagement: Engagement; editable: boolean; onRefresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const artifacts: Artifact[] = engagement.library ?? [];

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true); setError("");
    try {
      await uploadEngagementArtifact(engagement.id, file);
      await onRefresh();
    } catch (e) {
      setError(friendlyError(e, "Artifact action failed."));
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const open = async (a: Artifact) => {
    setError("");
    try {
      const blob = await openEngagementArtifact(engagement.id, a.id);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      setError(friendlyError(e, "Artifact action failed."));
    }
  };

  const remove = async (a: Artifact) => {
    setError("");
    try {
      await deleteEngagementArtifact(engagement.id, a.id);
      await onRefresh();
    } catch (e) {
      setError(friendlyError(e, "Artifact action failed."));
    }
  };

  return (
    <section className="tw-section">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="tw-h2">Artifacts</h2>
        <div>
          <input ref={fileInput} type="file" data-testid="artifact-upload-input"
            style={{ display: "none" }} onChange={(e) => upload(e.target.files?.[0])} />
          <button type="button" className="tw-btn" data-testid="artifact-upload-btn" disabled={busy}
            onClick={() => fileInput.current?.click()}>
            <Upload size={13} /> {busy ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
      {error && <div className="tw-error" data-testid="artifact-error">{error}</div>}
      {artifacts.length === 0 ? (
        <div className="tw-empty-sm">No artifacts on this engagement yet.</div>
      ) : (
        <div className="tw-doclist">
          {artifacts.map((a) => (
            <div key={a.id} className="tw-docitem" data-testid={`artifact-row-${a.id}`}>
              <Files size={15} />
              <span className="tw-td-title" style={{ flex: 1 }}>{a.name}</span>
              <span className="tw-td-sub">{humanSize(a.size)}</span>
              <span className="tw-td-sub">{a.uploadedBy}</span>
              <span className="tw-td-sub">{(a.uploadedAt || "").slice(0, 10)}</span>
              <button type="button" className="tw-btn-ghost" data-testid={`artifact-open-${a.id}`}
                title="Open" onClick={() => open(a)}>
                <Download size={13} />
              </button>
              {editable && (
                <ArmedDelete testid={`artifact-delete-${a.id}`} onConfirm={() => remove(a)} />
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

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
