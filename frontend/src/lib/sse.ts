import { notifyAuthExpired, withAppAuth } from "./appAuth";
import { AGUIEvent } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// A turn can legitimately go quiet for a while when the model reads a large
// uploaded document and prepares the first response chunk.
const INACTIVITY_TIMEOUT_MS = Number(
  process.env.NEXT_PUBLIC_SSE_INACTIVITY_TIMEOUT_MS || "600000",
);

export async function* streamSSE(
  prompt: string,
  signal: AbortSignal,
  sessionId: string,
): AsyncGenerator<AGUIEvent> {
  const url = `${API_BASE}/sessions/${sessionId}/messages`;
  const headers = await withAppAuth({ "Content-Type": "application/json" });

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ prompt }),
    signal,
  });

  if (res.status === 401) {
    notifyAuthExpired();
    yield { type: "RUN_ERROR", message: "Signed out — please sign in again." };
    return;
  }
  if (!res.ok) {
    yield { type: "RUN_ERROR", message: `HTTP ${res.status}: ${res.statusText}` };
    return;
  }

  if (!res.body) {
    yield { type: "RUN_ERROR", message: "Empty response body" } as AGUIEvent;
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let inactivityTimer: ReturnType<typeof setTimeout> | undefined;
  let timedOut = false;

  function resetInactivityTimer() {
    if (inactivityTimer) clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(() => { timedOut = true; reader.cancel(); }, INACTIVITY_TIMEOUT_MS);
  }

  resetInactivityTimer();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      resetInactivityTimer();
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop()!;

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith("data:")) continue;
        const data = trimmed.startsWith("data: ") ? trimmed.slice(6) : trimmed.slice(5);
        try {
          const event = JSON.parse(data) as AGUIEvent;
          yield event;
        } catch {
          // skip malformed lines
        }
      }
    }

    // On inactivity timeout, don't replay any buffered event (a stale RUN_FINISHED
    // would otherwise finalize the turn before the timeout error surfaces).
    if (timedOut) {
      yield { type: "RUN_ERROR", message: "The assistant stopped responding (timed out). Please try again." };
      return;
    }

    // process any remaining buffer
    const remaining = buffer.trim();
    if (remaining.startsWith("data:")) {
      const data = remaining.startsWith("data: ") ? remaining.slice(6) : remaining.slice(5);
      try {
        const event = JSON.parse(data) as AGUIEvent;
        yield event;
      } catch {
        // skip
      }
    }
  } finally {
    if (inactivityTimer) clearTimeout(inactivityTimer);
  }
}
