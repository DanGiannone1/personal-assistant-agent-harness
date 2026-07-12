"use client";

import { useState } from "react";
import { CheckCircle2, Activity, HelpCircle, AlertCircle, Sparkles, Circle, ChevronDown, ChevronRight } from "lucide-react";
import { MessagePart, ToolCard, ToolOutcome } from "@/lib/types";

function runningLabel(name: string): string {
  const labels: Record<string, string> = {
    navigate: "Navigating", create_task: "Creating task", update_task: "Updating task",
    delete_task: "Deleting task", add_subtask: "Adding subtask", list_tasks: "Reviewing tasks",
    create_event: "Creating event", update_event: "Updating event", delete_event: "Deleting event",
    list_events: "Reviewing events", search_documents: "Searching documents",
    list_documents: "Browsing documents",
    read_workspace_file: "Reading document", write_file: "Saving document", skill: "Loading skill",
    list_projects: "Reviewing projects", create_project: "Creating project", share_project: "Sharing project",
    propose_memory: "Proposing memory", save_memory: "Saving memory", delete_schedule: "Deleting reminder",
  };
  return labels[name] || "Working";
}

// outcome may be undefined if the result signal was lost — fail closed: show a
// neutral "Done", never a green success, so the trace never overclaims.
function doneLabel(name: string, outcome: ToolOutcome | undefined): string {
  if (name === "skill") return "Skill loaded";  // skill loads carry no outcome by design
  if (outcome === "noop") {
    return ({ navigate: "Needs clarification", update_task: "No changes", update_event: "No changes",
      delete_task: "Awaiting confirmation", delete_event: "Awaiting confirmation",
      delete_schedule: "Awaiting confirmation", propose_memory: "Awaiting confirmation" } as Record<string, string>)[name] || "No change";
  }
  if (outcome === "error") {
    return ({ navigate: "Destination not found", update_task: "Task not found", delete_task: "Task not found", add_subtask: "Task not found", create_task: "Couldn't create task", update_event: "Event not found", delete_event: "Event not found", create_event: "Couldn't create event", search_documents: "Search not configured" } as Record<string, string>)[name] || "Couldn't complete";
  }
  if (outcome === undefined) return "Done";
  const labels: Record<string, string> = {
    navigate: "Navigated", create_task: "Task created", update_task: "Task updated",
    list_projects: "Projects reviewed", create_project: "Project created", share_project: "Project shared",
    save_memory: "Memory saved", delete_schedule: "Reminder deleted",
    delete_task: "Task deleted", add_subtask: "Subtask added", list_tasks: "Tasks reviewed",
    create_event: "Event created", update_event: "Event updated", delete_event: "Event deleted",
    list_events: "Events reviewed", search_documents: "Documents searched",
    list_documents: "Documents listed",
    read_workspace_file: "Document read", write_file: "Document saved", skill: "Skill loaded",
  };
  return labels[name] || "Done";
}

function toolContext(name: string, args: string | undefined): string | null {
  if (!args) return null;
  try {
    const p = JSON.parse(args);
    switch (name) {
      case "navigate": return p.destination || null;
      case "create_task": return p.title ? `${p.title}${p.priority ? ` · ${p.priority}` : ""}` : null;
      case "update_task": case "delete_task": case "add_subtask": return p.task || null;
      case "create_event": return p.title ? `${p.title}${p.date ? ` · ${p.date}` : ""}` : null;
      case "update_event": case "delete_event": return p.event || null;
      case "search_documents": return p.query || null;
      case "read_workspace_file": return p.path || "uploaded document";
      case "write_file": return p.path || null;
      case "skill": return p.name || null;
      default: return null;
    }
  } catch { return null; }
}

function StepIcon({ running, outcome, skill }: { running: boolean; outcome: ToolOutcome | undefined; skill: boolean }) {
  if (running) return <span className="step-ic step-ic-running"><Activity size={12} className="animate-pulse" /></span>;
  if (skill) return <span className="step-ic step-ic-skill"><Sparkles size={11} /></span>;
  if (outcome === "noop") return <span className="step-ic step-ic-noop"><HelpCircle size={12} /></span>;
  if (outcome === "error") return <span className="step-ic step-ic-error"><AlertCircle size={12} /></span>;
  if (outcome === undefined) return <span className="step-ic step-ic-neutral"><Circle size={11} /></span>;
  return <span className="step-ic step-ic-ok"><CheckCircle2 size={12} /></span>;
}

function CardView({ card, onPick }: { card: ToolCard; onPick?: (text: string) => void }) {
  if (card.kind === "confirm") {
    return (
      <div className="step-card step-card-confirm" data-testid="confirm-card">
        <div className="step-card-title">{card.title}</div>
        {card.detail && <div className="step-card-detail">{card.detail}</div>}
        <div className="step-card-actions">
          <button type="button" className="step-card-btn step-card-btn-primary" disabled={!onPick}
            data-testid="confirm-card-yes"
            onClick={() => onPick?.("Yes — confirmed, go ahead.")}>
            Confirm
          </button>
          <button type="button" className="step-card-btn" disabled={!onPick}
            data-testid="confirm-card-no"
            onClick={() => onPick?.("No — cancel that.")}>
            Cancel
          </button>
        </div>
      </div>
    );
  }
  const fields = card.fields ?? {};
  return (
    <div className="step-card" data-testid="record-card">
      <div className="step-card-title">{fields.title ?? card.recordKind}</div>
      <div className="step-card-fields">
        {Object.entries(fields).filter(([k]) => k !== "title").map(([k, v]) => (
          <span key={k} className="step-card-field"><b>{k}</b> {v}</span>
        ))}
        {card.scope && <span className="step-card-field"><b>scope</b> {card.scope}</span>}
      </div>
    </div>
  );
}

function Step({ part, onPick }: { part: MessagePart & { type: "tool_call" }; onPick?: (text: string) => void }) {
  const running = part.status === "running";
  const isSkill = part.tool === "skill";
  const label = running ? runningLabel(part.tool) : doneLabel(part.tool, part.outcome);
  const ctx = toolContext(part.tool, part.args);
  const candidates = !running ? part.candidates ?? [] : [];
  return (
    <div className="step-block">
      <div className={`step-row ${isSkill ? "step-row-skill" : ""}`}>
        <StepIcon running={running} outcome={part.outcome} skill={isSkill} />
        <span className="step-label">{label}</span>
        {ctx && <span className="step-ctx" title={ctx}>{ctx}</span>}
      </div>
      {!running && part.card && <CardView card={part.card} onPick={onPick} />}
      {candidates.length > 0 && (
        <div className="step-candidates">
          {candidates.map((c) => (
            <button key={c} type="button" className="step-candidate" disabled={!onPick}
              onClick={() => onPick?.(`Take me to ${c}`)} data-testid={`nav-candidate-${c.replace(/\s+/g, "-")}`}>
              {c}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ToolTrace({ parts, isStreaming, onPick }: { parts: (MessagePart & { type: "tool_call" })[]; isStreaming?: boolean; onPick?: (text: string) => void }) {
  const [collapsed, setCollapsed] = useState(false);
  if (parts.length === 0) return null;

  const steps = (
    <div className="step-trace" data-testid="tool-trace">
      {parts.map((p) => <Step key={p.toolCallId} part={p} onPick={onPick} />)}
    </div>
  );

  // Single-step turns stay clean — no collapsible header. Multi-step turns get a
  // collapsible section header (like the reference UI). Keep it open while streaming.
  if (parts.length < 2) return steps;

  const open = isStreaming || !collapsed;
  return (
    <div className="step-group">
      <button
        type="button"
        className="step-group-header"
        onClick={() => setCollapsed((c) => !c)}
        aria-expanded={open}
        data-testid="step-group-toggle"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>Worked through {parts.length} steps</span>
      </button>
      {open && steps}
    </div>
  );
}
