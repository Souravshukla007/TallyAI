"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageSquare,
  LayoutDashboard,
  Clock,
  Database,
  Table as TableIcon,
  Layers,
  Lightbulb,
  Bookmark,
  Activity,
  Settings,
  ChevronsUpDown,
  Check,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useState } from "react";

type NavItem = { label: string; to: string; icon: React.ComponentType<{ className?: string }> };
type NavGroup = { label: string; items: NavItem[] };

const groups: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { label: "Ask", to: "/workspace/ask", icon: MessageSquare },
      { label: "Dashboard", to: "/workspace/dashboard", icon: LayoutDashboard },
      { label: "History", to: "/workspace/history", icon: Clock },
    ],
  },
  {
    label: "Data",
    items: [
      { label: "Connections", to: "/workspace/connections", icon: Database },
      { label: "Schema", to: "/workspace/schema", icon: TableIcon },
      { label: "Metrics", to: "/workspace/metrics", icon: Layers },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { label: "Insights & reports", to: "/workspace/insights", icon: Lightbulb },
      { label: "Saved queries", to: "/workspace/saved", icon: Bookmark },
    ],
  },
  {
    label: "Admin",
    items: [
      { label: "Eval & observability", to: "/workspace/eval", icon: Activity },
      { label: "Settings", to: "/workspace/settings", icon: Settings },
    ],
  },
];

const connections = [
  { id: "prod", name: "production_db", host: "db.acme.com" },
  { id: "staging", name: "staging_db", host: "staging.acme.com" },
  { id: "analytics", name: "analytics_warehouse", host: "warehouse.acme.com" },
];

interface Props {
  activeConnectionId: string;
  onConnectionChange: (id: string) => void;
}

export function WorkspaceSidebar({ activeConnectionId, onConnectionChange }: Props) {
  const pathname = usePathname();
  const [pickerOpen, setPickerOpen] = useState(false);
  const active = connections.find((c) => c.id === activeConnectionId) ?? connections[0];

  return (
    <nav className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-card">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2 px-4 border-b border-border">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Database className="h-4 w-4" />
        </span>
        <span className="text-base font-semibold tracking-tight">TallyAI</span>
      </div>

      {/* Groups */}
      <div className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
        {groups.map((g) => (
          <div key={g.label}>
            <div className="px-2 mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              {g.label}
            </div>
            <div className="space-y-0.5">
              {g.items.map((item) => {
                const isActive = pathname === item.to;
                return (
                  <Link
                    key={item.to}
                    href={item.to}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                      isActive
                        ? "bg-primary/10 text-primary font-medium"
                        : "text-foreground/70 hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <item.icon className="h-4 w-4 shrink-0" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Connection switcher */}
      <div className="border-t border-border p-3 relative">
        <button
          type="button"
          onClick={() => setPickerOpen((o) => !o)}
          className="flex w-full items-center gap-2.5 rounded-lg border border-border bg-background px-3 py-2 text-left text-sm hover:bg-muted transition-colors"
        >
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Database className="h-3.5 w-3.5" />
          </span>
          <span className="flex-1 min-w-0">
            <span className="block truncate text-xs font-semibold text-foreground">{active.name}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{active.host}</span>
          </span>
          <ChevronsUpDown className="h-3.5 w-3.5 text-muted-foreground" />
        </button>

        {pickerOpen && (
          <div className="absolute bottom-full left-3 right-3 mb-2 rounded-lg border border-border bg-card shadow-lg overflow-hidden">
            <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground border-b border-border">
              Connections
            </div>
            {connections.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  onConnectionChange(c.id);
                  setPickerOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted transition-colors"
              >
                <Database className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="flex-1 min-w-0 truncate">{c.name}</span>
                {c.id === active.id && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
            ))}
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-primary hover:bg-muted transition-colors border-t border-border"
            >
              <Plus className="h-3.5 w-3.5" />
              Add connection
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
