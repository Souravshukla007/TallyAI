"use client";

import { Layers, Plus, X, History as HistoryIcon } from "lucide-react";
import { useState, useEffect } from "react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { NewMetricInput } from "@/lib/api";
import type { MetricDefinition } from "@/types/tallyai";

type DrawerMode =
  | null
  | { mode: "edit" | "history"; metric: MetricDefinition }
  | { mode: "create" };

const emptyForm: NewMetricInput = { name: "", formula: "", condition: "", grain: "", description: "" };

export default function MetricsPage() {
  const [reloadKey, setReloadKey] = useState(0);
  const { data: metrics, loading } = useApi(() => api.listMetrics("prod"), [reloadKey]);
  const [drawer, setDrawer] = useState<DrawerMode>(null);
  const [form, setForm] = useState<NewMetricInput>(emptyForm);
  const [saving, setSaving] = useState(false);

  // Seed the edit form whenever the drawer opens in edit/create mode.
  useEffect(() => {
    if (drawer?.mode === "edit") {
      const m = drawer.metric;
      setForm({
        name: m.name,
        formula: m.formula,
        condition: m.condition ?? "",
        grain: m.grain,
        description: m.description,
      });
    } else if (drawer?.mode === "create") {
      setForm(emptyForm);
    }
  }, [drawer]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.saveMetric("prod", form);
      setDrawer(null);
      setReloadKey((k) => k + 1);
    } finally {
      setSaving(false);
    }
  };

  if (loading || !metrics) {
    return <div className="mx-auto max-w-6xl px-6 py-8 text-sm text-muted-foreground">Loading metrics…</div>;
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Metrics</h1>
          <p className="mt-1 text-sm text-muted-foreground">Semantic business layer. Saving creates a new version, never an in-place edit.</p>
        </div>
        <button
          onClick={() => setDrawer({ mode: "create" })}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110 transition-all"
        >
          <Plus className="h-3.5 w-3.5" /> New metric
        </button>
      </div>

      <div className="mt-8 rounded-xl border border-border bg-card overflow-hidden">
        <div className="grid grid-cols-12 px-5 py-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground border-b border-border">
          <div className="col-span-3">Name</div>
          <div className="col-span-4">Formula</div>
          <div className="col-span-2">Condition</div>
          <div className="col-span-1">Grain</div>
          <div className="col-span-1">Version</div>
          <div className="col-span-1" />
        </div>
        {metrics.map((m) => (
          <div key={m.name} className="grid grid-cols-12 px-5 py-3 items-center border-b border-border last:border-0 hover:bg-muted/30 transition-colors text-sm">
            <div className="col-span-3 flex items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-primary" />
              <span className="font-mono font-semibold">{m.name}</span>
            </div>
            <div className="col-span-4 font-mono text-xs text-muted-foreground truncate">{m.formula}</div>
            <div className="col-span-2 font-mono text-xs text-muted-foreground truncate">{m.condition ?? "—"}</div>
            <div className="col-span-1 text-xs">{m.grain}</div>
            <div className="col-span-1 font-mono text-xs">v{m.version}</div>
            <div className="col-span-1 flex items-center gap-1 justify-end">
              <button onClick={() => setDrawer({ mode: "history", metric: m })} className="rounded-md p-1.5 hover:bg-muted" title="Versions">
                <HistoryIcon className="h-3.5 w-3.5 text-muted-foreground" />
              </button>
              <button onClick={() => setDrawer({ mode: "edit", metric: m })} className="rounded-md px-2 py-1 text-xs text-primary hover:bg-muted">
                Edit
              </button>
            </div>
          </div>
        ))}
      </div>

      {drawer && (
        <div className="fixed inset-0 z-50 flex">
          <div className="flex-1 bg-foreground/30" onClick={() => setDrawer(null)} />
          <aside className="w-full max-w-md bg-background border-l border-border shadow-2xl flex flex-col">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h2 className="text-sm font-semibold">
                {drawer.mode === "create"
                  ? "New metric"
                  : drawer.mode === "edit"
                    ? `Edit ${drawer.metric.name}`
                    : `${drawer.metric.name} versions`}
              </h2>
              <button onClick={() => setDrawer(null)} className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              {drawer.mode === "edit" || drawer.mode === "create" ? (
                <div className="space-y-3">
                  {([
                    { key: "name", label: "Name" },
                    { key: "description", label: "Description" },
                    { key: "formula", label: "Formula", mono: true },
                    { key: "condition", label: "Condition", mono: true },
                    { key: "grain", label: "Grain" },
                  ] as const).map((f) => (
                    <div key={f.key}>
                      <label className="text-xs font-semibold">{f.label}</label>
                      <input
                        value={form[f.key] ?? ""}
                        onChange={(e) => setForm((prev) => ({ ...prev, [f.key]: e.target.value }))}
                        className={`mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:border-primary ${"mono" in f && f.mono ? "font-mono text-xs" : ""}`}
                      />
                    </div>
                  ))}
                  <div className="text-[11px] text-muted-foreground">
                    {drawer.mode === "create"
                      ? "Saving creates the first version of this metric."
                      : `Saving will create version ${drawer.metric.version + 1}. Older versions stay queryable.`}
                  </div>
                  <div className="flex justify-end gap-2 pt-2">
                    <button onClick={() => setDrawer(null)} className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-muted">
                      Cancel
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={saving || !form.name.trim() || !form.formula.trim()}
                      className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground hover:brightness-110 disabled:opacity-50"
                    >
                      {saving
                        ? "Saving…"
                        : drawer.mode === "create"
                          ? "Create metric"
                          : `Save v${drawer.metric.version + 1}`}
                    </button>
                  </div>
                </div>
              ) : (
                <ol className="space-y-3">
                  {drawer.metric.history.map((v) => (
                    <li key={v.version} className="rounded-lg border border-border bg-card p-3">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-semibold">v{v.version}</span>
                        <span className="text-[11px] text-muted-foreground">{v.createdAt}</span>
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-muted-foreground">{v.formula}</div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
