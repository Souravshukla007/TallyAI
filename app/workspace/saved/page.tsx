"use client";

import Link from "next/link";
import { Bookmark, Star, Play } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";

export default function SavedQueriesPage() {
  const { data: saved, loading } = useApi(() => api.listSavedQueries("prod"), []);

  if (loading || !saved) {
    return <div className="mx-auto max-w-5xl px-6 py-8 text-sm text-muted-foreground">Loading saved queries…</div>;
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">Saved queries</h1>
      <p className="mt-1 text-sm text-muted-foreground">Starred questions for one-click re-run.</p>

      <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-3">
        {saved.map((s) => (
          <div key={s.name} className="group flex items-center gap-3 rounded-xl border border-border bg-card p-4 hover:border-primary/40 transition-colors">
            <div className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Bookmark className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate">{s.name}</div>
              <div className="text-xs text-muted-foreground">{s.folder} · last run {s.last}</div>
            </div>
            <button className="rounded-md p-1.5 text-muted-foreground hover:text-secondary-foreground hover:bg-muted" title="Unstar">
              <Star className="h-4 w-4 fill-current text-secondary-foreground" />
            </button>
            <Link href="/workspace/ask" className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground hover:brightness-110">
              <Play className="h-3 w-3" /> Run
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
