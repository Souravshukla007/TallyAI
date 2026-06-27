"use client";

import { Copy, Sparkles } from "lucide-react";
import { useState } from "react";

interface Props {
  sql: string;
  explanation: string;
  metrics?: string[];
}

export function SqlBlock({ sql, explanation, metrics = [] }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-muted/40 px-4 py-2.5">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          Generated SQL
        </div>
        <div className="flex items-center gap-2">
          {metrics.length > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-medium text-primary">
              uses: {metrics.join(", ")}
            </span>
          )}
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            <Copy className="h-3 w-3" /> {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      <div className="grid lg:grid-cols-[1.4fr_1fr] divide-y lg:divide-y-0 lg:divide-x divide-border">
        <pre className="px-4 py-3 text-[12px] leading-relaxed font-mono text-foreground overflow-x-auto bg-foreground/[0.03]">
          {sql}
        </pre>
        <div className="px-4 py-3">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Explanation
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-foreground">{explanation}</p>
        </div>
      </div>
    </div>
  );
}
