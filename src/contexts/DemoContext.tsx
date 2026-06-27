"use client";

import { createContext, useCallback, useMemo, useState, type ReactNode } from "react";

export interface DemoContextValue {
  isDemo: boolean;
  enterDemoMode: () => void;
  exitDemoMode: () => void;
}

export const DemoContext = createContext<DemoContextValue | null>(null);

export function DemoProvider({ children }: { children: ReactNode }) {
  const [isDemo, setIsDemo] = useState(false);

  const enterDemoMode = useCallback(() => setIsDemo(true), []);
  const exitDemoMode = useCallback(() => setIsDemo(false), []);

  const value = useMemo<DemoContextValue>(
    () => ({ isDemo, enterDemoMode, exitDemoMode }),
    [isDemo, enterDemoMode, exitDemoMode],
  );

  return <DemoContext.Provider value={value}>{children}</DemoContext.Provider>;
}
