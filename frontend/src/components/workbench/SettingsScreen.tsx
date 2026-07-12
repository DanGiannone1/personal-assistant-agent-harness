"use client";

// Personal settings: persona (stored, legible, adjustable — never silently inferred),
// standing approvals (per-action grants the agent's confirm-first deletes honor), and
// workspace memories (every stored fact visible and deletable — the legibility rule).

import { useEffect, useState } from "react";
import { BadgeCheck, Brain, Plus, Trash2, UserCog } from "lucide-react";
import type { AppState } from "@/lib/types";
import { addMemory, deleteMemory, getApprovals, putApprovals, putPersona } from "@/lib/api";
import { friendlyError } from "@/lib/utils";

export default function SettingsScreen({ appState, onRefresh }: {
  appState: AppState; onRefresh: () => Promise<void>;
}) {
  const persona = appState.user?.persona ?? {};
  const memories = appState.context?.memories ?? [];
  const [role, setRole] = useState(persona.role ?? "");
  const [tone, setTone] = useState(persona.tone ?? "");
  const [outputPrefs, setOutputPrefs] = useState(persona.outputPrefs ?? "");
  const [language, setLanguage] = useState(persona.language ?? "English");
  const [saved, setSaved] = useState(false);
  const [available, setAvailable] = useState<string[]>([]);
  const [approvals, setApprovals] = useState<string[]>([]);
  const [memText, setMemText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getApprovals().then((r) => { setAvailable(r.available); setApprovals(r.approvals); }).catch(() => {});
  }, []);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); await onRefresh(); } catch (err) { setError(friendlyError(err, "Save failed.")); }
    finally { setBusy(false); }
  };

  return (
    <div className="tw-screen" data-testid="settings-screen">
      <h1 className="tw-h1">Settings</h1>
      <p className="tw-subtle">Everything stored about you is on this page — visible, editable, deletable.</p>

      <section className="tw-section">
        <h2 className="tw-h2"><UserCog size={14} /> Persona</h2>
        <p className="tw-subtle">Shapes how the assistant responds. Applied every turn; your in-message instructions always win.</p>
        <div className="tw-addform" style={{ flexWrap: "wrap" }}>
          <input className="tw-input" placeholder="Role (e.g. Product lead)" value={role} data-testid="persona-role"
            onChange={(e) => { setRole(e.target.value); setSaved(false); }} style={{ minWidth: 220 }} />
          <input className="tw-input" placeholder="Tone (e.g. concise and direct)" value={tone} data-testid="persona-tone"
            onChange={(e) => { setTone(e.target.value); setSaved(false); }} style={{ minWidth: 220 }} />
          <input className="tw-input" placeholder="Output preferences" value={outputPrefs} data-testid="persona-prefs"
            onChange={(e) => { setOutputPrefs(e.target.value); setSaved(false); }} style={{ minWidth: 260 }} />
          <input className="tw-input" placeholder="Language" value={language} data-testid="persona-language"
            onChange={(e) => { setLanguage(e.target.value); setSaved(false); }} style={{ width: 130 }} />
          <button type="button" className="tw-btn" disabled={busy} data-testid="persona-save"
            onClick={() => act(async () => { await putPersona({ role, tone, outputPrefs, language }); setSaved(true); })}>
            {saved ? "Saved ✓" : "Save persona"}
          </button>
        </div>
      </section>

      <section className="tw-section">
        <h2 className="tw-h2"><BadgeCheck size={14} /> Standing approvals</h2>
        <p className="tw-subtle">Actions the assistant may take without asking again. Everything else stays confirm-first.</p>
        <div className="tw-doclist" data-testid="approvals-list">
          {available.map((a) => {
            const on = approvals.includes(a);
            return (
              <label key={a} className="tw-docitem" style={{ cursor: "pointer" }} data-testid={`approval-${a}`}>
                <input type="checkbox" checked={on} disabled={busy}
                  onChange={() => {
                    const next = on ? approvals.filter((x) => x !== a) : [...approvals, a];
                    setApprovals(next);
                    void act(() => putApprovals(next));
                  }} />
                <span className="tw-td-title" style={{ fontSize: 13 }}>{a.replace(/_/g, " ")}</span>
                <span className="tw-td-sub" style={{ marginLeft: "auto" }}>{on ? "always allowed" : "asks first"}</span>
              </label>
            );
          })}
        </div>
      </section>

      <section className="tw-section">
        <h2 className="tw-h2"><Brain size={14} /> Workspace memory</h2>
        <p className="tw-subtle">Durable facts the assistant may use. It can only add here with your confirmation.</p>
        {memories.length === 0 ? (
          <div className="tw-empty-sm">Nothing remembered yet.</div>
        ) : (
          <div className="tw-doclist" data-testid="memory-list">
            {memories.map((m) => (
              <div key={m.id} className="tw-docitem" data-testid={`memory-${m.id}`}>
                <span className="tw-td-sub">{m.text}</span>
                <button type="button" className="tw-btn-ghost" style={{ marginLeft: "auto" }} disabled={busy}
                  data-testid={`memory-delete-${m.id}`}
                  onClick={() => act(() => deleteMemory(m.id))}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="tw-addform" style={{ marginTop: 10 }}>
          <input className="tw-input" placeholder="Add a memory yourself…" value={memText} data-testid="memory-input"
            onChange={(e) => setMemText(e.target.value)} style={{ minWidth: 300 }} />
          <button type="button" className="tw-btn" disabled={busy || !memText.trim()} data-testid="memory-add"
            onClick={() => act(async () => { await addMemory(memText.trim()); setMemText(""); })}>
            <Plus size={13} /> Remember
          </button>
        </div>
      </section>

      {error && <p className="tw-error" data-testid="settings-error">{error}</p>}
    </div>
  );
}
