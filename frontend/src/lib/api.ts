import { buildAuthHeaders } from "./auth";
import type { AppState, FileInfo } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SessionMetadata {
  session_id: string;
  status: string;
  files?: FileInfo[];
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = await buildAuthHeaders(init.headers);
  return fetch(`${API_BASE}${path}`, { ...init, headers });
}

export async function getAppState(sessionId: string): Promise<AppState> {
  const res = await apiFetch(`/sessions/${sessionId}/app/state`, {
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) throw new Error(`Failed to load app state: ${res.status}`);
  return res.json();
}

export async function getSession(sessionId: string): Promise<SessionMetadata | null> {
  const res = await apiFetch(`/sessions/${sessionId}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Session check failed: ${res.status}`);
  return res.json();
}

export async function createSession(): Promise<SessionMetadata> {
  const res = await apiFetch("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  return res.json();
}

export async function uploadFile(
  sessionId: string,
  file: File,
): Promise<{ path: string; filename: string; size: number; markdown_ready: boolean }> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch(`/sessions/${sessionId}/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Upload failed (${res.status}): ${detail}`);
  }
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await apiFetch(`/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404) {
    const detail = await res.text();
    throw new Error(`Delete session failed (${res.status}): ${detail}`);
  }
}

export async function listFiles(
  sessionId: string,
): Promise<{ files: FileInfo[] }> {
  const res = await apiFetch(`/sessions/${sessionId}/files`, {
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) throw new Error(`Failed to list files: ${res.status}`);
  return res.json();
}

export interface FileContentResponse {
  filename: string;
  size: number;
  mime_type: string;
  content: string;
}

export async function getFileContent(
  sessionId: string,
  filename: string,
): Promise<FileContentResponse> {
  const params = new URLSearchParams({ filename });
  const res = await apiFetch(`/sessions/${sessionId}/files/content?${params.toString()}`, {
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Failed to load file content (${res.status}): ${detail}`);
  }
  return res.json();
}

export async function saveFileContent(
  sessionId: string,
  filename: string,
  content: string,
): Promise<{ filename: string; size: number }> {
  const res = await apiFetch(`/sessions/${sessionId}/files/content`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, content }),
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Failed to save (${res.status}): ${detail}`);
  }
  return res.json();
}

// ── Library (persistent KB) ──────────────────────────────────────────────────
export async function saveToLibrary(
  sessionId: string,
  filename: string,
): Promise<{ filename: string; chunks: number; status: string }> {
  const res = await apiFetch(`/sessions/${sessionId}/library`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename }),
    signal: AbortSignal.timeout(60_000),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Failed to save to Library (${res.status}): ${detail}`);
  }
  return res.json();
}

export async function deleteFromLibrary(sessionId: string, filename: string): Promise<void> {
  const res = await apiFetch(`/sessions/${sessionId}/library/${encodeURIComponent(filename)}`, {
    method: "DELETE",
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok && res.status !== 204) {
    const detail = await res.text();
    throw new Error(`Failed to remove from Library (${res.status}): ${detail}`);
  }
}

export async function getLibraryContent(
  sessionId: string,
  filename: string,
): Promise<FileContentResponse> {
  const params = new URLSearchParams({ filename });
  const res = await apiFetch(`/sessions/${sessionId}/library/content?${params.toString()}`, {
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Failed to load Library document (${res.status}): ${detail}`);
  }
  return res.json();
}
