"use client";

import { Settings } from "lucide-react";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-sm text-muted-foreground">Configuration, preferences, and team management.</p>

      <div className="mt-10 rounded-2xl border border-dashed border-border p-12 text-center">
        <Settings className="mx-auto h-8 w-8 text-muted-foreground" />
        <h2 className="mt-3 text-base font-semibold">Coming soon</h2>
        <p className="mt-1 text-sm text-muted-foreground">RBAC, audit logs, team workspaces, and preferences are post-MVP.</p>
      </div>
    </div>
  );
}
