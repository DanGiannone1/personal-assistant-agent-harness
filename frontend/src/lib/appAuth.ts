// Demo actor sessions use X-Auth-Token. Entra actor requests use only the bearer
// built in lib/auth.ts; the selected mode never merges those credentials.

import { buildAuthHeaders, identityMode } from "./auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const TOKEN_KEY = "pa_auth_token";
const USER_KEY = "pa_auth_user";

export interface AppUser {
  id: string;
  username: string;
  displayName: string;
  identity?: "demo" | "entra";
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

/** Attach exactly the credential for this browser's selected identity mode. */
export async function withAppAuth(headersInit?: HeadersInit): Promise<Headers> {
  const mode = identityMode();
  if (!mode) throw new Error("Identity mode is not configured.");
  const headers = await buildAuthHeaders(headersInit);
  if (mode === "demo") {
    const token = getAppToken();
    if (token) headers.set("X-Auth-Token", token);
  }
  return headers;
}

/** Broadcast that the server rejected our token (expired/restarted) → show sign-in. */
export function notifyAuthExpired(): void {
  clear();
  window.dispatchEvent(new Event("app-auth-expired"));
}

/** Resolve the signed-in app user from whatever credentials the request carries
 *  (Entra bearer and/or demo token). Used to hydrate the Entra path, where no
 *  app token exists — the bearer alone identifies the user. Stores the user for
 *  per-user storage namespacing (session keys), same as the demo path. */
export async function fetchMe(): Promise<AppUser | null> {
  if (identityMode() !== "entra") return null;
  try {
    const headers = await withAppAuth();
    const res = await fetch(`${API_BASE}/auth/me`, { headers, signal: AbortSignal.timeout(15_000) });
    if (!res.ok) return null;
    const user = (await res.json()) as AppUser;
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    return user;
  } catch {
    return null;
  }
}

export async function login(username: string, password: string): Promise<AppUser> {
  if (identityMode() !== "demo") throw new Error("Demo sign-in is unavailable.");
  const headers = new Headers({ "Content-Type": "application/json" });
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
  const mode = identityMode();
  const token = getAppToken();
  clear();
  if (mode !== "demo" || !token) return;
  try {
    const headers = new Headers({ "X-Auth-Token": token });
    await fetch(`${API_BASE}/auth/logout`, { method: "POST", headers, signal: AbortSignal.timeout(5_000) });
  } catch {
    // Token is already cleared locally; server-side entry expires on its own.
  }
}
