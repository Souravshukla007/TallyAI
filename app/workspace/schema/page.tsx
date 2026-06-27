"use client";

import { Table as TableIcon, RefreshCw, ChevronRight, Key, Link2 } from "lucide-react";
import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import type { CachedSchema } from "@/types/tallyai";

export default function SchemaPage() {
  const [schema, setSchema] = useState<CachedSchema | null>(null);
  const [active, setActive] = useState<string>("");
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.getSchema("prod").then((s) => {
      if (cancelled) return;
      setSchema(s);
      setActive(s.tables[0]?.name ?? "");
    });
    return () => { cancelled = true; };
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    const s = await api.refreshSchema("prod");
    setSchema(s);
    setRefreshing(false);
  };

  if (!schema) {
    return <div className="mx-auto max-w-6xl px-6 py-8 text-sm text-muted-foreground">Loading schema…</div>;
  }

  const activeTable = schema.tables.find((t) => t.name === active) ?? schema.tables[0];

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Schema</h1>
          <p className="mt-1 text-sm text-muted-foreground">production_db · last introspected {schema.lastIntrospected}</p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} /> Refresh schema
        </button>
      </div>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
        <nav className="rounded-xl border border-border bg-card p-2 max-h-[600px] overflow-y-auto">
          {schema.tables.map((t) => (
            <button
              key={t.name}
              onClick={() => setActive(t.name)}
              className={`flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm transition-colors ${
                active === t.name ? "bg-primary/10 text-primary font-medium" : "text-foreground hover:bg-muted"
              }`}
            >
              <ChevronRight className={`h-3 w-3 transition-transform ${active === t.name ? "rotate-90" : ""}`} />
              <TableIcon className="h-3.5 w-3.5" />
              <span className="flex-1 text-left font-mono text-xs">{t.name}</span>
              <span className="text-[10px] text-muted-foreground">{t.rows}</span>
            </button>
          ))}
        </nav>

        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="border-b border-border px-5 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TableIcon className="h-4 w-4 text-primary" />
              <h2 className="font-mono text-sm font-semibold">{activeTable.name}</h2>
              <span className="text-xs text-muted-foreground">{activeTable.columns.length} columns · {activeTable.rows} rows</span>
            </div>
          </div>
          <ul className="divide-y divide-border">
            {activeTable.columns.map((c) => (
              <li key={c.name} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 px-5 py-2.5">
                <div className="flex items-center gap-2 font-mono text-sm">
                  {c.pk && <Key className="h-3 w-3 text-secondary-foreground" />}
                  {c.fk && <Link2 className="h-3 w-3 text-primary" />}
                  <span>{c.name}</span>
                </div>
                <span className="font-mono text-xs text-muted-foreground">{c.type}</span>
                {c.fk ? (
                  <span className="font-mono text-[11px] text-primary">→ {c.fk}</span>
                ) : c.pk ? (
                  <span className="text-[10px] text-muted-foreground uppercase tracking-widest">Primary</span>
                ) : (
                  <span />
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
