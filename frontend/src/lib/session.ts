import type { AuthUser, ChatMessage } from "./types";

const SESSION_KEY = "flow_session_id";
const MESSAGES_KEY = "flow_messages";
const USER_TOKEN_KEY = "flow_user_token";
const USER_KEY = "flow_user";

export function storeSessionId(id: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SESSION_KEY, id);
}

export function clearSessionId(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(MESSAGES_KEY);
}

export function getSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(SESSION_KEY);
}

export function getStoredMessages(): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(MESSAGES_KEY);
    if (!raw) return [];
    const messages = JSON.parse(raw) as ChatMessage[];
    // Sanitize: restore any "running" tool calls to "done" (page may have closed mid-turn)
    return messages.map(msg => ({
      ...msg,
      parts: msg.parts.map(part =>
        part.type === "tool_call" && part.status === "running"
          ? { ...part, status: "done" as const }
          : part
      ),
    }));
  } catch {
    return [];
  }
}

export function storeMessages(messages: ChatMessage[]): void {
  if (typeof window === "undefined") return;
  const completed = messages.filter((m) => !m.isStreaming);
  sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(completed));
}

// ── App-level user session (spec F1) ─────────────────────────────────────────
// Per-tab on purpose: two users signed in side-by-side in two tabs is the demo.
export function storeUserToken(token: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(USER_TOKEN_KEY, token);
}

export function getUserToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(USER_TOKEN_KEY);
}

export function clearUserToken(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(USER_TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  // A different user must never inherit another's chat: drop the agent session + messages too.
  clearSessionId();
}

export function storeUser(user: AuthUser): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}
