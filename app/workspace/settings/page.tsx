"use client";

import Link from "next/link";
import { Monitor, Moon, Sun, Eye, Zap, Database, User as UserIcon, RotateCcw, Check } from "lucide-react";
import { usePreferences, type ThemePref } from "@/hooks/usePreferences";
import { useAuth } from "@/hooks/useAuth";

const connections = [
  { id: "prod", name: "production_db" },
  { id: "staging", name: "staging_db" },
  { id: "analytics", name: "analytics_warehouse" },
];

const themeOptions: { value: ThemePref; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
        checked ? "bg-primary" : "bg-muted-foreground/30"
      }`}
    >
      <span
        className={`inline-block h-5 w-5 transform rounded-full bg-card shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

function Row({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-4">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="text-xs text-muted-foreground">{desc}</div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export default function SettingsPage() {
  const {
    theme,
    previewByDefault,
    defaultConnectionId,
    setTheme,
    setPreviewByDefault,
    setDefaultConnectionId,
    reset,
  } = usePreferences();
  const { user } = useAuth();

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="mt-1 text-sm text-muted-foreground">Preferences are saved to this browser.</p>
        </div>
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted transition-colors"
        >
          <RotateCcw className="h-3.5 w-3.5" /> Reset
        </button>
      </div>

      {/* Appearance */}
      <section className="mt-8 rounded-2xl border border-border bg-card p-5">
        <h2 className="text-sm font-semibold">Appearance</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">Choose how TallyAI looks.</p>
        <div className="mt-4 grid grid-cols-3 gap-2">
          {themeOptions.map((opt) => {
            const active = theme === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => setTheme(opt.value)}
                className={`flex flex-col items-center gap-2 rounded-xl border p-4 text-sm transition-colors ${
                  active ? "border-primary bg-primary/5 text-primary" : "border-border hover:bg-muted/50"
                }`}
              >
                <opt.icon className="h-5 w-5" />
                {opt.label}
                {active && <Check className="h-3.5 w-3.5" />}
              </button>
            );
          })}
        </div>
      </section>

      {/* Query preferences */}
      <section className="mt-6 rounded-2xl border border-border bg-card p-5">
        <h2 className="text-sm font-semibold">Querying</h2>
        <div className="mt-1 divide-y divide-border">
          <Row
            title="Preview before run"
            desc="Show generated SQL and require confirmation before executing."
          >
            <div className="flex items-center gap-2">
              {previewByDefault ? <Eye className="h-4 w-4 text-primary" /> : <Zap className="h-4 w-4 text-muted-foreground" />}
              <Toggle checked={previewByDefault} onChange={setPreviewByDefault} />
            </div>
          </Row>
          <Row title="Default connection" desc="The database selected when you open the workspace.">
            <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1.5">
              <Database className="h-3.5 w-3.5 text-muted-foreground" />
              <select
                value={defaultConnectionId}
                onChange={(e) => setDefaultConnectionId(e.target.value)}
                className="bg-transparent text-sm focus:outline-none"
              >
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          </Row>
        </div>
      </section>

      {/* Account */}
      <section className="mt-6 rounded-2xl border border-border bg-card p-5">
        <h2 className="text-sm font-semibold">Account</h2>
        <div className="mt-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 text-primary">
              <UserIcon className="h-4 w-4" />
            </span>
            <div>
              <div className="text-sm font-medium">{user ? user.email : "Demo session"}</div>
              <div className="text-xs text-muted-foreground">
                {user ? "Signed in" : "Exploring sample data — log in to manage your account."}
              </div>
            </div>
          </div>
          <Link
            href="/workspace/profile"
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm hover:bg-muted transition-colors"
          >
            Manage profile
          </Link>
        </div>
      </section>
    </div>
  );
}
