"use client";

import { useState } from "react";
import { CheckCircle2, Activity, HelpCircle, AlertCircle, Sparkles, Circle, ChevronDown, ChevronRight } from "lucide-react";
import { MessagePart, ProductToolResult } from "@/lib/types";

function runningLabel(name: string): string {
  const labels: Record<string, string> = {
    navigate: "Navigating",
    list_engagements: "Reviewing engagements",
    create_engagement: "Creating engagement",
    get_engagement: "Reviewing engagement",
    update_engagement: "Updating engagement",
    set_engagement_status: "Updating status",
    share_engagement: "Sharing engagement",
    skill: "Loading skill",
  };
  return labels[name] || "Working";
}

// Missing structured results stay neutral so the trace never overclaims.
function doneLabel(name: string, result: ProductToolResult | undefined): string {
  if (name === "skill") return "Skill loaded";  // skill loads carry no outcome by design
  if (!result) return "Outcome unavailable";
  if (["failed", "invalid", "not_found", "forbidden", "conflict"].includes(result.status)) return "Couldn't complete";
  if (["noop", "needs_confirmation", "ambiguous"].includes(result.status)) return "No change";
  if (["committed", "resolved", "succeeded"].includes(result.status)) return ({ navigate: "Navigated", create_engagement: "Engagement created", get_engagement: "Engagement reviewed", update_engagement: "Engagement updated", set_engagement_status: "Status updated", share_engagement: "Engagement shared", list_engagements: "Engagements reviewed" } as Record<string, string>)[name] || "Completed";
  return "Outcome unavailable";
}

function toolContext(name: string, args: string | undefined): string | null {
  if (!args) return null;
  try {
    const p = JSON.parse(args);
    switch (name) {
      case "navigate": return p.destination_id || null;
      case "create_engagement": return p.name || null;
      case "get_engagement": case "update_engagement": case "set_engagement_status": return p.engagement_id || null;
      case "share_engagement": return p.user || null;
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
