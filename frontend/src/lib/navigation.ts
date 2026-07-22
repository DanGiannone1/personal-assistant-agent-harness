import type { AppState, Destination } from "./types";
import { parseEngagementRoute } from "./engagementRoute";
const ENGAGEMENT_ID = /^[A-Za-z0-9_-]{1,128}$/;
const RECORD_ID = /^[A-Za-z0-9_-]{1,128}$/;
const PERSONAL_ROUTES = new Set(["/home", "/todo", "/calendar", "/reminders"]);

export function normalizeHostRoute(route: string): string {
  if (route === "/engagements" || route === "/settings" || PERSONAL_ROUTES.has(route)) return route;
  const taskDetail = /^\/todo\/([^/]+)$/.exec(route);
  if (taskDetail && RECORD_ID.test(taskDetail[1])) return route;
  return parseEngagementRoute(route) ? route : "/engagements";
}

export function isCatalogDestination(destination: Destination): boolean {
  const scoped = new Set(["engagement_overview", "engagement_tasks", "engagement_artifacts"]);
  if (destination.id === "engagements") return destination.path === "/engagements" && !destination.engagementId;
  if (!scoped.has(destination.id) || !destination.engagementId || !ENGAGEMENT_ID.test(destination.engagementId)) return false;
  const suffix = destination.id === "engagement_tasks" ? "/tasks" : destination.id === "engagement_artifacts" ? "/artifacts" : "";
  return destination.path === `/engagements/${destination.engagementId}${suffix}`;
}

export function isKnownDestination(destination: Destination, appState: AppState | null): boolean {
  if (!isCatalogDestination(destination)) return false;
  if (destination.id === "engagements") return true;
  if (!destination.engagementId) return false;
  if (!appState?.engagements?.some((engagement) => engagement.id === destination.engagementId)) return false;
  return true;
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

export function shouldQueueAgentNavigation(input: {
  activeRunId: string | null;
  navigationVersion: number;
  cancelled: boolean;
  event: { runId: string; destination: Destination; requestedAtNavigationVersion: number };
}): boolean {
  return !input.cancelled
    && input.event.runId === input.activeRunId
    && input.event.requestedAtNavigationVersion === input.navigationVersion
    && isCatalogDestination(input.event.destination);
}
