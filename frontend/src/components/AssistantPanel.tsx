"use client";

import { useCallback, useMemo, useState } from "react";
import { Plus, Sparkles, FileText, ArrowRight } from "lucide-react";
import BespokeIcon from "./ui/BespokeIcon";
import GlassPanel from "./ui/GlassPanel";
import MessageList from "./MessageList";
import InputBar from "./InputBar";
import { useSession } from "./SessionProvider";

// The assistant chat surface, shared by the docked co-pilot and the dedicated
// workspace. It owns the new-session confirm modal so both surfaces behave identically.
// `headerActions` lets each surface add its own controls (expand/collapse, back-to-app).
// `onOpenWorkspace` (dock only) surfaces a compact artifact card so a generated deliverable
// isn't orphaned in the dock — one click opens it in the workspace canvas.
// Human "Tue, Jun 30" label for an ISO day (matches the workspace's date formatting;
// deterministic UTC + fixed names to avoid hydration mismatch).
const _WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const _MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function humanDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  const [, m, day] = iso.split("-").map(Number);
  return `${_WD[d.getUTCDay()]}, ${_MO[m - 1]} ${day}`;
}

export default function AssistantPanel({ headerActions, onOpenWorkspace }: { headerActions?: React.ReactNode; onOpenWorkspace?: () => void }) {
  const {
    state, statusMessage, isChatUploading, chatUploadName,
    handleSend, handleStop, handleChatUpload, doNewChat, startSession, navigateView,
  } = useSession();

  const [confirmNewChat, setConfirmNewChat] = useState(false);
  const agentWorking = state.isStreaming || isChatUploading;
  const artifacts = useMemo(() => state.files.filter((f) => f.origin === "generated"), [state.files]);
  // Instant quick-nav targets (the app's pages) — client-side, no agent.
  const quickNav = useMemo(() => (
    [
      { label: "Home", route: "/home" },
      { label: "Tasks", route: "/todo" },
      { label: "Calendar", route: "/calendar" },
      { label: "Documents", route: "/documents" },
      { label: "Reminders", route: "/reminders" },
    ]
  ), []);

  // "Needs attention" — overdue tasks, computed client-side so opening the assistant lands the
  // user on what matters with one click (no asking, no agent turn). Done = not overdue.
  const attention = useMemo(() => {
    const app = state.appState;
    if (!app) return [];
    const today = new Date().toISOString().slice(0, 10);
    return app.tasks
      .filter((t) => t.dueDate && t.dueDate.slice(0, 10) < today && t.status !== "Done")
      .slice(0, 4)
      .map((t) => ({ label: t.title, sublabel: `${t.group || "Task"} · due ${humanDay(t.dueDate!.slice(0, 10))}`, route: `/todo/${t.id}` }));
  }, [state.appState]);

  const handleNewChat = useCallback(() => {
    if (state.messages.length > 0) { setConfirmNewChat(true); return; }
    void doNewChat();
  }, [state.messages.length, doNewChat]);

  return (
    <div className="flex h-full flex-col gap-3 min-w-0">
      <header className="h-14 flex items-center justify-between px-5 bg-surface-1/70 backdrop-blur-2xl rounded-2xl border border-border-subtle shrink-0">
        <div className="flex items-center gap-2.5 font-bold tracking-tight">
          <div className={`p-1.5 rounded-lg bg-gradient-to-br from-brand-primary to-brand-accent relative ${agentWorking ? "agent-working" : ""}`}>
            <BespokeIcon icon={Sparkles} size={16} className="text-white" glowColor="rgba(255,255,255,0.4)" />
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-text-primary text-[15px]">Assistant</span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
              {agentWorking ? "Working…" : "Ready"}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="new-chat-button"
            onClick={handleNewChat}
            disabled={state.isStreaming || state.isInitializing || isChatUploading}
            className="interactive-control inline-flex items-center justify-center rounded-xl bg-surface-2 border border-border-subtle px-3.5 py-2 text-[11px] font-bold uppercase tracking-widest text-text-secondary hover:text-text-primary hover:border-brand-primary transition-all disabled:opacity-45"
          >
            <Plus size={14} strokeWidth={3} className="mr-1" />
            New Session
          </button>
          {headerActions}
        </div>
      </header>

      <GlassPanel variant="light" className="flex-1 flex flex-col min-h-0">
        {state.sessionError ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <p className="text-sm text-text-muted">{state.sessionError}</p>
            <button type="button" onClick={() => void startSession()} className="interactive-control rounded-xl bg-brand-primary px-4 py-2 text-xs font-bold uppercase tracking-widest text-white">Retry</button>
          </div>
        ) : (
          <>
            <MessageList
              messages={state.messages}
              onSuggestion={state.isStreaming || state.isInitializing ? undefined : handleSend}
              quickNav={quickNav}
              onQuickNav={navigateView}
              attention={attention}
            />
            {statusMessage && <div className="px-5 pb-1 text-[11px] text-text-muted">{statusMessage}</div>}
            {onOpenWorkspace && artifacts.length > 0 && (
              <button
                type="button"
                data-testid="dock-artifact-card"
                onClick={onOpenWorkspace}
                className="interactive-control mx-4 mb-2 flex items-center gap-3 rounded-xl border border-brand-primary/40 bg-surface-2/60 px-3.5 py-2.5 text-left hover:border-brand-primary transition-all"
              >
                <span className="p-1.5 rounded-lg bg-brand-primary/15 text-brand-accent shrink-0"><FileText size={15} /></span>
                <span className="flex flex-col min-w-0 flex-1">
                  <span className="text-[12px] font-semibold text-text-primary truncate">{artifacts[0].filename}</span>
                  <span className="text-[10px] uppercase tracking-widest text-text-muted">{artifacts.length} artifact{artifacts.length === 1 ? "" : "s"} · open in workspace</span>
                </span>
                <ArrowRight size={15} className="text-text-muted shrink-0" />
              </button>
            )}
            <InputBar
              onSend={handleSend}
              onUpload={handleChatUpload}
              disabled={state.isStreaming || state.isInitializing}
              isStreaming={state.isStreaming}
              onStop={handleStop}
              isUploadingFile={isChatUploading}
              uploadingFileName={chatUploadName}
            />
          </>
        )}
      </GlassPanel>

      {confirmNewChat && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-app/80 backdrop-blur-md px-4" onClick={() => setConfirmNewChat(false)}>
          <div className="w-full max-w-sm rounded-[2rem] border border-border-subtle bg-surface-1 p-8 shadow-[0_24px_60px_rgba(0,0,0,0.15)] relative overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="absolute top-0 inset-x-0 h-1 bg-brand-primary" />
            <h2 className="text-lg font-bold text-text-primary uppercase tracking-wide">New session?</h2>
            <p className="mt-3 text-sm text-text-muted leading-relaxed">This clears the current conversation and resets the workspace to seed data.</p>
            <div className="mt-8 flex flex-col gap-2">
              <button type="button" onClick={() => { setConfirmNewChat(false); void doNewChat(); }} className="interactive-control w-full rounded-xl bg-brand-primary py-3 text-xs font-bold uppercase tracking-widest text-white hover:brightness-110">Start new session</button>
              <button type="button" onClick={() => setConfirmNewChat(false)} className="interactive-control w-full rounded-xl border border-border-subtle py-3 text-xs font-bold uppercase tracking-widest text-text-muted hover:bg-surface-2">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
