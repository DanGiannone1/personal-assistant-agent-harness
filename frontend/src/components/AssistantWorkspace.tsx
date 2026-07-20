"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { PanelLeftClose, Home } from "lucide-react";
import AssistantPanel from "./AssistantPanel";
import ArtifactCanvas from "./ArtifactCanvas";
import WorkbenchNav from "./workbench/WorkbenchNav";
import { useSession } from "./SessionProvider";

// The dedicated Assistant workspace ("/assistant"): chat is the spine, with the artifact
// canvas beside it for deep work that produces output. Same continuous session as the dock.
export default function AssistantWorkspace() {
  const router = useRouter();
  const { state, navigateView } = useSession();

  // Responsive: below ~1100px the 3 columns overflow (the canvas got pushed off-screen), so
  // drop the redundant host nav rail (a Back control already exists) and let chat + canvas share.
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 1100);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // When the agent navigates the host app to a place the user should see IN CONTEXT (a task,
  // the home agenda, the calendar), bring them back to the host app. But the Documents route
  // must NOT eject the user out of the workspace — a drafted document belongs in the canvas
  // here. Ejecting on that was the headline UX wound (asking for a deliverable yanked you out).
  const prevRoute = useRef(state.viewRoute);
  useEffect(() => {
    if (state.viewRoute === prevRoute.current) return;
    const r = state.viewRoute;
    prevRoute.current = r;
    const hostContext = r === "/home" || r === "/todo" || r.startsWith("/todo/") || r === "/calendar";
    if (hostContext) router.push("/");
  }, [state.viewRoute, router]);

  return (
    <div className="relative flex h-screen w-full bg-app p-3 gap-3 text-text-primary font-sans overflow-hidden">
      <div className="ambient-orb-1 animate-blob" />
      <div className="ambient-orb-2 animate-blob" />

      <div className="relative z-10 flex h-full w-full gap-3">
        {/* Host app shell rail — so the workspace reads as a page OF CSA Workbench, not a
            separate chatbot. Hidden on narrow viewports (the Back control covers returning). */}
        {!narrow && (
          <div className="flex h-full w-[210px] shrink-0 flex-col rounded-2xl border border-border-subtle bg-surface-1/70 backdrop-blur-2xl overflow-hidden">
            <div className="tw-appbar-brand px-4 h-14 flex items-center shrink-0 border-b border-border-subtle">
              <div className="tw-logo"><Home size={16} strokeWidth={2.5} /></div>
              <div className="flex flex-col leading-tight ml-2">
                <span className="tw-appbar-title">CSA Workbench</span>
                <span className="tw-appbar-sub">Assistant</span>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              <WorkbenchNav appState={state.appState} viewRoute={state.viewRoute} onNavigate={navigateView} assistantActive />
            </div>
          </div>
        )}

        <div className={`${narrow ? "w-1/2 min-w-[320px]" : "w-[40%] min-w-[400px] max-w-[600px]"} shrink-0 h-full`}>
          <AssistantPanel
            headerActions={
              <button
                type="button"
                data-testid="workspace-back"
                onClick={() => router.push("/")}
                title="Back to CSA Workbench"
                className="interactive-control inline-flex h-8 w-8 items-center justify-center rounded-lg bg-surface-2 border border-border-subtle text-text-secondary hover:text-text-primary hover:border-brand-primary transition-all"
              >
                <PanelLeftClose size={14} strokeWidth={2.5} />
              </button>
            }
          />
        </div>
        <div className="flex-1 min-w-0 h-full">
          <ArtifactCanvas />
        </div>
      </div>
    </div>
  );
}
