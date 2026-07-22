"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, PanelLeftClose, Home } from "lucide-react";
import AssistantPanel from "./AssistantPanel";
import ArtifactCanvas from "./ArtifactCanvas";
import WorkbenchNav from "./workbench/WorkbenchNav";
import { useSession } from "./SessionProvider";
import { isHostRoute } from "@/lib/navigation";

// The dedicated Assistant workspace ("/assistant"): chat is the spine, with the artifact
// canvas beside it for deep work that produces output. Same continuous session as the dock.
export default function AssistantWorkspace() {
  const router = useRouter();
  const { state, navigateView } = useSession();

  // Responsive: below ~1100px the 3 columns overflow (the canvas got pushed off-screen), so
  // drop the redundant host nav rail (a Back control already exists) and let chat + canvas share.
  const [narrow, setNarrow] = useState(false);
  const [stacked, setStacked] = useState(false);
  useEffect(() => {
    const onResize = () => { setNarrow(window.innerWidth < 1100); setStacked(window.innerWidth < 768); };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // The artifact canvas is not popped out by default: chat is the full-width spine until the
  // assistant actually produces a deliverable (auto-reveal) or the user opens it deliberately.
  const artifacts = useMemo(() => state.files.filter((f) => f.origin === "generated"), [state.files]);
  // Default: chat is full-width and the canvas stays closed until a deliverable actually exists
  // (auto-reveal). A deliberate user toggle wins only for the current session so New Session
  // restores the default and a prior session cannot suppress a new deliverable.
  const [artifactPreference, setArtifactPreference] = useState<{
    sessionId: string | null;
    visible: boolean;
  } | null>(null);
  const override = artifactPreference?.sessionId === state.sessionId
    ? artifactPreference.visible
    : null;
  const showArtifacts = override ?? artifacts.length > 0;

  // Manual navigation must leave AI Mode even when the selected route is already the accepted
  // host route (for example: enter AI Mode from Home, then select Home again).
  const navigateHostView = useCallback((route: string) => {
    navigateView(route);
    router.push("/");
  }, [navigateView, router]);

  // Agent-driven navigation also leaves AI Mode after authoritative state accepts the route.
  // Manual navigation is handled immediately above; this effect covers structured navigation
  // events that update shared state without invoking the rail callback.
  const handledViewRouteRevision = useRef(state.viewRouteRevision);
  useEffect(() => {
    if (state.viewRouteRevision === handledViewRouteRevision.current) return;
    handledViewRouteRevision.current = state.viewRouteRevision;
    if (isHostRoute(state.viewRoute)) router.push("/");
  }, [state.viewRoute, state.viewRouteRevision, router]);

  return (
    <div className={`relative flex h-screen w-full bg-app p-3 gap-3 text-text-primary font-sans ${stacked ? "overflow-y-auto" : "overflow-hidden"}`} data-testid="assistant-workspace">
      <div className="ambient-orb-1 animate-blob" />
      <div className="ambient-orb-2 animate-blob" />

      <div className={`relative z-10 flex w-full gap-3 ${stacked ? "min-h-full flex-col" : "h-full"}`}>
        {/* Host app shell rail — so the workspace reads as a page OF CSA Workbench, not a
            separate chatbot. Hidden on narrow viewports (the Back control covers returning). */}
        {!narrow && (
          <div className="flex h-full w-[210px] shrink-0 flex-col rounded-2xl border border-border-subtle bg-surface-1/70 backdrop-blur-2xl overflow-hidden">
            <div className="tw-appbar-brand px-4 h-14 flex items-center shrink-0 border-b border-border-subtle">
              <div className="tw-logo"><Home size={16} strokeWidth={2.5} /></div>
              <div className="flex flex-col leading-tight ml-2">
                <span className="tw-appbar-title">CSA Workbench</span>
                <span className="tw-appbar-sub">AI Mode</span>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              <WorkbenchNav appState={state.appState} viewRoute={state.viewRoute} onNavigate={navigateHostView} assistantActive />
            </div>
          </div>
        )}

        <div className={`${!showArtifacts ? "flex-1 min-w-0 h-full" : stacked ? "w-full min-h-[500px] h-[62svh] shrink-0" : narrow ? "w-1/2 min-w-[320px] shrink-0 h-full" : "w-[40%] min-w-[400px] max-w-[600px] shrink-0 h-full"}`}>
          <AssistantPanel
            headerActions={
              <>
                <button
                  type="button"
                  data-testid="artifacts-toggle"
                  aria-pressed={showArtifacts}
                  onClick={() => setArtifactPreference({ sessionId: state.sessionId, visible: !showArtifacts })}
                  title={showArtifacts ? "Hide artifacts" : "Show artifacts"}
                  className="interactive-control inline-flex h-8 items-center gap-1.5 rounded-lg bg-surface-2 border border-border-subtle px-2.5 text-text-secondary hover:text-text-primary hover:border-brand-primary transition-all"
                >
                  <FileText size={14} strokeWidth={2.5} />
                  <span className="text-[11px] font-bold uppercase tracking-widest">{showArtifacts ? "Hide" : "Artifacts"}</span>
                  {!showArtifacts && artifacts.length > 0 && (
                    <span data-testid="artifacts-toggle-count" className="ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-primary px-1 text-[10px] font-bold text-white">{artifacts.length}</span>
                  )}
                </button>
                <button
                  type="button"
                  data-testid="workspace-back"
                  onClick={() => router.push("/")}
                  title="Back to CSA Workbench"
                  className="interactive-control inline-flex h-8 w-8 items-center justify-center rounded-lg bg-surface-2 border border-border-subtle text-text-secondary hover:text-text-primary hover:border-brand-primary transition-all"
                >
                  <PanelLeftClose size={14} strokeWidth={2.5} />
                </button>
              </>
            }
          />
        </div>
        {showArtifacts && (
          <div className={`${stacked ? "w-full min-h-[400px] h-[52svh]" : "flex-1 min-w-0 h-full"}`} data-testid="artifact-canvas-column">
            <ArtifactCanvas />
          </div>
        )}
      </div>
    </div>
  );
}
