"use client";

import { Activity, CheckCircle2, AlertCircle, Play, FlaskConical } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";

export default function EvalPage() {
  const { data, loading } = useApi(() => api.getEvalReport(), []);

  if (loading || !data) {
    return <div className="mx-auto max-w-6xl px-6 py-8 text-sm text-muted-foreground">Loading eval…</div>;
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Eval & observability</h1>
          <p className="mt-1 text-sm text-muted-foreground">NL→SQL accuracy and runtime traces.</p>
        </div>
        <button
          disabled={data.labeledCount === 0}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110 disabled:opacity-40"
        >
          <Play className="h-3.5 w-3.5" /> Run evaluation
        </button>
      </div>

      {data.labeledCount === 0 ? (
        <div className="mt-10 rounded-2xl border border-dashed border-border p-12 text-center">
          <FlaskConical className="mx-auto h-8 w-8 text-muted-foreground" />
          <h2 className="mt-3 text-base font-semibold">No labeled examples yet</h2>
          <p className="mt-1 text-sm text-muted-foreground">Add at least one labeled question + expected SQL to run an evaluation.</p>
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-4">
          <section className="rounded-xl border border-border bg-card p-5">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-semibold">Accuracy</h2>
              <span className="text-xs text-muted-foreground">labeled set · {data.labeledCount} examples</span>
            </div>
            <div className="mt-4 font-mono text-4xl font-semibold text-primary">{data.currentAccuracy}%</div>
            <p className="text-xs text-muted-foreground">Current run · +{data.deltaPp} pp vs previous</p>

            <div className="mt-6 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Run history</div>
            <ul className="mt-2 divide-y divide-border">
              {data.history.map((r) => (
                <li key={r.run} className="flex items-center gap-3 py-2.5 text-sm">
                  <span className="font-mono text-xs text-muted-foreground w-32">{r.run}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className="h-full bg-primary" style={{ width: `${r.score}%` }} />
                  </div>
                  <span className="font-mono text-xs font-semibold w-14 text-right">{r.score}%</span>
                  <span className="text-xs text-muted-foreground w-12 text-right">{r.examples}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="grid grid-cols-2 gap-3">
            {data.stats.map((s) => (
              <div key={s.label} className="rounded-xl border border-border bg-card p-4">
                <div className="text-xs text-muted-foreground">{s.label}</div>
                <div className="mt-1 font-mono text-xl font-semibold">{s.value}</div>
              </div>
            ))}
          </section>
        </div>
      )}

      <section className="mt-6 rounded-xl border border-border bg-card overflow-hidden">
        <div className="flex items-center gap-2 border-b border-border px-5 py-3">
          <Activity className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold">Traces</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 border-b border-border">
              <tr className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
                <th className="text-left px-5 py-2">Question</th>
                <th className="text-left px-5 py-2">Tools</th>
                <th className="text-right px-5 py-2">Latency</th>
                <th className="text-right px-5 py-2">Cost</th>
                <th className="text-center px-5 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.traces.map((t, i) => (
                <tr key={i} className="border-b border-border last:border-0">
                  <td className="px-5 py-2.5 truncate max-w-xs">{t.q}</td>
                  <td className="px-5 py-2.5 font-mono text-xs text-muted-foreground">{t.tools.join(" · ")}</td>
                  <td className="px-5 py-2.5 text-right font-mono text-xs">{t.latencyMs} ms</td>
                  <td className="px-5 py-2.5 text-right font-mono text-xs">${t.costUsd.toFixed(4)}</td>
                  <td className="px-5 py-2.5 text-center">
                    {t.status === "ok" ? (
                      <CheckCircle2 className="inline h-4 w-4 text-primary" />
                    ) : t.status === "warn" ? (
                      <AlertCircle className="inline h-4 w-4 text-secondary-foreground" />
                    ) : (
                      <AlertCircle className="inline h-4 w-4 text-destructive" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
