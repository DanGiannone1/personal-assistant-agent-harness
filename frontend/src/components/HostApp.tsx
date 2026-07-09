"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import WorkbenchApp from "./workbench/WorkbenchApp";
import CoPilotDock from "./CoPilotDock";
import BespokeIcon from "./ui/BespokeIcon";
import { useSession } from "./SessionProvider";

// The host route ("/"): the Personal Assistant app is primary and full-width; the assistant
// rides along as a collapsible docked co-pilot. Collapsed, the app gets the whole canvas
// and the assistant becomes an unobtrusive launcher pill.
export default function HostApp() {
  const { state, navigateView, isChatUploading, saveToLibrary, removeFromLibrary, uploadDocument, refresh } = useSession();
  const [dockOpen, setDockOpen] = useState(true);

  // Responsive: below ~1100px the side-by-side rail crushes the host content, so the dock
  // auto-collapses to the launcher (host gets the full width) and, when opened, overlays the
  // host instead of squeezing it. Auto-adapts on resize while respecting in-regime toggles.
  const [narrow, setNarrow] = useState(false);
  const prevNarrow = useRef<boolean | null>(null);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 1100);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  useEffect(() => {
    if (prevNarrow.current === narrow) return;
    prevNarrow.current = narrow;
    setDockOpen(!narrow);
  }, [narrow]);

  const uploadedFiles = useMemo(() => state.files.filter((f) => f.origin === "uploaded"), [state.files]);
  const generatedFiles = useMemo(() => state.files.filter((f) => f.origin === "generated"), [state.files]);
  const agentWorking = state.isStreaming || isChatUploading;

  return (
    <div className="relative flex h-screen w-full bg-app p-3 gap-3 text-text-primary font-sans overflow-hidden">
      <div className="ambient-orb-1 animate-blob" />
      <div className="ambient-orb-2 animate-blob" />

      <div className="relative z-10 flex h-full w-full gap-3">
        <div className="flex-1 min-w-0 h-full">
          <WorkbenchApp
            appState={state.appState}
            loading={state.isInitializing}
            viewRoute={state.viewRoute}
            onNavigate={navigateView}
            sessionId={state.sessionId}
            uploadedFiles={uploadedFiles}
            generatedFiles={generatedFiles}
            newRecordIds={state.newRecordIds}
            agentWorking={agentWorking}
            onSaveToLibrary={saveToLibrary}
            onRemoveFromLibrary={removeFromLibrary}
            onUpload={uploadDocument}
            onRefresh={refresh}
          />
        </div>

        {dockOpen && !narrow && (
          <div data-testid="copilot-dock" className="w-[32%] min-w-[360px] max-w-[420px] shrink-0 h-full">
            <CoPilotDock onCollapse={() => setDockOpen(false)} />
          </div>
        )}
      </div>

      {/* Narrow: the dock overlays the host (with a tap-to-dismiss backdrop) instead of squeezing it. */}
      {dockOpen && narrow && (
        <>
          <div className="fixed inset-0 z-20 bg-app/50 backdrop-blur-sm" onClick={() => setDockOpen(false)} />
          <div data-testid="copilot-dock" className="fixed right-3 top-3 bottom-3 z-30 w-[min(440px,92vw)]">
            <CoPilotDock onCollapse={() => setDockOpen(false)} />
          </div>
        </>
      )}

      {!dockOpen && (
        <button
          type="button"
          data-testid="dock-launcher"
          onClick={() => setDockOpen(true)}
          className={`interactive-control fixed bottom-6 right-6 z-20 inline-flex items-center gap-2.5 rounded-2xl border border-border-subtle bg-surface-1/90 backdrop-blur-2xl px-4 py-3 shadow-[0_16px_40px_rgba(0,0,0,0.12)] hover:border-brand-primary transition-all`}
        >
          <span className={`p-1.5 rounded-lg bg-gradient-to-br from-brand-primary to-brand-accent ${agentWorking ? "agent-working" : ""}`}>
            <BespokeIcon icon={Sparkles} size={15} className="text-white" glowColor="rgba(255,255,255,0.4)" />
          </span>
          <span className="text-[12px] font-bold uppercase tracking-widest text-text-secondary">
            {agentWorking ? "Assistant · Working…" : "Ask the Assistant"}
          </span>
        </button>
      )}
    </div>
  );
}
