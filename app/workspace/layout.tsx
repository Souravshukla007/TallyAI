"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { WorkspaceSidebar } from "@/components/workspace/WorkspaceSidebar";
import { WorkspaceTopBar } from "@/components/workspace/WorkspaceTopBar";
import { useDemo } from "@/hooks/useDemo";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { isDemo, enterDemoMode } = useDemo();
  const [conn, setConn] = useState("prod");
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    if (!isDemo) enterDemoMode();
  }, [isDemo, enterDemoMode]);

  // Close mobile drawer on navigation
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

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
