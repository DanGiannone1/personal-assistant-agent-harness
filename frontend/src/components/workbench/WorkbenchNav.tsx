"use client";

import { useRouter } from "next/navigation";
import { Home, CheckSquare, Calendar, Files, Sparkles, Bell } from "lucide-react";
import { AppState } from "@/lib/types";

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
    </nav>
  );
}
