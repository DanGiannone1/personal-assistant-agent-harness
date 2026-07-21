"use client";

import { useRouter } from "next/navigation";
import { Maximize2, PanelRightClose } from "lucide-react";
import AssistantPanel from "./AssistantPanel";

// The docked co-pilot supports Engagement work beside the host app. `Expand` opens
// the full /assistant workspace (same session);
// `Collapse` hands the screen back to the app (host app shows a launcher pill).
export default function CoPilotDock({ onCollapse }: { onCollapse: () => void }) {
  const router = useRouter();
  return (
    <AssistantPanel
      onOpenWorkspace={() => router.push("/assistant")}
      headerActions={
        <>
          <button
            type="button"
            data-testid="dock-expand"
            onClick={() => router.push("/assistant")}
            title="Open the Assistant workspace"
            className="interactive-control inline-flex h-8 w-8 items-center justify-center rounded-lg bg-surface-2 border border-border-subtle text-text-secondary hover:text-text-primary hover:border-brand-primary transition-all"
          >
            <Maximize2 size={14} strokeWidth={2.5} />
          </button>
          <button
            type="button"
            data-testid="dock-collapse"
            onClick={onCollapse}
            title="Collapse the assistant"
            className="interactive-control inline-flex h-8 w-8 items-center justify-center rounded-lg bg-surface-2 border border-border-subtle text-text-secondary hover:text-text-primary hover:border-brand-primary transition-all"
          >
            <PanelRightClose size={14} strokeWidth={2.5} />
          </button>
        </>
      }
    />
  );
}
