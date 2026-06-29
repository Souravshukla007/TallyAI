"use client";

import { useState, useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { WorkspaceSidebar } from "@/components/workspace/WorkspaceSidebar";
import { WorkspaceTopBar } from "@/components/workspace/WorkspaceTopBar";
import { useDemo } from "@/hooks/useDemo";
import { useAuth } from "@/hooks/useAuth";
import { usePreferences } from "@/hooks/usePreferences";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { isDemo } = useDemo();
  const { user, loading } = useAuth();
  const { defaultConnectionId } = usePreferences();
  const router = useRouter();
  const pathname = usePathname();
  const [conn, setConn] = useState("prod");
  const [mobileOpen, setMobileOpen] = useState(false);
  const connInit = useRef(false);

  const allowed = Boolean(user) || isDemo;

  // Adopt the saved default connection once preferences hydrate.
  useEffect(() => {
    if (connInit.current) return;
    connInit.current = true;
    if (defaultConnectionId) setConn(defaultConnectionId);
  }, [defaultConnectionId]);

  // Gate access: authenticated session OR active demo mode.
  useEffect(() => {
    if (loading) return;
    if (!allowed) {
      const redirect = encodeURIComponent(pathname || "/workspace/ask");
      router.replace(`/auth?redirect=${redirect}`);
    }
  }, [loading, allowed, pathname, router]);

  // Close mobile drawer on navigation
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // While resolving auth, or before redirect kicks in, show a neutral splash.
  if (loading || !allowed) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <div className="hidden md:block">
        <WorkspaceSidebar activeConnectionId={conn} onConnectionChange={setConn} />
      </div>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-foreground/30" onClick={() => setMobileOpen(false)} />
          <div className="absolute inset-y-0 left-0 shadow-2xl">
            <WorkspaceSidebar activeConnectionId={conn} onConnectionChange={setConn} />
          </div>
        </div>
      )}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Demo indicator — visible only while in demo mode and not authenticated */}
        {isDemo && !user && (
          <div className="flex items-center justify-center gap-2 bg-secondary/15 px-4 py-1.5 text-center text-xs font-medium text-secondary-foreground">
            <span className="inline-flex h-1.5 w-1.5 rounded-full bg-secondary" />
            Demo mode — exploring sample data.{" "}
            <button
              type="button"
              onClick={() => router.push("/auth")}
              className="font-semibold text-primary hover:underline"
            >
              Log in for your data
            </button>
          </div>
        )}
        <WorkspaceTopBar
          activeConnectionId={conn}
          onConnectionChange={setConn}
          onMenuClick={() => setMobileOpen(true)}
        />
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
