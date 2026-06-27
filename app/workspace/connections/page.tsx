"use client";

import { Database, Plus, ShieldCheck, X, Lock, AlertTriangle, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { NewConnectionInput, PrivilegeTestResult } from "@/types/tallyai";

const emptyForm: NewConnectionInput = { host: "", port: "", database: "", username: "", password: "" };

export default function ConnectionsPage() {
  const { data: connections, loading, error } = useApi(() => api.listConnections(), []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<NewConnectionInput>(emptyForm);
  const [test, setTest] = useState<PrivilegeTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const runTest = async () => {
    setTesting(true);
    const result = await api.testConnection(form);
    setTest(result);
    setTesting(false);
  };

  const fields: Array<{ key: keyof NewConnectionInput; label: string; placeholder: string; type?: string }> = [
    { key: "host", label: "Host", placeholder: "db.example.com" },
    { key: "port", label: "Port", placeholder: "5432" },
    { key: "database", label: "Database", placeholder: "production" },
    { key: "username", label: "Username", placeholder: "tallyai_reader" },
    { key: "password", label: "Password", placeholder: "••••••••", type: "password" },
  ];

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Connections</h1>
          <p className="mt-1 text-sm text-muted-foreground">Databases TallyAI can query, read-only.</p>
        </div>
        <button
          onClick={() => { setOpen(true); setTest(null); setForm(emptyForm); }}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110 transition-all"
        >
          <Plus className="h-3.5 w-3.5" /> Add connection
        </button>
      </div>

      <div className="mt-8 grid grid-cols-1 gap-3 md:grid-cols-2">
        {loading ? (
          <div className="text-sm text-muted-foreground">Loading connections…</div>
        ) : error ? (
          <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-5 text-sm text-destructive md:col-span-2">
            Couldn&apos;t load connections: {error}
          </div>
        ) : !connections || connections.length === 0 ? (
          <div className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground md:col-span-2">
            No connections yet. Click &quot;Add connection&quot; to register a read-only database.
          </div>
        ) : (
          connections.map((c) => (
              <div key={c.id} className="rounded-xl border border-border bg-card p-5">
                <div className="flex items-start justify-between">
                  <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Database className="h-4 w-4" />
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                      <span className="h-1.5 w-1.5 rounded-full bg-primary" /> {c.status}
                    </span>
                    {c.readOnly && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                        <Lock className="h-2.5 w-2.5" /> Read-only
                      </span>
                    )}
                  </div>
                </div>
                <h3 className="mt-4 text-base font-semibold">{c.name}</h3>
                <p className="mt-0.5 text-xs text-muted-foreground">{c.engine}</p>
                <p className="mt-0.5 font-mono text-xs text-muted-foreground">{c.host}</p>
              </div>
            ))
        )}
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-foreground/30">
          <div className="w-full max-w-md rounded-2xl border border-border bg-background shadow-2xl">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h2 className="text-sm font-semibold">Add connection</h2>
              <button onClick={() => setOpen(false)} className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-muted">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="p-5 space-y-3">
              {fields.map((f) => (
                <div key={f.key}>
                  <label className="text-xs font-semibold text-foreground">{f.label}</label>
                  <input
                    type={f.type ?? "text"}
                    placeholder={f.placeholder}
                    value={form[f.key]}
                    onChange={(e) => { setForm((prev) => ({ ...prev, [f.key]: e.target.value })); setTest(null); }}
                    className="mt-1 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:border-primary"
                  />
                </div>
              ))}

              {test?.ok && (
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-primary mt-0.5 shrink-0" />
                  <div>
                    <div className="font-semibold text-primary">Read-only privileges confirmed</div>
                    <div className="text-xs text-muted-foreground">Granted: {test.privileges.join(", ")}</div>
                  </div>
                </div>
              )}
              {test && !test.ok && (
                <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
                  <div>
                    <div className="font-semibold text-destructive">Connection rejected</div>
                    <div className="text-xs text-muted-foreground">
                      Disallowed privileges detected: {(test.disallowed ?? []).join(", ")}. Create a read-only role and retry.
                    </div>
                  </div>
                </div>
              )}

              <div className="text-[11px] text-muted-foreground inline-flex items-center gap-1">
                <ShieldCheck className="h-3 w-3" /> Credentials are encrypted in transit and never displayed again.
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
              <button onClick={runTest} disabled={testing} className="rounded-lg border border-border bg-card px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50">
                {testing ? "Testing…" : "Test connection"}
              </button>
              <button
                disabled={!test?.ok}
                className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-40"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
