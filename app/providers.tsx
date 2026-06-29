"use client";

import type { ReactNode } from "react";
import { AuthProvider } from "@/contexts/AuthContext";
import { DemoProvider } from "@/contexts/DemoContext";
import { PreferencesProvider } from "@/contexts/PreferencesContext";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <PreferencesProvider>
        <DemoProvider>{children}</DemoProvider>
      </PreferencesProvider>
    </AuthProvider>
  );
}
