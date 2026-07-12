"use client";

import { useRouter } from "next/navigation";
import { Home, CheckSquare, Calendar, Files, Sparkles, Bell, LogOut, FolderKanban } from "lucide-react";
import { AppState } from "@/lib/types";
import { useAppAuth } from "@/components/AppAuthProvider";

// The Personal Assistant left-nav rail, shared by the host app and the Assistant workspace so
// the workspace reads as a page *of* Personal Assistant (not a separate chatbot). Host items
// navigate the app (onNavigate → viewRoute); the ✦ AI Workbench item routes to /assistant.
export default function WorkbenchNav({
  viewRoute, onNavigate, assistantActive = false,
}: {
  appState: AppState | null;
  viewRoute: string;
  onNavigate: (route: string) => void;
  assistantActive?: boolean;
}) {
  const router = useRouter();
  const { user, signOut } = useAppAuth();

  const navItem = (route: string, label: string, Icon: typeof Home) => {
    const active = !assistantActive && (viewRoute === route || (route !== "/home" && viewRoute.startsWith(route)));
    return (
      <button type="button" onClick={() => onNavigate(route)} className={`tw-nav-item ${active ? "tw-nav-item-active" : ""}`} data-testid={`nav-${route.replace(/\//g, "-")}`}>
        <Icon size={16} strokeWidth={2.25} />
        <span>{label}</span>
      </button>
    );
  };

  return (
    <nav className="tw-nav">
      {navItem("/home", "Home", Home)}
      <div className="tw-nav-section">Workspace</div>
      {navItem("/projects", "Projects", FolderKanban)}
      {navItem("/todo", "Tasks", CheckSquare)}
      {navItem("/calendar", "Calendar", Calendar)}
      {navItem("/documents", "Documents", Files)}
      {navItem("/reminders", "Reminders", Bell)}
      <div className="tw-nav-section">Assistant</div>
      <button
        type="button"
        data-testid="nav-assistant"
        onClick={() => router.push("/assistant")}
        className={`tw-nav-item ${assistantActive ? "tw-nav-item-active" : ""}`}
      >
        <Sparkles size={16} strokeWidth={2.25} />
        <span>Assistant</span>
      </button>

      {/* Signed-in user chip — the whole workspace is this user's. */}
      <div className="mt-auto pt-4 border-t border-border-subtle/60">
        <div className="flex items-center gap-2 px-2 py-1.5" data-testid="user-chip">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-primary/20 text-[11px] font-bold uppercase text-brand-primary">
            {user.displayName.slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1 truncate text-[13px] font-semibold" data-testid="user-chip-name">
            {user.displayName}
          </span>
          <button
            type="button"
            data-testid="sign-out"
            title="Sign out"
            onClick={() => void signOut()}
            className="interactive-control rounded-lg p-1.5 text-text-muted transition hover:text-text-primary"
          >
            <LogOut size={14} />
          </button>
        </div>
      </div>
    </nav>
  );
}
