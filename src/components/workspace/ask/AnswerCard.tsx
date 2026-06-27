"use client";

import { useState } from "react";
import {
  ShieldCheck,

  BarChart3,
  Table as TableIcon,
  Info,
  Lightbulb,
  Check,
  Clock,
  Database,
  Play,
  RotateCcw,
} from "lucide-react";
import { SqlBlock } from "./SqlBlock";
import { ProgressStepper } from "./ProgressStepper";
import { ResultChart } from "./ResultChart";
import { SourceChip } from "./SourceChip";
import type { AnswerData } from "@/types/tallyai";

export type { AnswerData };

interface Props {
  data: AnswerData;
  onOpenSource: (queryId: string) => void;
  onRun?: () => void;
  onRetry?: () => void;
  onEdit?: () => void;
}

const confidenceMeta = {
  low: { label: "Low confidence", color: "text-destructive bg-destructive/10" },
  medium: { label: "Medium confidence", color: "text-secondary-foreground bg-secondary/30" },
  high: { label: "High confidence", color: "text-primary bg-primary/10" },
};

const failureMeta = {
  blocked: { title: "Blocked by safety", icon: ShieldCheck },
  insufficient_data: { title: "Insufficient data", icon: Database },
  timeout: { title: "Query timed out", icon: Clock },
};

export function AnswerCard({ data, onOpenSource, onRun, onRetry, onEdit }: Props) {
  const [view, setView] = useState<"chart" | "table">("chart");

  const failure =
    data.failure ?? (data.safety?.blocked ? { kind: "blocked" as const, title: "Blocked by safety", reason: data.safety.reason ?? "Query was blocked by safety rules." } : null);
  const state: NonNullable<AnswerData["pipelineState"]> = failure ? "failed" : data.pipelineState ?? "complete";
  const showResults = state === "complete";

  return (
    <article className="rounded-2xl border border-border bg-background p-5 space-y-4 shadow-sm">
      {/* SQL + explanation */}
      <SqlBlock sql={data.sql} explanation={data.explanation} metrics={data.metrics} />

      {/* Safety / progress */}
      {state === "failed" && failure ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4">
          <div className="flex items-start gap-3">
            {(() => {
              const Icon = failureMeta[failure.kind].icon;
              return <Icon className="h-4 w-4 text-destructive shrink-0 mt-0.5" />;
            })()}
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-destructive">{failure.title}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{failure.reason}</div>
              {onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium hover:bg-muted transition-colors"
                >
                  <RotateCcw className="h-3 w-3" /> Retry
                </button>
              )}
            </div>
          </div>
        </div>
      ) : (
        <ProgressStepper steps={data.steps} />
      )}

      {state === "preview" && (
        <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Preview before run</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Read-only query is ready. Review the SQL, then run when you're satisfied.
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {onEdit && (
              <button
                type="button"
                onClick={onEdit}
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted transition-colors"
              >
                Edit & re-ask
              </button>
            )}
            {onRun && (
              <button
                type="button"
                onClick={onRun}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-xs font-semibold hover:brightness-110 transition-all"
              >
                <Play className="h-3 w-3" /> Run query
              </button>
            )}
          </div>
        </div>
      )}

      {showResults && (
        <>
          {/* Result */}

          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="inline-flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-0.5">
                <button
                  type="button"
                  onClick={() => setView("chart")}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    view === "chart" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
                  }`}
                >
                  <BarChart3 className="h-3 w-3" /> Chart
                </button>
                <button
                  type="button"
                  onClick={() => setView("table")}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    view === "table" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground"
                  }`}
                >
                  <TableIcon className="h-3 w-3" /> Table
                </button>
              </div>
              {data.truncated && (
                <span className="text-[11px] text-muted-foreground">Results truncated to 1,000 rows</span>
              )}
            </div>

            {view === "chart" ? (
              <ResultChart data={data.chart} yLabel="Revenue (USD)" />
            ) : (
              <div className="rounded-xl border border-border bg-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 border-b border-border">
                    <tr>
                      {data.table.columns.map((c) => (
                        <th key={c} className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.table.rows.map((row, i) => (
                      <tr key={i} className="border-b border-border last:border-0">
                        {row.map((cell, j) => (
                          <td key={j} className="px-4 py-2 font-mono text-xs">{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Summary */}
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              <Info className="h-3 w-3" /> Summary
            </div>
            <p className="mt-2 text-sm leading-relaxed text-foreground">
              {data.summaryParts.map((p, i) =>
                p.type === "text" ? (
                  <span key={i}>{p.text}</span>
                ) : (
                  <SourceChip key={i} {...p} onOpen={onOpenSource} />
                )
              )}
            </p>
          </div>

          {/* Reasoning split */}
          <div className="grid lg:grid-cols-2 gap-3">
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-primary">
                <Check className="h-3 w-3" /> What the data shows
              </div>
              <ul className="mt-2 space-y-1.5 text-sm text-foreground">
                {data.facts.map((f, i) => (
                  <li key={i} className="leading-relaxed">· {f}</li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-widest text-secondary-foreground">
                <Lightbulb className="h-3 w-3" /> What it might mean
              </div>
              <div className="mt-2 space-y-3">
                {data.hypotheses.map((h, i) => (
                  <div key={i} className="rounded-lg border border-border bg-muted/30 p-3">
                    <div className="flex items-start justify-between gap-2 flex-wrap">
                      <div className="text-sm font-semibold">Hypothesis: {h.title}</div>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {h.correlation && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-secondary/20 px-2 py-0.5 text-[10px] font-medium text-secondary-foreground">
                            <ShieldCheck className="h-2.5 w-2.5" /> Correlation, not proven causation
                          </span>
                        )}
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${confidenceMeta[h.confidence].color}`}>
                          {confidenceMeta[h.confidence].label}
                        </span>
                      </div>
                    </div>
                    <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{h.body}</p>
                    {h.chips && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {h.chips.map((c, j) => (
                          <SourceChip key={j} {...c} onOpen={onOpenSource} />
                        ))}
                      </div>
                    )}
                    <div className="mt-2 text-[10px] text-muted-foreground">Coverage: {h.coverage}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </article>
  );
}
