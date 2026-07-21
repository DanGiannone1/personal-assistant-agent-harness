"use client";

// Persona settings are stored, legible, and adjustable — never silently inferred.

import { useState } from "react";
import { UserCog } from "lucide-react";
import type { AppState } from "@/lib/types";
import { putPersona } from "@/lib/api";
import { friendlyError } from "@/lib/utils";

export default function SettingsScreen({ appState, onRefresh }: {
  appState: AppState; onRefresh: () => Promise<void>;
}) {
  const persona = appState.user?.persona ?? {};
  const [role, setRole] = useState(persona.role ?? "");
  const [tone, setTone] = useState(persona.tone ?? "");
  const [outputPrefs, setOutputPrefs] = useState(persona.outputPrefs ?? "");
  const [language, setLanguage] = useState(persona.language ?? "English");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try { await fn(); await onRefresh(); } catch (err) { setError(friendlyError(err, "Save failed.")); }
    finally { setBusy(false); }
  };

  return (
    <div className="tw-screen" data-testid="settings-screen">
      <h1 className="tw-h1">Settings</h1>
      <p className="tw-subtle">Persona settings are visible and editable here.</p>

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

      {error && <p className="tw-error" data-testid="settings-error">{error}</p>}
    </div>
  );
}
