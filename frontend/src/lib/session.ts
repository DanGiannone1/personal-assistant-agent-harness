import type { ChatMessage } from "./types";
import { currentUserId } from "./appAuth";

// Keys are namespaced per signed-in user: switching accounts must never
// resurrect another user's session id or chat transcript.
const SESSION_KEY = () => `flow_session_id:${currentUserId()}`;
const MESSAGES_KEY = () => `flow_messages:${currentUserId()}`;

export function storeSessionId(id: string): void {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(SESSION_KEY(), id);
}

export function clearSessionId(): void {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(SESSION_KEY());
  sessionStorage.removeItem(MESSAGES_KEY());
}

export function getSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(SESSION_KEY());
}

export function getStoredMessages(): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(MESSAGES_KEY());
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
  sessionStorage.setItem(MESSAGES_KEY(), JSON.stringify(completed));
}
