"use client";

import { Check, Loader2 } from "lucide-react";
import type { Step, StepState } from "@/types/tallyai";

export type { Step, StepState };

interface Props {
  steps: Step[];
}

export function ProgressStepper({ steps }: Props) {
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-1 overflow-x-auto">
        {steps.map((s, i) => (
          <div key={s.label} className="flex items-center gap-1 shrink-0">
            <div className="flex items-center gap-1.5">
              <span
                className={`inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${
                  s.state === "done"
                    ? "bg-primary text-primary-foreground"
                    : s.state === "running"
                      ? "bg-primary/20 text-primary"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {s.state === "done" ? (
                  <Check className="h-3 w-3" />
                ) : s.state === "running" ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  i + 1
                )}
              </span>
              <span
                className={`text-xs font-medium whitespace-nowrap ${
                  s.state === "done" || s.state === "running"
                    ? "text-foreground"
                    : "text-muted-foreground"
                }`}
              >
                {s.label}
              </span>
              {s.ms !== undefined && s.state === "done" && (
                <span className="font-mono text-[10px] text-muted-foreground">{s.ms}ms</span>
              )}
            </div>
            {i < steps.length - 1 && (
              <span
                className={`mx-1 h-px w-6 ${
                  s.state === "done" ? "bg-primary/60" : "bg-border"
                }`}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
