"use client";

import Link from "next/link";
import { Search, Clock, Database, ArrowRight } from "lucide-react";
import { useState, useEffect } from "react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";

export default function HistoryPage() {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");

  // Debounce the search box, then let the API filter server-side via `?search=`.
  useEffect(() => {
    const id = setTimeout(() => setTerm(q), 250);
    return () => clearTimeout(id);
  }, [q]);

  const { data: items, loading } = useApi(() => api.listHistory("prod", term), [term]);
  const filtered = items ?? [];

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">History</h1>
      <p className="mt-1 text-sm text-muted-foreground">Every question your team has asked. Click to reopen the full answer.</p>

      <div className="mt-6 relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search questions…"
          className="w-full rounded-lg border border-border bg-card pl-9 pr-3 py-2 text-sm focus:outline-none focus:border-primary"
        />
      </div>

      {loading ? (
        <div className="mt-6 text-sm text-muted-foreground">Loading history…</div>
      ) : (
        <ul className="mt-6 divide-y divide-border rounded-xl border border-border bg-card">
          {filtered.length === 0 ? (
            <li className="px-5 py-10 text-center text-sm text-muted-foreground">No matches.</li>
          ) : (
            filtered.map((it, i) => (
              <li key={i}>
                <Link href="/workspace/ask" className="flex items-center gap-3 px-5 py-3.5 hover:bg-muted/30 transition-colors">
                  <Clock className="h-4 w-4 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{it.q}</div>
                    <div className="text-[11px] text-muted-foreground inline-flex items-center gap-2 mt-0.5">
                      <span className="inline-flex items-center gap-1"><Database className="h-3 w-3" /> {it.conn}</span>
                      <span>·</span>
                      <span className="font-mono">{it.rows} rows · {it.ms} ms</span>
                      <span>·</span>
                      <span>{it.queries} supporting {it.queries === 1 ? "query" : "queries"}</span>
                    </div>
                  </div>
                  <span className="hidden sm:inline text-xs text-muted-foreground">{it.time}</span>
                  <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                </Link>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
