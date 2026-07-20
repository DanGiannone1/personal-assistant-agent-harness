import type { AppState, Destination } from "./types";
const ENGAGEMENT_ID = /^[A-Za-z0-9_-]{1,128}$/;

export function isKnownDestination(destination: Destination, appState: AppState | null): boolean {
  const scoped = new Set(["engagement_overview", "engagement_tasks", "engagement_artifacts"]);
  if (destination.id === "engagements") return destination.path === "/engagements" && !destination.engagementId;
  if (destination.id === "workbench") return destination.path === "/home" && !destination.engagementId;
  if (!scoped.has(destination.id) || !destination.engagementId || !ENGAGEMENT_ID.test(destination.engagementId)) return false;
  if (!appState?.engagements?.some((engagement) => engagement.id === destination.engagementId)) return false;
  const suffix = destination.id === "engagement_tasks" ? "/tasks" : destination.id === "engagement_artifacts" ? "/documents" : "";
  return destination.path === `/engagements/${destination.engagementId}${suffix}`;
}

export function shouldApplyAgentNavigation(input: {
  activeRunId: string | null;
  navigationVersion: number;
  cancelled: boolean;
  event: { runId: string; destination: Destination; requestedAtNavigationVersion: number };
  appState: AppState | null;
}): boolean {
  return !input.cancelled
    && input.event.runId === input.activeRunId
    && input.event.requestedAtNavigationVersion === input.navigationVersion
    && isKnownDestination(input.event.destination, input.appState);
}
