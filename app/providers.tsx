"use client";

import type { ReactNode } from "react";
import { DemoProvider } from "@/contexts/DemoContext";

export function Providers({ children }: { children: ReactNode }) {
  return <DemoProvider>{children}</DemoProvider>;
}
