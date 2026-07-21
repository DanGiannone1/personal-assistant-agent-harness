"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { ChatMessage } from "@/lib/types";
import MessageBubble from "./MessageBubble";

interface MessageListProps {
  messages: ChatMessage[];
  onSuggestion?: (text: string) => void;
}

// Showcase the assistant's active Engagement capabilities.
const SUGGESTIONS = [
  { icon: "gauge", label: "Review engagements", description: "See the Engagements available to you", prompt: "List my engagements." },
  { icon: "strategy", label: "Open an Engagement", description: "Navigate to an Engagement you can access", prompt: "Open an Engagement for me. If you need to know which one, ask me to choose." },
  { icon: "checklist", label: "Create an Engagement", description: "Start a new Engagement workspace", prompt: "Create a new Engagement. Ask me for any details you need." },
  { icon: "shield", label: "Update engagement status", description: "Set a status and explain why", prompt: "Update an Engagement's status. Ask me which Engagement, the new status, and the reason." },
];

function SuggestionIcon({ icon }: { icon: string }) {
  const cls = "shrink-0 text-brand";
  switch (icon) {
    case "checklist":
      return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={cls}><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>;
    case "gauge":
      return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={cls}><path d="M12 20v-6M6 20V10M18 20V4"/></svg>;
    case "doc":
      return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={cls}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>;
    case "shield":
      return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={cls}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>;
    case "strategy":
      return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={cls}><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/></svg>;
    default:
      return null;
  }
}

export default function MessageList({ messages, onSuggestion }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);
  const rafRef = useRef<number>(0);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    shouldAutoScroll.current = distanceFromBottom < 180;
    setShowJumpToLatest(distanceFromBottom > 260);
  }, []);

  useEffect(() => {
    if (shouldAutoScroll.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: "smooth" });
        setShowJumpToLatest(false);
      });
    }
  }, [messages]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="flex-1 overflow-x-hidden overflow-y-auto"
      role="log"
      aria-label="Chat messages"
      aria-live="polite"
    >
      <div className="mx-auto w-full max-w-3xl px-4 py-5 md:py-10">
        {messages.length === 0 ? (
          <div className="mx-auto flex min-h-[68vh] flex-col justify-center">
            <h2 className="text-3xl font-extrabold tracking-tight text-text-primary md:text-4xl">How can I help?</h2>
            <p className="mt-4 text-lg text-text-secondary">Ask me to review, navigate, create, or update your Engagements.</p>

            {onSuggestion && (
              <div className="mt-10 grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
                {SUGGESTIONS.map((s, i) => (
                  <button
                    key={s.prompt}
                    type="button"
                    onClick={() => onSuggestion(s.prompt)}
                    style={{ animationDelay: `${i * 40}ms` }}
                    className="interactive-chip animate-fade-in group flex flex-col items-start gap-3 rounded-2xl border border-border-subtle bg-surface-1 p-5 text-left transition hover:border-brand-primary hover:bg-surface-2"
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-text-primary group-hover:bg-brand-primary group-hover:text-white transition-colors">
                      <SuggestionIcon icon={s.icon} />
                    </div>
                    <div>
                      <p className="text-[15px] font-bold tracking-wide text-text-primary group-hover:text-brand-primary transition-colors min-h-[2.6em] flex items-start">{s.label}</p>
                      <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">{s.description}</p>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((msg, index) => (
              <div
                key={msg.id}
                className="animate-fade-in"
                style={{ animationDelay: `${Math.min(index * 30, 160)}ms` }}
              >
                <MessageBubble message={msg} />
              </div>
            ))}
          </div>
        )}

      </div>

      {showJumpToLatest && (
        <button
          type="button"
          data-testid="jump-latest-button"
          onClick={() => {
            shouldAutoScroll.current = true;
            containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: "smooth" });
            setShowJumpToLatest(false);
          }}
          className="interactive-control animate-fade-in fixed bottom-28 left-1/2 z-20 -translate-x-1/2 flex items-center gap-1.5 rounded-full border border-border-subtle bg-surface-2/95 px-3 py-2 text-xs text-text-primary shadow-[0_10px_30px_rgba(0,0,0,.12)] backdrop-blur md:bottom-32 md:left-auto md:right-8 md:translate-x-0"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
          Jump to latest
        </button>
      )}
    </div>
  );
}
