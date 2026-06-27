"use client";

import Link from "next/link";
import { TrendingUp, Users, DollarSign, Activity, ArrowRight, AlertTriangle, MessageSquare } from "lucide-react";
import { useState } from "react";
import { SupportingQueriesDrawer } from "@/components/workspace/ask/SupportingQueriesDrawer";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { DashboardMetric } from "@/types/tallyai";

const iconFor: Record<string, typeof DollarSign> = {
  rev: DollarSign,
  mrr: TrendingUp,
  users: Users,
  churn: Activity,
};

export default function DashboardPage() {
  const { data, loading } = useApi(() => api.getDashboard("prod"), []);
  const [drawerId, setDrawerId] = useState<string | null>(null);

  if (loading || !data) {
    return <div className="mx-auto max-w-6xl px-6 py-8 text-sm text-muted-foreground">Loading dashboard…</div>;
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-muted-foreground">Live metrics from your semantic layer.</p>
        </div>
        <Link
          href="/workspace/ask"
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110 transition-all"
        >
          <MessageSquare className="h-3.5 w-3.5" /> New question
        </Link>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {data.metrics.map((m: DashboardMetric) => {
          const Icon = iconFor[m.id] ?? Activity;
          return (
            <div key={m.id} className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{m.label}</span>
                <Icon className="h-4 w-4 text-primary" />
              </div>
              <button
                type="button"
                onClick={() => setDrawerId(m.queryId)}
                className="mt-3 block text-left font-mono text-2xl font-semibold hover:text-primary transition-colors"
              >
                {m.value}
                <span className="ml-1 text-[10px] opacity-70 align-top">◆</span>
              </button>
              <div className="mt-1 flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{m.period}</span>
                <span className={m.trend === "up" ? "text-primary" : "text-destructive"}>{m.delta}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="rounded-xl border border-border bg-card overflow-hidden">
          <header className="flex items-center justify-between border-b border-border px-5 py-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-secondary-foreground" />
              <h2 className="text-sm font-semibold">Needs attention</h2>
            </div>
            <Link href="/workspace/insights" className="text-xs text-primary hover:underline">View all</Link>
          </header>
          <ul className="divide-y divide-border">
            {data.attention.map((a) => (
              <li key={a.title}>
                <Link href="/workspace/ask" className="flex items-center gap-3 px-5 py-3 hover:bg-muted/30 transition-colors">
                  <span className="inline-flex shrink-0 rounded-full bg-secondary/20 px-2 py-0.5 text-[10px] font-semibold text-secondary-foreground uppercase">
                    {a.tag}
                  </span>
                  <span className="flex-1 truncate text-sm">{a.title}</span>
                  <span className="text-xs text-muted-foreground shrink-0">{a.time}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-xl border border-border bg-card overflow-hidden">
          <header className="flex items-center justify-between border-b border-border px-5 py-3">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-semibold">Recent activity</h2>
            </div>
            <Link href="/workspace/history" className="text-xs text-primary hover:underline">View all</Link>
          </header>
          <ul className="divide-y divide-border">
            {data.recent.map((r, i) => (
              <li key={i}>
                <Link href="/workspace/ask" className="flex items-center gap-3 px-5 py-3 hover:bg-muted/30 transition-colors">
                  <MessageSquare className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="truncate text-sm">{r.q}</div>
                    <div className="text-[11px] text-muted-foreground">{r.who} · {r.time}</div>
                  </div>
                  <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <SupportingQueriesDrawer
        open={drawerId !== null}
        activeId={drawerId}
        queries={data.supportingQueries}
        onClose={() => setDrawerId(null)}
      />
    </div>
  );
}
