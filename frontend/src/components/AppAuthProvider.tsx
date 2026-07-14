"use client";

import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore } from "react";
import { KeyRound, LogIn } from "lucide-react";

import { AppUser, fetchMe, getAppToken, getStoredUser, login, logout } from "@/lib/appAuth";
import {
  isBrowserAuthEnabled,
  signIn as entraSignIn,
  signOut as entraSignOut,
} from "@/lib/auth";

// Demo accounts stay available for automated tests unless explicitly disabled
// at build time (mirrors the orchestrator's DEMO_LOGIN_ENABLED runtime flag).
const demoLoginEnabled = (process.env.NEXT_PUBLIC_DEMO_LOGIN || "true").toLowerCase() !== "false";

interface AppAuthValue {
  user: AppUser;
  signOut: () => Promise<void>;
}

const AppAuthContext = createContext<AppAuthValue | null>(null);
const subscribeHydration = () => () => undefined;

export function useAppAuth(): AppAuthValue {
  const ctx = useContext(AppAuthContext);
  if (!ctx) throw new Error("useAppAuth must be used within AppAuthProvider");
  return ctx;
}

// Gate the whole app behind sign-in. Children (including the SessionProvider
// that auto-creates agent sessions) render ONLY once signed in, so no
// unauthenticated requests ever fire. Two paths resolve a user: the demo
// token (X-Auth-Token) and, when Entra auth is enabled, the MSAL bearer.
export default function AppAuthProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  // The server snapshot deliberately remains false. A saved demo token is only
  // read after hydration, so server and first client render agree.
  const hydrated = useSyncExternalStore(subscribeHydration, () => true, () => false);
  const [resolvedUser, setResolvedUser] = useState<AppUser | null>(null);
  const [entraResolved, setEntraResolved] = useState(false);
  const demoUser = hydrated && getAppToken() ? getStoredUser() : null;
  const user = resolvedUser ?? demoUser;
  const waitingForEntra = hydrated && isBrowserAuthEnabled() && !getAppToken() && !entraResolved;

  useEffect(() => {
    if (hydrated && isBrowserAuthEnabled() && !getAppToken()) {
      // Entra path: this also completes a pending MSAL redirect. If a signed-in
      // account exists, /auth/me resolves (auto-provisioning on first sight).
      fetchMe()
        .then((me) => setResolvedUser(me))
        .finally(() => setEntraResolved(true));
    }
    const onExpired = () => setResolvedUser(null);
    window.addEventListener("app-auth-expired", onExpired);
    return () => window.removeEventListener("app-auth-expired", onExpired);
  }, [hydrated]);

  const signOut = useCallback(async () => {
    if (user?.identity === "entra") {
      await logout(); // clears local storage; server call is a no-op without a demo token
      await entraSignOut(); // MSAL redirect tears the SPA down and returns signed out
      return;
    }
    await logout();
    // Full reload: tears down the agent session, per-user storage reads, and any
    // in-flight streams in one deterministic step.
    window.location.reload();
  }, [user]);

  if (!hydrated || waitingForEntra) return null;
  if (!user) return <SignIn onSignedIn={setResolvedUser} />;

  return <AppAuthContext.Provider value={{ user, signOut }}>{children}</AppAuthContext.Provider>;
}

function SignIn({ onSignedIn }: { onSignedIn: (u: AppUser) => void }) {
  const entraEnabled = isBrowserAuthEnabled();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // With Entra enabled the demo form is a secondary, collapsed option.
  const [showDemo, setShowDemo] = useState(!entraEnabled);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const u = await login(username.trim(), password);
      onSignedIn(u);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  const microsoft = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await entraSignIn(); // redirect flow — navigates away
    } catch (err) {
      setError(err instanceof Error ? err.message : "Microsoft sign-in failed.");
      setBusy(false);
    }
  };

  const demoForm = (
    <>
      <label className="mt-8 block text-[11px] font-bold uppercase tracking-[0.14em] text-text-muted">
        Username
        <input
          data-testid="signin-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus={!entraEnabled}
          autoComplete="username"
          className="mt-2 w-full rounded-xl border border-border-subtle bg-surface-2 px-4 py-3 text-[15px] font-medium normal-case tracking-normal text-text-primary outline-none focus:border-brand-primary"
        />
      </label>
      <label className="mt-4 block text-[11px] font-bold uppercase tracking-[0.14em] text-text-muted">
        Password
        <input
          data-testid="signin-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          className="mt-2 w-full rounded-xl border border-border-subtle bg-surface-2 px-4 py-3 text-[15px] font-medium normal-case tracking-normal text-text-primary outline-none focus:border-brand-primary"
        />
      </label>

      <button
        type="submit"
        data-testid="signin-submit"
        disabled={busy || !username.trim() || !password}
        className="interactive-control mt-6 inline-flex w-full items-center justify-center rounded-xl bg-brand-primary px-5 py-3 text-xs font-bold uppercase tracking-[0.18em] text-white shadow-[0_12px_32px_rgba(0,115,234,0.3)] transition hover:bg-brand-strong disabled:opacity-50"
      >
        <LogIn size={14} strokeWidth={2.5} className="mr-2" />
        {busy ? "Signing in…" : "Sign in"}
      </button>

      <p className="mt-6 text-center text-xs text-text-muted">
        Demo accounts: <code>dan</code> · <code>ava</code> · <code>sam</code> (password <code>demo1234</code>)
      </p>
    </>
  );

  return (
    <div className="min-h-screen bg-app px-6 py-10 text-text-primary">
      <div className="mx-auto flex min-h-[80vh] max-w-md items-center justify-center">
        <form
          onSubmit={submit}
          data-testid="signin-form"
          className="w-full rounded-[2rem] border border-border-subtle bg-surface-1/80 p-10 shadow-[0_24px_60px_rgba(0,0,0,0.1)] backdrop-blur-2xl"
        >
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-primary/20 text-brand-primary">
            <KeyRound size={24} />
          </div>
          <h1 className="mt-6 text-center text-2xl font-bold uppercase tracking-[0.16em]">Sign In</h1>
          <p className="mt-2 text-center text-sm text-text-muted">
            Your workspace is personal — sign in to load it.
          </p>

          {entraEnabled && (
            <button
              type="button"
              data-testid="signin-microsoft"
              onClick={microsoft}
              disabled={busy}
              className="interactive-control mt-8 inline-flex w-full items-center justify-center rounded-xl bg-brand-primary px-5 py-3 text-xs font-bold uppercase tracking-[0.18em] text-white shadow-[0_12px_32px_rgba(0,115,234,0.3)] transition hover:bg-brand-strong disabled:opacity-50"
            >
              <LogIn size={14} strokeWidth={2.5} className="mr-2" />
              {busy ? "Redirecting…" : "Sign in with Microsoft"}
            </button>
          )}

          {entraEnabled && demoLoginEnabled && !showDemo && (
            <button
              type="button"
              data-testid="signin-show-demo"
              onClick={() => setShowDemo(true)}
              className="mt-4 w-full text-center text-xs text-text-muted underline-offset-2 hover:underline"
            >
              Use a demo account
            </button>
          )}

          {(!entraEnabled || (demoLoginEnabled && showDemo)) && demoForm}

          {error && (
            <p data-testid="signin-error" className="mt-4 rounded-xl border border-red-400/40 bg-red-400/10 px-4 py-3 text-sm">
              {error}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
