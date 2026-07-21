"use client";

import { Home as HomeIcon } from "lucide-react";
import type { AppState } from "@/lib/types";
import WorkbenchNav from "./WorkbenchNav";
import { EngagementScreen, EngagementsList } from "./EngagementScreens";
import SettingsScreen from "./SettingsScreen";

interface WorkbenchAppProps {
  appState: AppState | null;
  loading: boolean;
  viewRoute: string;
  onNavigate: (route: string) => void;
  agentWorking: boolean;
  onRefresh: () => Promise<void>;
  workspaceStale?: string | null;
  sessionError?: string | null;
  onRetrySession?: () => Promise<void>;
  onDrawerOpenChange?: (open: boolean) => void;
}

export default function WorkbenchApp({
  appState, loading, viewRoute, onNavigate, agentWorking, onRefresh, workspaceStale, sessionError, onRetrySession, onDrawerOpenChange,
}: WorkbenchAppProps) {
  return (
    <div className="tw-app" data-testid="workbench-app">
      <style>{`.tw-app :focus-visible { outline: 2px solid var(--brand-primary, #0073ea); outline-offset: 2px; border-radius: 6px; }`}</style>
      <div className="tw-appbar">
        <div className="tw-appbar-brand">
          <div className="tw-logo"><HomeIcon size={16} strokeWidth={2.5} /></div>
          <div className="flex flex-col leading-tight">
            <span className="tw-appbar-title">CSA Workbench</span>
            <span className="tw-appbar-sub">{agentWorking ? "Assistant working…" : "Ready"}</span>
          </div>
        </div>
        <Breadcrumb appState={appState} viewRoute={viewRoute} />
      </div>
      <div className="tw-body">
        <WorkbenchNav appState={appState} viewRoute={viewRoute} onNavigate={onNavigate} onDrawerOpenChange={onDrawerOpenChange} />
        <main className="tw-content" data-testid="workbench-content">
          {loading && !appState ? <div className="tw-empty" data-testid="workspace-loading" role="status">Loading workspace…</div>
            : sessionError && !appState ? <div className="tw-empty" role="alert">{sessionError} <button type="button" className="tw-btn" data-testid="workspace-retry" onClick={() => void onRetrySession?.()}>Retry</button></div>
              : !appState ? <div className="tw-empty" role="alert">{workspaceStale ?? "Workspace unavailable."}</div>
                : <RouteContent appState={appState} viewRoute={viewRoute} onNavigate={onNavigate} onRefresh={onRefresh} />}
          {workspaceStale && appState && <div className="tw-workspace-stale" data-testid="workspace-stale" role="status">Showing the last refreshed workspace. {workspaceStale} <button type="button" className="tw-btn-ghost" data-testid="workspace-retry" onClick={() => void onRefresh().catch(() => undefined)}>Retry</button></div>}
        </main>
      </div>
    </div>
  );
}

function Breadcrumb({ appState, viewRoute }: { appState: AppState | null; viewRoute: string }) {
  if (!appState) return null;
  if (viewRoute === "/settings") return <div className="tw-breadcrumb" data-testid="breadcrumb">Settings</div>;
  if (viewRoute === "/engagements") return <div className="tw-breadcrumb" data-testid="breadcrumb">Engagements</div>;
  const id = viewRoute.split("/")[2];
  const engagement = appState.engagements?.find((entry) => entry.id === id);
  const section = viewRoute.split("/")[3];
  return <div className="tw-breadcrumb" data-testid="breadcrumb">Engagements › {engagement?.name ?? ""}{section ? ` › ${section[0].toUpperCase()}${section.slice(1)}` : ""}</div>;
}

function RouteContent({ appState, viewRoute, onNavigate, onRefresh }: { appState: AppState; viewRoute: string; onNavigate: (route: string) => void; onRefresh: () => Promise<void> }) {
  if (viewRoute === "/settings") return <SettingsScreen appState={appState} onRefresh={onRefresh} />;
  if (viewRoute === "/engagements") return <EngagementsList appState={appState} onNavigate={onNavigate} onRefresh={onRefresh} />;
  return <EngagementScreen appState={appState} viewRoute={viewRoute} onNavigate={onNavigate} onRefresh={onRefresh} />;
}
