"use client";

import { useState } from "react";
import { CheckCircle2, Activity, HelpCircle, AlertCircle, Sparkles, Circle, ChevronDown, ChevronRight } from "lucide-react";
import { MessagePart, ProductToolResult } from "@/lib/types";

function runningLabel(name: string): string {
  const labels: Record<string, string> = {
    navigate: "Navigating", create_task: "Creating task", update_task: "Updating task",
    delete_task: "Deleting task", add_subtask: "Adding subtask", list_tasks: "Reviewing tasks",
    create_event: "Creating event", update_event: "Updating event", delete_event: "Deleting event",
    list_events: "Reviewing events", search_documents: "Searching documents",
    list_documents: "Browsing documents",
    read_workspace_file: "Reading document", write_file: "Saving document", skill: "Loading skill",
    list_engagements: "Reviewing engagements", create_engagement: "Creating engagement", share_engagement: "Sharing engagement",
    propose_memory: "Proposing memory", save_memory: "Saving memory", delete_schedule: "Deleting reminder",
  };
  return labels[name] || "Working";
}

// Missing structured results stay neutral so the trace never overclaims.
function doneLabel(name: string, result: ProductToolResult | undefined): string {
  if (name === "skill") return "Skill loaded";  // skill loads carry no outcome by design
  if (!result) return "Outcome unavailable";
  if (["failed", "invalid", "not_found", "forbidden", "conflict"].includes(result.status)) return "Couldn't complete";
  if (["noop", "needs_confirmation", "ambiguous"].includes(result.status)) return "No change";
  if (["committed", "resolved", "succeeded"].includes(result.status)) return ({ navigate: "Navigated", create_engagement: "Engagement created", update_engagement: "Engagement updated", set_engagement_status: "Status updated", share_engagement: "Engagement shared", list_engagements: "Engagements reviewed" } as Record<string, string>)[name] || "Completed";
  return "Outcome unavailable";
}

function toolContext(name: string, args: string | undefined): string | null {
  if (!args) return null;
  try {
    const p = JSON.parse(args);
    switch (name) {
      case "navigate": return p.destination_id || null;
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

function StepIcon({ running, result, skill }: { running: boolean; result: ProductToolResult | undefined; skill: boolean }) {
  if (running) return <span className="step-ic step-ic-running"><Activity size={12} className="animate-pulse" /></span>;
  if (skill) return <span className="step-ic step-ic-skill"><Sparkles size={11} /></span>;
  if (["noop", "needs_confirmation", "ambiguous"].includes(result?.status ?? "")) return <span className="step-ic step-ic-noop"><HelpCircle size={12} /></span>;
  if (["failed", "invalid", "not_found", "forbidden", "conflict"].includes(result?.status ?? "")) return <span className="step-ic step-ic-error"><AlertCircle size={12} /></span>;
  if (!result) return <span className="step-ic step-ic-neutral"><Circle size={11} /></span>;
  return <span className="step-ic step-ic-ok"><CheckCircle2 size={12} /></span>;
}

function Step({ part }: { part: MessagePart & { type: "tool_call" } }) {
  const running = part.status === "running";
  const isSkill = part.tool === "skill";
  const label = running ? runningLabel(part.tool) : doneLabel(part.tool, part.result);
  const ctx = toolContext(part.tool, part.args);
  return (
    <div className="step-block">
      <div className={`step-row ${isSkill ? "step-row-skill" : ""}`}>
        <StepIcon running={running} result={part.result} skill={isSkill} />
        <span className="step-label">{label}</span>
        {ctx && <span className="step-ctx" title={ctx}>{ctx}</span>}
      </div>
    </div>
  );
}

export default function ToolTrace({ parts, isStreaming }: { parts: (MessagePart & { type: "tool_call" })[]; isStreaming?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  if (parts.length === 0) return null;

  const steps = (
    <div className="step-trace" data-testid="tool-trace">
      {parts.map((p) => <Step key={p.toolCallId} part={p} />)}
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
