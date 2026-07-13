"use client";

// Engagement screens: list, overview, tasks, calendar, documents, settings.
// Role-aware: mutation controls render only for editor+; member management for owners.
// All mutations go through the typed REST API then onRefresh() re-reads /app/state —
// the pane never renders from its own optimism (same invariant as everywhere else).

import { useState } from "react";
import {
  AlertTriangle, ArrowLeft, Calendar as CalendarIcon, CheckSquare, Files, FolderKanban,
  Plus, Settings as SettingsIcon, Target, Trash2, Users,
} from "lucide-react";
import type {
  AppState, Engagement, EngagementHealth, EngagementRole, Task,
} from "@/lib/types";
import {
  addConvention, addEngagementItem, addEngagementMember, createEngagement, createEngagementEvent,
  createEngagementTask, deleteEngagementEvent, deleteEngagementItem, deleteEngagementTask,
  removeConvention, removeEngagementMember, updateEngagement, updateEngagementItem, updateEngagementTask,
} from "@/lib/api";
import { friendlyError } from "@/lib/utils";

const STAGES = ["Discovery", "Design", "Build", "Deploy", "Live", "Closed"] as const;
const MILESTONE_STATUSES = ["Planned", "In progress", "Done", "Slipped"] as const;
const RISK_STATUSES = ["Open", "Mitigating", "Closed"] as const;
const RISK_SEVERITIES = ["Low", "Medium", "High"] as const;
const ACTION_STATUSES = ["Open", "Done"] as const;

function healthClass(health: EngagementHealth): string {
  return health === "red" ? "tw-badge-red" : health === "amber" ? "tw-badge-orange" : "tw-badge-green";
}

function HealthBadge({ health, testid }: { health: EngagementHealth; testid?: string }) {
  return <span className={`tw-badge ${healthClass(health)}`} data-testid={testid}>{health}</span>;
}

// Done/Closed/Live are "settled" states; In progress/Mitigating are live; Slipped is trouble.
function engStatusClass(status: string): string {
  if (status === "Done" || status === "Closed" || status === "Live") return "tw-badge-green";
  if (status === "In progress" || status === "Mitigating") return "tw-badge-orange";
  if (status === "Slipped") return "tw-badge-red";
  return "tw-badge-gray";
}

const openRisks = (p: Engagement) => (p.risks ?? []).filter((r) => r.status !== "Closed").length;
const openActions = (p: Engagement) => (p.actions ?? []).filter((a) => a.status !== "Done").length;
const milestonesDone = (p: Engagement) => (p.milestones ?? []).filter((m) => m.status === "Done").length;

const KNOWN_USERS = ["dan", "ava", "sam"];

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
      <p className="tw-subtle">Shared customer-delivery workspaces — stage, health, milestones, risks, and the team&apos;s records in one place.</p>

      <div className="tw-stats" style={{ marginTop: 14 }}>
        <StatBox label="Engagements" value={engagements.length} testid="eng-stat-total" />
        <StatBox label="Red" value={engagements.filter((p) => p.health === "red").length} testid="eng-stat-red" />
        <StatBox label="Amber" value={engagements.filter((p) => p.health === "amber").length} testid="eng-stat-amber" />
        <StatBox label="Open risks" value={engagements.reduce((n, p) => n + openRisks(p), 0)} testid="eng-stat-risks" />
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
                      {p.healthNote ? `${p.healthNote.slice(0, 80)}${p.healthNote.length > 80 ? "…" : ""}` : p.description || "—"}
                    </span>
                  </span>
                  <span style={{ marginLeft: "auto" }} className="flex items-center gap-2">
                    <HealthBadge health={p.health} testid={`engagement-health-${p.id}`} />
                    <span className="tw-badge tw-badge-gray">{p.stage}</span>
                    <span className="tw-badge tw-badge-gray" data-testid={`engagement-role-${p.id}`}>{role}</span>
                    <span className="tw-td-sub"><Target size={12} style={{ display: "inline" }} /> {milestonesDone(p)}/{(p.milestones ?? []).length}</span>
                    <span className="tw-td-sub"><AlertTriangle size={12} style={{ display: "inline" }} /> {openRisks(p)}</span>
                    <span className="tw-td-sub"><Users size={12} style={{ display: "inline" }} /> {p.members.length}</span>
                    <span className="tw-td-sub"><CheckSquare size={12} style={{ display: "inline" }} /> {p.tasks.length}</span>
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
      {[["", "Overview"], ["tasks", "Tasks"], ["calendar", "Calendar"], ["documents", "Documents"], ["settings", "Settings"]].map(([key, label]) => (
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
        <HealthBadge health={engagement.health} testid="engagement-health-badge" />
        <span className="tw-badge tw-badge-gray" data-testid="engagement-stage-badge">{engagement.stage}</span>
        <span className="tw-badge tw-badge-gray" data-testid="my-role">{role}</span>
        {engagement.customer && <span className="tw-td-sub">{engagement.customer}</span>}
        <span className="tw-subtle">{engagement.description}</span>
      </div>
      {engagement.healthNote && (
        <p className="tw-subtle" data-testid="engagement-health-note" style={{ marginTop: 4 }}>
          {engagement.health !== "green" ? "Why: " : ""}{engagement.healthNote}
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

  if (sub === "calendar") {
    return (
      <div className="tw-screen" data-testid="engagement-calendar-screen">
        {header}
        <EngagementCalendar engagement={engagement} editable={editable} today={today} onRefresh={onRefresh} />
      </div>
    );
  }

  if (sub === "documents") {
    return (
      <div className="tw-screen" data-testid="engagement-documents-screen">
        {header}
        <section className="tw-section">
          <h2 className="tw-h2">Engagement documents</h2>
          {engagement.library.length === 0 ? (
            <div className="tw-empty-sm">No documents saved to this engagement yet.</div>
          ) : (
            <div className="tw-doclist">
              {engagement.library.map((d) => (
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
        <StatBox label="Milestones" value={`${milestonesDone(engagement)}/${(engagement.milestones ?? []).length}`} testid="stat-milestones" />
        <StatBox label="Open risks" value={openRisks(engagement)} testid="stat-risks" />
        <StatBox label="Open actions" value={openActions(engagement)} testid="stat-actions" />
        <StatBox label="Tasks" value={engagement.tasks.length} />
        <StatBox label="Overdue" value={overdue} />
        <StatBox label="Members" value={engagement.members.length} />
      </div>
      <EngagementDetailEditor key={engagement.id} engagement={engagement} editable={editable} onRefresh={onRefresh} />
      <MilestoneSection engagement={engagement} editable={editable} onRefresh={onRefresh} />
      <RiskSection engagement={engagement} editable={editable} onRefresh={onRefresh} />
      <ActionSection engagement={engagement} editable={editable} onRefresh={onRefresh} />
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

// Delivery-record editor: customer/stage/dates save on change; health is HELD locally
// when moving to amber/red until a non-empty why is entered, then both commit together —
// the same rule the tool layer (NOTE_REQUIRED) and REST (422) enforce.
function EngagementDetailEditor({ engagement, editable, onRefresh }: {
  engagement: Engagement; editable: boolean; onRefresh: () => Promise<void>;
}) {
  const { busy, error, run } = useBusy(onRefresh);
  const [saved, setSaved] = useState(false);
  const [pendingHealth, setPendingHealth] = useState<EngagementHealth | null>(null);
  const [note, setNote] = useState(engagement.healthNote);
  if (!editable) return null;

  const save = async (fn: () => Promise<unknown>) => {
    setSaved(false);
    await run(fn);
    setSaved(true);
  };
  const shownHealth = pendingHealth ?? engagement.health;
  const noteVisible = pendingHealth !== null || engagement.health !== "green";

  return (
    <section className="tw-section" data-testid="engagement-detail-editor">
      <h2 className="tw-h2">Delivery record</h2>
      <div className="tw-addform">
        <input className="tw-input" placeholder="Customer" defaultValue={engagement.customer}
          data-testid="engagement-customer-edit" disabled={busy} style={{ minWidth: 180 }}
          onBlur={(e) => { const v = e.target.value.trim(); if (v !== engagement.customer) save(() => updateEngagement(engagement.id, { customer: v })); }} />
        <select className="tw-input" value={engagement.stage} data-testid="engagement-stage-select" disabled={busy}
          onChange={(e) => save(() => updateEngagement(engagement.id, { stage: e.target.value }))}>
          {STAGES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <input type="date" className="tw-input" title="Start date" defaultValue={engagement.startDate} disabled={busy}
          onChange={(e) => save(() => updateEngagement(engagement.id, { startDate: e.target.value }))} />
        <input type="date" className="tw-input" title="Target date" defaultValue={engagement.targetDate} disabled={busy}
          data-testid="engagement-target-edit"
          onChange={(e) => save(() => updateEngagement(engagement.id, { targetDate: e.target.value }))} />
        <span className="tw-td-sub" data-testid="detail-save-state">{busy ? "Saving…" : error ? "" : saved ? "Saved ✓" : ""}</span>
      </div>
      <div className="tw-addform" style={{ marginTop: 8 }}>
        <select className="tw-input" value={shownHealth} data-testid="health-select" disabled={busy}
          onChange={(e) => {
            const v = e.target.value as EngagementHealth;
            if (v === "green") { setPendingHealth(null); save(() => updateEngagement(engagement.id, { health: "green", healthNote: "" })); }
            else { setPendingHealth(v); setNote(engagement.healthNote); }
          }}>
          {(["green", "amber", "red"] as const).map((h) => <option key={h}>{h}</option>)}
        </select>
        {noteVisible && (
          <input className="tw-input" placeholder="Why? (required for amber/red)" value={note}
            data-testid="health-note-input" disabled={busy} style={{ minWidth: 320 }}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => {
              if (pendingHealth === null && note.trim() && note.trim() !== engagement.healthNote)
                save(() => updateEngagement(engagement.id, { healthNote: note.trim() }));
            }} />
        )}
        {pendingHealth !== null && (
          <>
            <button type="button" className="tw-btn" data-testid="health-commit-btn" disabled={busy || !note.trim()}
              onClick={() => { const h = pendingHealth; setPendingHealth(null); save(() => updateEngagement(engagement.id, { health: h, healthNote: note.trim() })); }}>
              Set {pendingHealth}
            </button>
            <button type="button" className="tw-btn-ghost" onClick={() => { setPendingHealth(null); setNote(engagement.healthNote); }}>Cancel</button>
            {!note.trim() && <span className="tw-td-sub" data-testid="health-note-hint">A {pendingHealth} needs a why before it saves.</span>}
          </>
        )}
      </div>
      {error && <p className="tw-error" data-testid="detail-error">{error}</p>}
    </section>
  );
}

function MilestoneSection({ engagement, editable, onRefresh }: {
  engagement: Engagement; editable: boolean; onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const items = engagement.milestones ?? [];

  return (
    <section className="tw-section" data-testid="milestone-section">
      <h2 className="tw-h2"><Target size={14} /> Milestones</h2>
      {editable && (!adding ? (
        <button type="button" className="tw-addbar" data-testid="add-milestone-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add milestone
        </button>
      ) : (
        <div className="tw-addform">
          <input autoFocus placeholder="Milestone title" value={title} data-testid="milestone-title-input"
            onChange={(e) => setTitle(e.target.value)} className="tw-input" style={{ minWidth: 240 }} />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="tw-input" data-testid="milestone-due-input" />
          <button type="button" className="tw-btn" data-testid="milestone-save-btn" disabled={busy || !title.trim()}
            onClick={() => run(async () => { await addEngagementItem(engagement.id, "milestone", { title: title.trim(), dueDate: due }); setAdding(false); setTitle(""); setDue(""); })}>
            Save
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ))}
      {error && <p className="tw-error">{error}</p>}
      {items.length === 0 ? (
        <div className="tw-empty-sm">No milestones yet.</div>
      ) : (
        <table className="tw-table" data-testid="milestones-table">
          <thead><tr><th>Milestone</th><th>Due</th><th>Status</th>{editable && <th></th>}</tr></thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id} data-testid={`milestone-row-${m.id}`}>
                <td className="tw-td-title">{m.title}</td>
                <td>{m.dueDate || "—"}</td>
                <td>
                  {editable ? (
                    <select className="tw-input" value={m.status} data-testid={`milestone-status-${m.id}`} disabled={busy}
                      onChange={(e) => run(() => updateEngagementItem(engagement.id, "milestone", m.id, { status: e.target.value }))}>
                      {MILESTONE_STATUSES.map((s) => <option key={s}>{s}</option>)}
                    </select>
                  ) : (
                    <span className={`tw-badge ${engStatusClass(m.status)}`}>{m.status}</span>
                  )}
                </td>
                {editable && (
                  <td><ArmedDelete testid={`milestone-delete-${m.id}`}
                    onConfirm={() => run(() => deleteEngagementItem(engagement.id, "milestone", m.id))} /></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function RiskSection({ engagement, editable, onRefresh }: {
  engagement: Engagement; editable: boolean; onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("Medium");
  const [owner, setOwner] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const items = engagement.risks ?? [];

  return (
    <section className="tw-section" data-testid="risk-section">
      <h2 className="tw-h2"><AlertTriangle size={14} /> Risks</h2>
      {editable && (!adding ? (
        <button type="button" className="tw-addbar" data-testid="add-risk-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add risk
        </button>
      ) : (
        <div className="tw-addform">
          <input autoFocus placeholder="Risk title" value={title} data-testid="risk-title-input"
            onChange={(e) => setTitle(e.target.value)} className="tw-input" style={{ minWidth: 240 }} />
          <select className="tw-input" value={severity} data-testid="risk-severity-input" onChange={(e) => setSeverity(e.target.value)}>
            {RISK_SEVERITIES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <input placeholder="Owner" value={owner} onChange={(e) => setOwner(e.target.value)} className="tw-input" style={{ minWidth: 120 }} />
          <button type="button" className="tw-btn" data-testid="risk-save-btn" disabled={busy || !title.trim()}
            onClick={() => run(async () => { await addEngagementItem(engagement.id, "risk", { title: title.trim(), severity, owner: owner.trim() }); setAdding(false); setTitle(""); setOwner(""); })}>
            Save
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ))}
      {error && <p className="tw-error">{error}</p>}
      {items.length === 0 ? (
        <div className="tw-empty-sm">No risks logged.</div>
      ) : (
        <table className="tw-table" data-testid="risks-table">
          <thead><tr><th>Risk</th><th>Severity</th><th>Status</th><th>Owner</th><th>Mitigation</th>{editable && <th></th>}</tr></thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.id} data-testid={`risk-row-${r.id}`}>
                <td className="tw-td-title">{r.title}</td>
                <td><span className={`tw-badge ${r.severity === "High" ? "tw-badge-red" : r.severity === "Medium" ? "tw-badge-orange" : "tw-badge-gray"}`}>{r.severity}</span></td>
                <td>
                  {editable ? (
                    <select className="tw-input" value={r.status} data-testid={`risk-status-${r.id}`} disabled={busy}
                      onChange={(e) => run(() => updateEngagementItem(engagement.id, "risk", r.id, { status: e.target.value }))}>
                      {RISK_STATUSES.map((s) => <option key={s}>{s}</option>)}
                    </select>
                  ) : (
                    <span className={`tw-badge ${engStatusClass(r.status)}`}>{r.status}</span>
                  )}
                </td>
                <td>{r.owner || "—"}</td>
                <td className="tw-td-sub">{r.mitigation || "—"}</td>
                {editable && (
                  <td><ArmedDelete testid={`risk-delete-${r.id}`}
                    onConfirm={() => run(() => deleteEngagementItem(engagement.id, "risk", r.id))} /></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ActionSection({ engagement, editable, onRefresh }: {
  engagement: Engagement; editable: boolean; onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const items = engagement.actions ?? [];

  return (
    <section className="tw-section" data-testid="action-section">
      <h2 className="tw-h2"><CheckSquare size={14} /> Actions</h2>
      {editable && (!adding ? (
        <button type="button" className="tw-addbar" data-testid="add-action-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add action
        </button>
      ) : (
        <div className="tw-addform">
          <input autoFocus placeholder="Action title" value={title} data-testid="action-title-input"
            onChange={(e) => setTitle(e.target.value)} className="tw-input" style={{ minWidth: 240 }} />
          <input placeholder="Owner" value={owner} onChange={(e) => setOwner(e.target.value)} className="tw-input" style={{ minWidth: 120 }} />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="tw-input" />
          <button type="button" className="tw-btn" data-testid="action-save-btn" disabled={busy || !title.trim()}
            onClick={() => run(async () => { await addEngagementItem(engagement.id, "action", { title: title.trim(), owner: owner.trim(), dueDate: due }); setAdding(false); setTitle(""); setOwner(""); setDue(""); })}>
            Save
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ))}
      {error && <p className="tw-error">{error}</p>}
      {items.length === 0 ? (
        <div className="tw-empty-sm">No open actions.</div>
      ) : (
        <table className="tw-table" data-testid="actions-table">
          <thead><tr><th>Action</th><th>Owner</th><th>Due</th><th>Status</th>{editable && <th></th>}</tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id} data-testid={`action-row-${a.id}`}>
                <td className="tw-td-title">{a.title}</td>
                <td>{a.owner || "—"}</td>
                <td>{a.dueDate || "—"}</td>
                <td>
                  {editable ? (
                    <select className="tw-input" value={a.status} data-testid={`action-status-${a.id}`} disabled={busy}
                      onChange={(e) => run(() => updateEngagementItem(engagement.id, "action", a.id, { status: e.target.value }))}>
                      {ACTION_STATUSES.map((s) => <option key={s}>{s}</option>)}
                    </select>
                  ) : (
                    <span className={`tw-badge ${engStatusClass(a.status)}`}>{a.status}</span>
                  )}
                </td>
                {editable && (
                  <td><ArmedDelete testid={`action-delete-${a.id}`}
                    onConfirm={() => run(() => deleteEngagementItem(engagement.id, "action", a.id))} /></td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
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

function EngagementCalendar({ engagement, editable, today, onRefresh }: {
  engagement: Engagement; editable: boolean; today: string; onRefresh: () => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const events = [...engagement.events].sort((a, b) => ((a.date || "") < (b.date || "") ? -1 : 1));

  return (
    <>
      {editable && (!adding ? (
        <button type="button" className="tw-addbar" data-testid="engagement-add-event-btn" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add event
        </button>
      ) : (
        <div className="tw-addform">
          <input autoFocus placeholder="Event title" value={title} data-testid="engagement-event-title-input"
            onChange={(e) => setTitle(e.target.value)} className="tw-input" style={{ minWidth: 220 }} />
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="tw-input" data-testid="engagement-event-date-input" />
          <button type="button" className="tw-btn" data-testid="engagement-event-save-btn" disabled={busy || !title.trim() || !date}
            onClick={() => run(async () => { await createEngagementEvent(engagement.id, { title: title.trim(), date }); setAdding(false); setTitle(""); setDate(""); })}>
            Save
          </button>
          <button type="button" className="tw-btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ))}
      {error && <p className="tw-error">{error}</p>}
      {events.length === 0 ? (
        <section className="tw-section"><div className="tw-empty-sm">Nothing scheduled in this engagement yet.</div></section>
      ) : (
        <section className="tw-section">
          <div className="tw-doclist">
            {events.map((e) => (
              <div key={e.id} className="tw-docitem" data-testid={`engagement-event-${e.id}`}>
                <CalendarIcon size={15} />
                <span className="flex min-w-0 flex-col">
                  <span className="tw-td-title">{e.title}</span>
                  <span className="tw-td-sub">{e.date}{e.start ? ` · ${e.start}${e.end ? `–${e.end}` : ""}` : ""} · {e.type || "Meeting"}{e.date === today ? " · today" : ""}</span>
                </span>
                {editable && (
                  <span style={{ marginLeft: "auto" }}>
                    <ArmedDelete testid={`engagement-event-delete-${e.id}`} onConfirm={() => run(() => deleteEngagementEvent(engagement.id, e.id))} />
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

function EngagementSettings({ engagement, myRole, onRefresh }: {
  engagement: Engagement; myRole: EngagementRole | null; onRefresh: () => Promise<void>;
}) {
  const isOwner = myRole === "owner";
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<EngagementRole>("viewer");
  const [convText, setConvText] = useState("");
  const { busy, error, run } = useBusy(onRefresh);
  const candidates = KNOWN_USERS.filter((u) => !engagement.members.some((m) => m.userId === u));

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
              {candidates.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
            <select className="tw-input" value={role} onChange={(e) => setRole(e.target.value as EngagementRole)} data-testid="member-role-select">
              {(["viewer", "editor", "owner"] as const).map((r) => <option key={r}>{r}</option>)}
            </select>
            <button type="button" className="tw-btn" data-testid="member-add-btn" disabled={busy || !userId}
              onClick={() => run(async () => { await addEngagementMember(engagement.id, userId, role); setUserId(""); })}>
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
