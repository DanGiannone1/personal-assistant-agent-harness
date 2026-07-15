"use client";

import { useRouter } from "next/navigation";
import {
  Home,
  CheckSquare,
  Calendar,
  Files,
  Sparkles,
  Bell,
  LogOut,
  FolderKanban,
  Settings,
  Menu,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AppState } from "@/lib/types";
import { useAppAuth } from "@/components/AppAuthProvider";

// The CSA Workbench left-nav rail, shared by the host app and the Assistant workspace so
// the workspace reads as a page *of* CSA Workbench (not a separate chatbot). Host items
// navigate the app (onNavigate → viewRoute); the ✦ AI Workbench item routes to /assistant.
export default function WorkbenchNav({
  viewRoute,
  onNavigate,
  assistantActive = false,
}: {
  appState: AppState | null;
  viewRoute: string;
  onNavigate: (route: string) => void;
  assistantActive?: boolean;
}) {
  const router = useRouter();
  const { user, signOut } = useAppAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLElement>(null);

  const closeDrawer = () => {
    setDrawerOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  useEffect(() => {
    if (!drawerOpen) return;
    const drawer = drawerRef.current;
    const focusable = () =>
      [
        ...(drawer?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ) ?? []),
      ].filter((element) => element.offsetParent !== null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeDrawer();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = focusable();
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    let focusFrame: number | undefined;
    const visibilityFrame = requestAnimationFrame(() => {
      focusFrame = requestAnimationFrame(() => focusable()[0]?.focus());
    });
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      cancelAnimationFrame(visibilityFrame);
      if (focusFrame !== undefined) cancelAnimationFrame(focusFrame);
    };
  }, [drawerOpen]);

  const navItem = (route: string, label: string, Icon: typeof Home) => {
    const active =
      !assistantActive &&
      (viewRoute === route ||
        (route !== "/home" && viewRoute.startsWith(route)));
    return (
      <button
        type="button"
        onClick={() => {
          onNavigate(route);
          if (drawerOpen) closeDrawer();
        }}
        className={`tw-nav-item ${active ? "tw-nav-item-active" : ""}`}
        data-testid={`nav-${route.replace(/\//g, "-")}`}
        aria-current={active ? "page" : undefined}
      >
        <Icon size={16} strokeWidth={2.25} />
        <span>{label}</span>
      </button>
    );
  };

  const navigation = (
    <nav
      ref={drawerRef}
      className={`tw-nav ${drawerOpen ? "tw-nav-drawer-open" : ""}`}
      id="workbench-nav"
      aria-label="Workspace navigation"
      data-testid={drawerOpen ? "nav-drawer" : undefined}
    >
      <div className="tw-nav-mobile-head">
        <span>Navigate</span>
        <button
          type="button"
          className="tw-btn-ghost"
          aria-label="Close navigation"
          onClick={closeDrawer}
        >
          <X size={18} />
        </button>
      </div>
      {navItem("/engagements", "Engagements", FolderKanban)}
      <div data-testid="personal-space">
        <div className="tw-nav-section" data-testid="personal-nav-section">
          My work
        </div>
        {navItem("/home", "Home", Home)}
        {navItem("/todo", "Tasks", CheckSquare)}
        {navItem("/calendar", "Calendar", Calendar)}
        {navItem("/documents", "Documents", Files)}
        {navItem("/reminders", "Reminders", Bell)}
      </div>
      <div className="tw-nav-section">Assistant</div>
      <button
        type="button"
        data-testid="nav-assistant"
        onClick={() => {
          router.push("/assistant");
          if (drawerOpen) closeDrawer();
        }}
        className={`tw-nav-item ${assistantActive ? "tw-nav-item-active" : ""}`}
      >
        <Sparkles size={16} strokeWidth={2.25} />
        <span>Assistant</span>
      </button>

      {navItem("/settings", "Settings", Settings)}

      {/* Signed-in user chip — the whole workspace is this user's. */}
      <div className="mt-auto pt-4 border-t border-border-subtle/60">
        <div
          className="flex items-center gap-2 px-2 py-1.5"
          data-testid="user-chip"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-primary/20 text-[11px] font-bold uppercase text-brand-primary">
            {user.displayName.slice(0, 1)}
          </span>
          <span
            className="min-w-0 flex-1 truncate text-[13px] font-semibold"
            data-testid="user-chip-name"
          >
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

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="tw-nav-toggle"
        data-testid="nav-toggle"
        aria-label="Open navigation"
        aria-controls="workbench-nav"
        aria-expanded={drawerOpen}
        onClick={() => setDrawerOpen(true)}
      >
        <Menu size={20} />
      </button>
      {drawerOpen && (
        <button
          type="button"
          className="tw-nav-backdrop"
          data-testid="nav-backdrop"
          aria-label="Close navigation"
          onClick={closeDrawer}
        />
      )}
      {navigation}
    </>
  );
}
