"use client";

import { Bell, Search, ChevronDown, Database, Check, LogOut, User, Menu } from "lucide-react";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useDemo } from "@/hooks/useDemo";

const connections = [
  { id: "prod", name: "production_db" },
  { id: "staging", name: "staging_db" },
  { id: "analytics", name: "analytics_warehouse" },
];

interface Props {
  activeConnectionId: string;
  onConnectionChange: (id: string) => void;
  onMenuClick?: () => void;
}

export function WorkspaceTopBar({ activeConnectionId, onConnectionChange, onMenuClick }: Props) {
  const router = useRouter();
  const { exitDemoMode } = useDemo();
  const [connOpen, setConnOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const active = connections.find((c) => c.id === activeConnectionId) ?? connections[0];

  const handleAsk = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    router.push("/workspace/ask");
  };

  const handleSignOut = () => {
    exitDemoMode?.();
    router.push("/");
  };

  return (
    <header className="flex h-14 items-center gap-3 border-b border-border bg-background px-4">
      {onMenuClick && (
        <button
          type="button"
          onClick={onMenuClick}
          className="md:hidden inline-flex h-9 w-9 items-center justify-center rounded-lg hover:bg-muted transition-colors"
          aria-label="Open navigation"
        >
          <Menu className="h-4 w-4" />
        </button>
      )}
      {/* Ask input */}
      <form onSubmit={handleAsk} className="flex-1 min-w-0 max-w-2xl">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-1.5 focus-within:bg-card focus-within:border-primary/40 transition-colors">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            name="q"
            type="text"
            placeholder="Ask a question…"
            className="flex-1 min-w-0 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          <kbd className="hidden sm:inline-block rounded border border-border bg-card px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
            ⌘K
          </kbd>
        </div>
      </form>


      {/* Connection switcher */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setConnOpen((o) => !o)}
          className="hidden md:inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm hover:bg-muted transition-colors"
        >
          <Database className="h-3.5 w-3.5 text-primary" />
          <span className="font-medium">{active.name}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </button>
        {connOpen && (
          <div className="absolute right-0 top-full mt-2 w-56 rounded-lg border border-border bg-card shadow-lg overflow-hidden z-50">
            <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground border-b border-border">
              Switch connection
            </div>
            {connections.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  onConnectionChange(c.id);
                  setConnOpen(false);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted transition-colors"
              >
                <Database className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="flex-1">{c.name}</span>
                {c.id === active.id && <Check className="h-3.5 w-3.5 text-primary" />}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Notifications */}
      <button
        type="button"
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg hover:bg-muted transition-colors"
        aria-label="Notifications"
      >
        <Bell className="h-4 w-4 text-foreground" />
        <span className="absolute top-2 right-2 h-1.5 w-1.5 rounded-full bg-primary" />
      </button>

      {/* User menu */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setUserOpen((o) => !o)}
          className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-muted transition-colors"
        >
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-semibold">
            DA
          </span>
          <span className="hidden sm:inline text-sm font-medium">Demo Admin</span>
          <ChevronDown className="hidden sm:inline h-3.5 w-3.5 text-muted-foreground" />
        </button>
        {userOpen && (
          <div className="absolute right-0 top-full mt-2 w-52 rounded-lg border border-border bg-card shadow-lg overflow-hidden z-50">
            <div className="px-3 py-2 border-b border-border">
              <div className="text-sm font-semibold">Demo Admin</div>
              <div className="text-xs text-muted-foreground">demo@tallyai.io</div>
            </div>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted transition-colors"
            >
              <User className="h-3.5 w-3.5" />
              Profile
            </button>
            <button
              type="button"
              onClick={handleSignOut}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted transition-colors border-t border-border"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
