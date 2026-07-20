"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Sparkles } from "lucide-react";
import WorkbenchApp from "./workbench/WorkbenchApp";
import CoPilotDock from "./CoPilotDock";
import BespokeIcon from "./ui/BespokeIcon";
import { useSession } from "./SessionProvider";

// The host route ("/"): the CSA Workbench app is primary and full-width; the assistant
// rides along as a collapsible docked co-pilot. Collapsed, the app gets the whole canvas
// and the assistant becomes an unobtrusive launcher pill.
export default function HostApp() {
  const {
    state,
    navigateView,
    isChatUploading,
    saveToLibrary,
    removeFromLibrary,
    uploadDocument,
    refresh,
    startSession,
  } = useSession();
  const [wideDockOpen, setWideDockOpen] = useState(true);
  const [compactDockOpen, setCompactDockOpen] = useState(false);
  const [navDrawerOpen, setNavDrawerOpen] = useState(false);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const compactSheetRef = useRef<HTMLDivElement>(null);

  // Responsive: below 1200px the side-by-side rail crushes the host content, so the dock
  // auto-collapses to the launcher (host gets the full width) and, when opened, overlays the
  // host instead of squeezing it. Auto-adapts on resize while respecting in-regime toggles.
  const narrow = useCompactLayout();
  const dockOpen = narrow ? compactDockOpen : wideDockOpen;
  const setDockOpen = useCallback((open: boolean) => {
    if (narrow) setCompactDockOpen(open);
    else setWideDockOpen(open);
  }, [narrow]);
  const closeDock = useCallback(() => {
    setDockOpen(false);
    if (narrow) requestAnimationFrame(() => launcherRef.current?.focus());
  }, [narrow, setDockOpen]);

  useEffect(() => {
    if (!narrow || !dockOpen) return;
    const sheet = compactSheetRef.current;
    const focusable = () => [...(sheet?.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])") ?? [])].filter((element) => element.offsetParent !== null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { closeDock(); return; }
      if (event.key !== "Tab") return;
      const controls = focusable();
      if (!controls.length) return;
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    requestAnimationFrame(() => (focusable()[0] ?? sheet)?.focus());
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeDock, dockOpen, narrow]);

  const uploadedFiles = useMemo(
    () => state.files.filter((f) => f.origin === "uploaded"),
    [state.files],
  );
  const generatedFiles = useMemo(
    () => state.files.filter((f) => f.origin === "generated"),
    [state.files],
  );
  const agentWorking = state.isStreaming || isChatUploading;

  return (
    <div className="relative flex h-screen w-full bg-app p-3 gap-3 text-text-primary font-sans overflow-clip" data-testid="host-shell">
      <div className="pointer-events-none absolute inset-0 overflow-clip" aria-hidden="true">
        <div className="ambient-orb-1 animate-blob" />
        <div className="ambient-orb-2 animate-blob" />
      </div>

      <div className="relative z-10 flex h-full w-full gap-3" data-testid="host-layout">
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
            quickLinks={state.quickLinks}
            onSaveToLibrary={saveToLibrary}
            onRemoveFromLibrary={removeFromLibrary}
            onUpload={uploadDocument}
            onRefresh={refresh}
            workspaceStale={state.workspaceStale}
            sessionError={state.sessionError}
            onRetrySession={startSession}
            onDrawerOpenChange={setNavDrawerOpen}
          />
        </div>

        {dockOpen && !narrow && (
          <div
            data-testid="copilot-dock"
            className="w-[32%] min-w-[360px] max-w-[420px] shrink-0 h-full"
          >
            <CoPilotDock onCollapse={closeDock} />
          </div>
        )}
      </div>

      {/* Narrow: the dock overlays the host (with a tap-to-dismiss backdrop) instead of squeezing it. */}
      {dockOpen && narrow && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-20 bg-app/50 backdrop-blur-sm"
            aria-label="Close assistant"
            onClick={closeDock}
          />
          <div
            ref={compactSheetRef}
            role="dialog"
            aria-modal="true"
            aria-label="Assistant"
            tabIndex={-1}
            data-testid="copilot-dock"
            className="fixed right-3 top-3 bottom-3 z-30 w-[min(440px,92vw)]"
          >
            <CoPilotDock onCollapse={closeDock} />
          </div>
        </>
      )}

      {!dockOpen && !navDrawerOpen && (
        <button
          type="button"
          data-testid="dock-launcher"
          ref={launcherRef}
          onClick={() => setDockOpen(true)}
          className={`interactive-control fixed bottom-6 right-6 z-20 inline-flex items-center gap-2.5 rounded-2xl border border-border-subtle bg-surface-1/90 backdrop-blur-2xl px-4 py-3 shadow-[0_16px_40px_rgba(0,0,0,0.12)] hover:border-brand-primary transition-all`}
        >
          <span
            className={`p-1.5 rounded-lg bg-gradient-to-br from-brand-primary to-brand-accent ${agentWorking ? "agent-working" : ""}`}
          >
            <BespokeIcon
              icon={Sparkles}
              size={15}
              className="text-white"
              glowColor="rgba(255,255,255,0.4)"
            />
          </span>
          <span className="text-[12px] font-bold uppercase tracking-widest text-text-secondary">
            {agentWorking ? "Assistant · Working…" : "Ask the Assistant"}
          </span>
        </button>
      )}
    </div>
  );
}

function useCompactLayout() {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia("(max-width: 1199px)");
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => window.matchMedia("(max-width: 1199px)").matches,
    // Render the safe compact state on the server and during hydration. The
    // browser snapshot immediately opens the dock on wide layouts, while a
    // compact first paint never exposes an overlay the user did not request.
    () => true,
  );
}
