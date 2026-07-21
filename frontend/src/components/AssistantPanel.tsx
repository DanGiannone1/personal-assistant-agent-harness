"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
export default function AssistantPanel({ headerActions, onOpenWorkspace }: { headerActions?: React.ReactNode; onOpenWorkspace?: () => void }) {
  const {
    state, statusMessage, isChatUploading, chatUploadName,
    handleSend, handleStop, handleChatUpload, doNewChat, startSession,
  } = useSession();

  const [confirmNewChat, setConfirmNewChat] = useState(false);
  const [newSessionPending, setNewSessionPending] = useState(false);
  const newSessionLauncherRef = useRef<HTMLButtonElement>(null);
  const newSessionConfirmRef = useRef<HTMLButtonElement>(null);
  const newSessionCancelRef = useRef<HTMLButtonElement>(null);
  const agentWorking = state.isStreaming || isChatUploading;
  const artifacts = useMemo(() => state.files.filter((f) => f.origin === "generated"), [state.files]);
  const handleNewChat = useCallback(() => {
    if (state.messages.length > 0) { setConfirmNewChat(true); return; }
    void doNewChat();
  }, [state.messages.length, doNewChat]);

  const closeNewSessionDialog = useCallback(() => {
    setConfirmNewChat(false);
    requestAnimationFrame(() => newSessionLauncherRef.current?.focus());
  }, []);

  useEffect(() => {
    if (!confirmNewChat) return;
    const focusable = () => [newSessionConfirmRef.current, newSessionCancelRef.current].filter((element): element is HTMLButtonElement => !!element && !element.disabled);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !newSessionPending) { event.preventDefault(); closeNewSessionDialog(); return; }
      if (event.key !== "Tab") return;
      const controls = focusable();
      if (!controls.length) return;
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    requestAnimationFrame(() => newSessionConfirmRef.current?.focus());
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeNewSessionDialog, confirmNewChat, newSessionPending]);

  const confirmNewSession = useCallback(async () => {
    setNewSessionPending(true);
    try { await doNewChat(); closeNewSessionDialog(); }
    finally { setNewSessionPending(false); }
  }, [closeNewSessionDialog, doNewChat]);

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
            ref={newSessionLauncherRef}
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
            {state.lastBundle && (
              <details className="ctx-inspector" data-testid="context-inspector">
                <summary>What personalized the last turn</summary>
                <div className="ctx-inspector-body">
                  <span className="ctx-line"><b>User</b> {state.lastBundle.user.displayName}</span>
                  {(state.lastBundle.persona.role || state.lastBundle.persona.tone) && (
                    <span className="ctx-line"><b>Persona</b> {[state.lastBundle.persona.role, state.lastBundle.persona.tone, state.lastBundle.persona.outputPrefs].filter(Boolean).join(" · ")}</span>
                  )}
                  {state.lastBundle.conventions.length > 0 && (
                    <span className="ctx-line"><b>Conventions ({state.lastBundle.engagementName})</b> {state.lastBundle.conventions.map((c) => c.text).join(" | ")}</span>
                  )}
                  <span className="ctx-line"><b>Precedence</b> {state.lastBundle.precedence.join(" › ")}</span>
                </div>
              </details>
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-app/80 backdrop-blur-md px-4">
          <div role="dialog" aria-modal="true" aria-labelledby="new-session-title" aria-describedby="new-session-description" className="w-full max-w-sm rounded-[2rem] border border-border-subtle bg-surface-1 p-8 shadow-[0_24px_60px_rgba(0,0,0,0.15)] relative overflow-hidden">
            <div className="absolute top-0 inset-x-0 h-1 bg-brand-primary" />
            <h2 id="new-session-title" className="text-lg font-bold text-text-primary uppercase tracking-wide">Start a new session?</h2>
            <p id="new-session-description" className="mt-3 text-sm text-text-muted leading-relaxed">This clears this conversation and its session files. Your Engagements and their durable artifacts stay available.</p>
            <div className="mt-8 flex flex-col gap-2">
              <button ref={newSessionConfirmRef} type="button" disabled={newSessionPending} onClick={() => void confirmNewSession()} className="interactive-control w-full rounded-xl bg-brand-primary py-3 text-xs font-bold uppercase tracking-widest text-white hover:brightness-110 disabled:opacity-45">{newSessionPending ? "Starting…" : "Start new session"}</button>
              <button ref={newSessionCancelRef} type="button" disabled={newSessionPending} onClick={closeNewSessionDialog} className="interactive-control w-full rounded-xl border border-border-subtle py-3 text-xs font-bold uppercase tracking-widest text-text-muted hover:bg-surface-2 disabled:opacity-45">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
