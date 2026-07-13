"use client";

import { useEffect, useState } from "react";
import { LogIn, ShieldCheck } from "lucide-react";

import { fetchMe, login } from "@/lib/api";
import { clearUserToken, getUserToken, storeUser, storeUserToken } from "@/lib/session";
import { friendlyError } from "@/lib/utils";

type Status = "checking" | "form" | "authed";

// App-level sign-in gate (spec F1). Sits above SessionProvider so the agent session — which
// 401s without a signed-in user — never mounts until a token is in hand. Per-tab token
// (sessionStorage) is deliberate: two users side-by-side in two tabs is the demo.
export default function SignInGate({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [status, setStatus] = useState<Status>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // On mount, validate any existing token; a stale/invalid one drops back to the form.
  useEffect(() => {
    let cancelled = false;
    if (!getUserToken()) {
      setStatus("form");
      return () => { cancelled = true; };
    }
    void (async () => {
      try {
        const { user } = await fetchMe();
        if (cancelled) return;
        storeUser(user);
        setStatus("authed");
      } catch {
        if (cancelled) return;
        clearUserToken();
        setStatus("form");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { token, user } = await login(username.trim(), password);
      storeUserToken(token);
      storeUser(user);
      setStatus("authed");
    } catch (err) {
      // On a 401 the backend returns "Invalid username or password." verbatim.
      setError(friendlyError(err, "Sign in failed. Please try again."));
      setBusy(false);
    }
  };

  if (status === "authed") {
    return <>{children}</>;
  }

  if (status === "checking") {
    return (
      <div className="min-h-screen bg-app px-6 py-10 text-text-primary">
        <div className="mx-auto flex min-h-[70vh] max-w-lg items-center justify-center">
          <div className="w-full rounded-[2rem] border border-border-subtle bg-surface-1/80 p-10 text-center shadow-[0_24px_60px_rgba(0,0,0,0.1)] backdrop-blur-2xl">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-primary/20 text-brand-primary">
              <ShieldCheck size={24} />
            </div>
            <h1 className="mt-6 text-2xl font-bold uppercase tracking-[0.16em]">Restoring Session</h1>
            <p className="mt-3 text-sm leading-relaxed text-text-muted">
              Checking your sign-in before loading the workspace.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-app px-6 py-10 text-text-primary">
      <div className="mx-auto flex min-h-[70vh] max-w-lg items-center justify-center">
        <div className="w-full rounded-[2rem] border border-border-subtle bg-surface-1/80 p-10 shadow-[0_24px_60px_rgba(0,0,0,0.1)] backdrop-blur-2xl">
          <div className="text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-primary/20 text-brand-primary">
              <ShieldCheck size={24} />
            </div>
            <h1 className="mt-6 text-2xl font-bold uppercase tracking-[0.16em]">Sign In</h1>
            <p className="mt-3 text-sm leading-relaxed text-text-muted">
              Sign in to your Personal Assistant workspace.
            </p>
          </div>

          <form className="mt-8 flex flex-col gap-4 text-left" onSubmit={submit}>
            <label className="flex flex-col gap-1.5 text-xs font-bold uppercase tracking-[0.12em] text-text-muted">
              Username
              <input
                type="text"
                name="username"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                data-testid="signin-username"
                className="rounded-xl border border-border-subtle bg-surface-1 px-4 py-3 text-sm font-normal normal-case tracking-normal text-text-primary outline-none transition focus:border-brand-primary"
              />
            </label>
            <label className="flex flex-col gap-1.5 text-xs font-bold uppercase tracking-[0.12em] text-text-muted">
              Password
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="signin-password"
                className="rounded-xl border border-border-subtle bg-surface-1 px-4 py-3 text-sm font-normal normal-case tracking-normal text-text-primary outline-none transition focus:border-brand-primary"
              />
            </label>

            {error && (
              <p
                role="alert"
                data-testid="signin-error"
                className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-text-primary"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy || !username.trim() || !password}
              data-testid="signin-submit"
              className="interactive-control mt-2 inline-flex items-center justify-center rounded-xl bg-brand-primary px-5 py-3 text-xs font-bold uppercase tracking-[0.18em] text-white shadow-[0_12px_32px_rgba(0,115,234,0.3)] transition hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              <LogIn size={14} strokeWidth={2.5} className="mr-2" />
              {busy ? "Signing In…" : "Sign In"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
