// App-level accounts (username/password, demo-grade) — distinct from lib/auth.ts,
// which is the deploy-time Entra gate. This layer answers "which app user is this?".
// Token travels in X-Auth-Token; Authorization stays reserved for Entra.

import { buildAuthHeaders } from "./auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "pa_auth_token";
const USER_KEY = "pa_auth_user";

export interface AppUser {
  id: string;
  username: string;
  displayName: string;
  persona?: { role?: string; tone?: string; outputPrefs?: string; language?: string };
}

export function getAppToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): AppUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AppUser) : null;
  } catch {
    return null;
  }
}

export function currentUserId(): string {
  return getStoredUser()?.id ?? "anon";
}

function store(token: string, user: AppUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function clear(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** Attach the app token to a Headers object (after any Entra header). */
export async function withAppAuth(headersInit?: HeadersInit): Promise<Headers> {
  const headers = await buildAuthHeaders(headersInit);
  const token = getAppToken();
  if (token) headers.set("X-Auth-Token", token);
  return headers;
}

/** Broadcast that the server rejected our token (expired/restarted) → show sign-in. */
export function notifyAuthExpired(): void {
  clear();
  window.dispatchEvent(new Event("app-auth-expired"));
}

export async function login(username: string, password: string): Promise<AppUser> {
  const headers = await buildAuthHeaders({ "Content-Type": "application/json" });
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers,
    body: JSON.stringify({ username, password }),
    signal: AbortSignal.timeout(15_000),
  });
  if (res.status === 401) throw new Error("Invalid username or password.");
  if (!res.ok) throw new Error(`Sign-in failed (${res.status}). Is the server running?`);
  const data = (await res.json()) as { token: string; user: AppUser };
  store(data.token, data.user);
  return data.user;
}

export async function logout(): Promise<void> {
  const token = getAppToken();
  clear();
  if (!token) return;
  try {
    const headers = await buildAuthHeaders();
    headers.set("X-Auth-Token", token);
    await fetch(`${API_BASE}/auth/logout`, { method: "POST", headers, signal: AbortSignal.timeout(5_000) });
  } catch {
    // Token is already cleared locally; server-side entry expires on its own.
  }
}
