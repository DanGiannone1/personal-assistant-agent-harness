"use client";

import { useState, useRef, useCallback, FormEvent, KeyboardEvent } from "react";
import { ACCEPTED_TYPES } from "@/lib/constants";

interface InputBarProps {
  onSend: (message: string) => void;
  onUpload?: (file: File) => Promise<void>;
  disabled: boolean;
  isStreaming?: boolean;
  onStop?: () => void;
  isUploadingFile?: boolean;
  uploadingFileName?: string | null;
}

export default function InputBar({
  onSend,
  onUpload,
  disabled,
  isStreaming,
  onStop,
  isUploadingFile,
  uploadingFileName,
}: InputBarProps) {
  const [input, setInput] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [localUploading, setLocalUploading] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const uploadBusy = localUploading || Boolean(isUploadingFile);

  function resetInputHeight() {
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed && !selectedFile) return;

    if (selectedFile && onUpload) {
      setLocalUploading(true);
      await onUpload(selectedFile);
      setSelectedFile(null);
      setLocalUploading(false);
      if (!trimmed) return;
    }

    if (trimmed) {
      onSend(trimmed);
      setInput("");
      resetInputHeight();
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit(e);
    }
  }

  const handleTextareaChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  const canSend = Boolean(input.trim() || selectedFile);

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      className="sticky bottom-0 pb-8 pt-2 bg-transparent z-20"
    >
      <div className="mx-auto w-full max-w-3xl px-4">
        {(selectedFile || uploadBusy) && (
          <div className="mb-3 inline-flex items-center gap-3 rounded-xl border border-var(--color-border-subtle)/80 bg-var(--color-app)/80 backdrop-blur-md px-4 py-2 text-sm text-var(--color-text-primary) shadow-xl animate-fade-in">
            <span className="max-w-[220px] truncate font-bold text-[13px] tracking-tight">{uploadingFileName || selectedFile?.name || "Processing…"}</span>
            {uploadBusy ? (
              <span className="inline-flex items-center gap-2 text-var(--color-brand-primary)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="animate-spin">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56" />
                </svg>
              </span>
            ) : (
              <>
                <span className="text-var(--color-text-muted) font-mono text-[11px]">{((selectedFile?.size || 0) / 1024).toFixed(0)} KB</span>
                <button
                  type="button"
                  onClick={() => setSelectedFile(null)}
                  className="rounded-full p-1 text-var(--color-text-muted) hover:text-var(--color-brand-warning) transition-colors"
                  aria-label={`Remove file ${selectedFile?.name || "selected file"}`}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </>
            )}
          </div>
        )}

        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED_TYPES}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) setSelectedFile(file);
            e.target.value = "";
          }}
          className="hidden"
          aria-label="Upload file"
        />

        <div className={`flex items-end gap-2 rounded-2xl border bg-var(--color-app)/70 backdrop-blur-2xl p-1.5 transition-all duration-500 relative overflow-hidden group ${
          inputFocused 
            ? "border-var(--color-brand-primary)/60 shadow-[0_0_40px_rgba(0,115,234,0.15)] bg-var(--color-app)/90"
            : "border-var(--color-border-subtle)/80 shadow-[0_8px_24px_rgba(0,0,0,.08)]"
        }`}>
          <div className="absolute top-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent" />

          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={disabled || uploadBusy}
            aria-label="Attach file"
            className="p-2.5 text-var(--color-text-muted) hover:text-var(--color-brand-primary) rounded-xl transition-all hover:bg-var(--color-brand-primary)/10 disabled:opacity-40"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </button>

          <textarea
            ref={textareaRef}
            data-testid="chat-input"
            value={input}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
            placeholder="Message your assistant…"
            disabled={disabled || uploadBusy}
            rows={1}
            className="min-h-10 max-h-52 flex-1 resize-none bg-transparent px-3 py-2.5 text-[15px] font-medium leading-relaxed text-var(--color-text-primary) outline-none placeholder-var(--color-text-muted) disabled:opacity-50 font-sans"
            aria-label="Message input"
          />

          {isStreaming ? (
            <button
              data-testid="stop-button"
              type="button"
              onClick={onStop}
              className="flex h-10 shrink-0 items-center gap-2 rounded-xl border border-var(--color-brand-warning)/40 bg-var(--color-brand-warning)/10 px-4 text-[11px] font-bold uppercase tracking-widest text-var(--color-brand-warning) hover:bg-var(--color-brand-warning)/20 transition-all"
              aria-label="Stop generation"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <rect x="4" y="4" width="16" height="16" rx="2" />
              </svg>
              Stop
            </button>
          ) : (
            <button
              data-testid="send-button"
              type="submit"
              disabled={disabled || uploadBusy || !canSend}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-var(--color-brand-primary) to-var(--color-brand-accent) text-white shadow-[0_4px_15px_rgba(0,115,234,0.35)] hover:brightness-110 disabled:opacity-40 disabled:grayscale transition-all"
              aria-label="Send message"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="ml-0.5">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          )}
        </div>
        <p className="composer-footer">AI can make mistakes. Double-check responses.</p>
      </div>
    </form>
  );
}
