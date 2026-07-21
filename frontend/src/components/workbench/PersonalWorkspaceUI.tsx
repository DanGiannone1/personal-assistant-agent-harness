"use client";

// Shared presentational bits + a tiny mutation helper for the four personal-work
// screens (Home, Tasks, Calendar, Reminders). Kept local to this folder rather than
// imported from EngagementScreens.tsx, which does not export its equivalents.

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";
import type { Task, TaskPriority, TaskStatus } from "@/lib/types";
import { friendlyError } from "@/lib/utils";

export function isOverdue(task: Task, today: string): boolean {
  if (task.status === "Done") return false;
  const due = (task.dueDate || "").slice(0, 10);
  return !!due && due < today;
}

function statusClass(status: TaskStatus): string {
  switch (status) {
    case "Done": return "tw-badge-green";
    case "In progress": return "tw-badge-orange";
    case "Blocked": return "tw-badge-red";
    default: return "tw-badge-gray"; // To do
  }
}

export function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`tw-badge ${statusClass(status)}`}>{status}</span>;
}

export function PriorityBadge({ priority }: { priority: TaskPriority }) {
  const cls = priority === "High" ? "cell-pill-high" : priority === "Medium" ? "cell-pill-med" : "cell-pill-low";
  return <span className={`cell-pill ${cls}`}>{priority}</span>;
}

export function OverdueBadge() {
  return <span className="tw-badge tw-badge-red"><AlertTriangle size={11} strokeWidth={2.5} />Overdue</span>;
}

export function Stat({ label, value, testid }: { label: string; value: number | string; testid?: string }) {
  return (
    <div className="tw-stat" data-testid={testid}>
      <div className="tw-stat-value">{value}</div>
      <div className="tw-stat-label">{label}</div>
    </div>
  );
}

// "Today" / "Tomorrow" / weekday-date label for an ISO day vs. today. Formatted
// deterministically (fixed UTC + fixed names) so server prerender and client
// hydration always agree, regardless of the viewer's locale/timezone.
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function dayLabel(iso: string, today: string): string {
  if (iso === today) return "Today";
  const target = new Date(`${iso}T00:00:00Z`);
  const base = new Date(`${today}T00:00:00Z`);
  const diffDays = Math.round((target.getTime() - base.getTime()) / 86_400_000);
  if (diffDays === 1) return "Tomorrow";
  if (diffDays === -1) return "Yesterday";
  const [, month, day] = iso.split("-").map(Number);
  return `${WEEKDAYS[target.getUTCDay()]}, ${MONTHS[month - 1]} ${day}`;
}

export function absDate(iso: string): string {
  const target = new Date(`${iso}T00:00:00Z`);
  const [, month, day] = iso.split("-").map(Number);
  return `${WEEKDAYS[target.getUTCDay()]}, ${MONTHS[month - 1]} ${day}`;
}

// Every screen's mutations are AI-free CRUD calls against the owner-scoped session:
// run the call, surface a failure inline, then re-fetch authoritative app state.
export function usePersonalAction(onRefresh: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (action: () => Promise<unknown>): Promise<boolean> => {
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

// Destructive deletes require a deliberate two-step confirm (arm → confirm) so a
// stray click can't silently destroy a record.
export function ArmedDelete({ onConfirm, testid, label }: { onConfirm: () => void; testid: string; label: string }) {
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
  if (!armed) {
    return (
      <button
        ref={triggerRef}
        type="button"
        className="tw-btn-ghost"
        data-testid={testid}
        title={`Delete ${label}`}
        aria-label={`Delete ${label}`}
        onClick={(event) => { event.stopPropagation(); setArmed(true); }}
      >
        <Trash2 size={13} />
      </button>
    );
  }
  return (
    <span className="tw-confirm-actions" onClick={(event) => event.stopPropagation()}>
      <button
        ref={confirmRef}
        type="button"
        className="tw-btn"
        data-testid={`${testid}-confirm`}
        aria-label={`Confirm delete ${label}`}
        onClick={(event) => { event.stopPropagation(); cancel(); onConfirm(); }}
      >
        Confirm
      </button>
      <button
        type="button"
        className="tw-btn-ghost"
        data-testid={`${testid}-cancel`}
        aria-label="Cancel delete"
        onClick={(event) => { event.stopPropagation(); cancel(); }}
      >
        Cancel
      </button>
    </span>
  );
}
