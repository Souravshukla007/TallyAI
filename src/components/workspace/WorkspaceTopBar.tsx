"use client";

import { Bell, Search, ChevronDown, Database, Check, LogOut, User, Menu, Settings, AlertTriangle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useDemo } from "@/hooks/useDemo";
import { useAuth } from "@/hooks/useAuth";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import type { AttentionItem } from "@/types/tallyai";

const connections = [
  { id: "prod", name: "production_db" },
  { id: "staging", name: "staging_db" },
  { id: "analytics", name: "analytics_warehouse" },
];

const SEEN_KEY = "tallyai-seen-notifs";

function readSeen(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(SEEN_KEY) || "[]") as string[];
  } catch {
    return [];
  }
}

interface Props {
  activeConnectionId: string;
  onConnectionChange: (id: string) => void;
  onMenuClick?: () => void;
}

export function WorkspaceTopBar({ activeConnectionId, onConnectionChange, onMenuClick }: Props) {
  const router = useRouter();
  const { exitDemoMode } = useDemo();
  const { user, signOut } = useAuth();
  const [connOpen, setConnOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [seen, setSeen] = useState<string[]>([]);
  const searchRef = useRef<HTMLInputElement>(null);
  const active = connections.find((c) => c.id === activeConnectionId) ?? connections[0];

  const { data: dashboard } = useApi(() => api.getDashboard(activeConnectionId), [activeConnectionId]);
  const notifications: AttentionItem[] = dashboard?.attention ?? [];
  const unreadCount = notifications.filter((n) => !seen.includes(n.title)).length;

  // Identity shown in the top bar: the authenticated user, or the demo persona.
  const email = user?.email ?? "demo@tallyai.io";
  const displayName =
    (user?.user_metadata?.full_name as string | undefined) ??
    (user ? email.split("@")[0] : "Demo Admin");
  const initials =
    displayName
      .split(/[\s._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "U";

  useEffect(() => {
    setSeen(readSeen());
  }, []);

  // ⌘K / Ctrl+K focuses the search input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleAsk = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const q = query.trim();
    router.push(q ? `/workspace/ask?q=${encodeURIComponent(q)}` : "/workspace/ask");
    setQuery("");
  };

  const openNotifications = () => {
    const next = !notifOpen;
    setNotifOpen(next);
    if (next && notifications.length > 0) {
      const titles = notifications.map((n) => n.title);
      setSeen(titles);
      try {
        window.localStorage.setItem(SEEN_KEY, JSON.stringify(titles));
      } catch {
        /* ignore */
      }
    }
  };

  const handleSignOut = async () => {
    await signOut();
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
            ref={searchRef}
            name="q"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
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
      <div className="relative">
        <button
          type="button"
          onClick={openNotifications}
          className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg hover:bg-muted transition-colors"
          aria-label="Notifications"
        >
          <Bell className="h-4 w-4 text-foreground" />
          {unreadCount > 0 && (
            <span className="absolute top-1.5 right-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-semibold text-primary-foreground">
              {unreadCount}
            </span>
          )}
        </button>
        {notifOpen && (
          <div className="absolute right-0 top-full mt-2 w-80 rounded-lg border border-border bg-card shadow-lg overflow-hidden z-50">
            <div className="flex items-center justify-between px-3 py-2 border-b border-border">
              <span className="text-xs font-semibold">Notifications</span>
              <span className="text-[10px] text-muted-foreground">{notifications.length} items</span>
            </div>
            <div className="max-h-80 overflow-y-auto">
              {notifications.length === 0 ? (
                <div className="px-3 py-6 text-center text-sm text-muted-foreground">You&apos;re all caught up.</div>
              ) : (
                notifications.map((n) => (
                  <div key={n.title} className="flex items-start gap-2.5 px-3 py-2.5 border-b border-border last:border-0">
                    <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-secondary/15 text-secondary-foreground">
                      <AlertTriangle className="h-3 w-3" />
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm leading-snug text-foreground">{n.title}</div>
                      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                        <span className="rounded-full bg-muted px-1.5 py-0.5 font-medium">{n.tag}</span>
                        {n.time}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
            <button
              type="button"
              onClick={() => { setNotifOpen(false); router.push("/workspace/dashboard"); }}
              className="block w-full border-t border-border px-3 py-2 text-center text-xs font-medium text-primary hover:bg-muted transition-colors"
            >
              View all on dashboard
            </button>
          </div>
        )}
      </div>

      {/* User menu */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setUserOpen((o) => !o)}
          className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-muted transition-colors"
        >
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-semibold">
            {initials}
          </span>
          <span className="hidden sm:inline text-sm font-medium">{displayName}</span>
          <ChevronDown className="hidden sm:inline h-3.5 w-3.5 text-muted-foreground" />
        </button>
        {userOpen && (
          <div className="absolute right-0 top-full mt-2 w-52 rounded-lg border border-border bg-card shadow-lg overflow-hidden z-50">
            <div className="px-3 py-2 border-b border-border">
              <div className="text-sm font-semibold">{displayName}</div>
              <div className="text-xs text-muted-foreground">{email}</div>
            </div>
            <button
              type="button"
              onClick={() => { setUserOpen(false); router.push("/workspace/profile"); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted transition-colors"
            >
              <User className="h-3.5 w-3.5" />
              Profile
            </button>
            <button
              type="button"
              onClick={() => { setUserOpen(false); router.push("/workspace/settings"); }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted transition-colors"
            >
              <Settings className="h-3.5 w-3.5" />
              Settings
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
