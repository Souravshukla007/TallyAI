"use client";

import { X, Clock } from "lucide-react";
import { useEffect } from "react";
import type { SupportingQuery } from "@/types/tallyai";

export type { SupportingQuery };

interface Props {
  open: boolean;
  activeId: string | null;
  queries: SupportingQuery[];
  onClose: () => void;
}

export function SupportingQueriesDrawer({ open, activeId, queries, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-foreground/30" onClick={onClose} />
      <aside className="w-full max-w-lg bg-background border-l border-border flex flex-col shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold">Supporting queries</h2>
            <p className="text-xs text-muted-foreground">Every number traces back to a query.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {queries.map((q) => (
            <div
              key={q.id}
              className={`rounded-xl border bg-card overflow-hidden transition-all ${
                q.id === activeId ? "border-primary shadow-md ring-1 ring-primary/30" : "border-border"
              }`}
            >
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-muted/30">
                <span className="text-xs font-semibold">{q.label}</span>
                <span className="inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
                  <Clock className="h-3 w-3" /> {q.latencyMs}ms
                </span>
              </div>
              <pre className="px-4 py-3 text-[11px] leading-relaxed font-mono text-foreground overflow-x-auto bg-foreground/[0.03]">
                {q.sql}
              </pre>
              {q.params && Object.keys(q.params).length > 0 && (
                <div className="px-4 py-2 border-t border-border text-[11px] text-muted-foreground font-mono">
                  {Object.entries(q.params).map(([k, v]) => (
                    <div key={k}>
                      {k} = <span className="text-foreground">{v}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="px-4 py-2 border-t border-border text-[10px] text-muted-foreground">
                Ran {q.timestamp} · read-only
              </div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
