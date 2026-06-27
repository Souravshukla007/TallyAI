"use client";

import { Lightbulb, Calendar, BarChart3, Plus } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";

export default function InsightsPage() {
  const { data: insights, loading } = useApi(() => api.listInsights("prod"), []);

  if (loading || !insights) {
    return <div className="mx-auto max-w-5xl px-6 py-8 text-sm text-muted-foreground">Loading insights…</div>;
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Insights & reports</h1>
          <p className="mt-1 text-sm text-muted-foreground">Scheduled analyses and one-off reports.</p>
        </div>
        <button className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110">
          <Plus className="h-3.5 w-3.5" /> New report
        </button>
      </div>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-3">
        {insights.map((i) => (
          <button
            key={i.title}
            type="button"
            className="text-left rounded-xl border border-border bg-card p-5 hover:border-primary/40 hover:shadow-sm transition-all"
          >
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary uppercase">
                <Lightbulb className="h-2.5 w-2.5" /> {i.tag}
              </span>
              <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
            </div>
            <h3 className="mt-3 text-base font-semibold">{i.title}</h3>
            <p className="mt-1 text-sm text-muted-foreground line-clamp-2">{i.body}</p>
            {i.schedule ? (
              <div className="mt-4 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Calendar className="h-3 w-3" /> {i.schedule}
              </div>
            ) : (
              <div className="mt-4 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground italic">
                Not scheduled
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
