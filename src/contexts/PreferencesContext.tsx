"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemePref = "light" | "dark" | "system";

export interface Preferences {
  theme: ThemePref;
  /** Default for the Ask page "preview before run" toggle. */
  previewByDefault: boolean;
  /** Default workspace connection id. */
  defaultConnectionId: string;
}

export interface PreferencesContextValue extends Preferences {
  setTheme: (t: ThemePref) => void;
  setPreviewByDefault: (v: boolean) => void;
  setDefaultConnectionId: (id: string) => void;
  reset: () => void;
}

const STORAGE_KEY = "tallyai-prefs";

const DEFAULTS: Preferences = {
  theme: "system",
  previewByDefault: true,
  defaultConnectionId: "prod",
};

export const PreferencesContext = createContext<PreferencesContextValue | null>(null);

function readStored(): Preferences {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Preferences>) };
  } catch {
    return DEFAULTS;
  }
}

function applyTheme(theme: ThemePref) {
  if (typeof document === "undefined") return;
  const prefersDark =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Preferences>(DEFAULTS);

  // Hydrate from storage on mount.
  useEffect(() => {
    setPrefs(readStored());
  }, []);

  // Persist + apply theme whenever prefs change.
  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      /* ignore quota / private-mode errors */
    }
    applyTheme(prefs.theme);
  }, [prefs]);

  // React to OS theme changes while in "system" mode.
  useEffect(() => {
    if (prefs.theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyTheme("system");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [prefs.theme]);

  const setTheme = useCallback((theme: ThemePref) => setPrefs((p) => ({ ...p, theme })), []);
  const setPreviewByDefault = useCallback(
    (previewByDefault: boolean) => setPrefs((p) => ({ ...p, previewByDefault })),
    [],
  );
  const setDefaultConnectionId = useCallback(
    (defaultConnectionId: string) => setPrefs((p) => ({ ...p, defaultConnectionId })),
    [],
  );
  const reset = useCallback(() => setPrefs(DEFAULTS), []);

  const value = useMemo<PreferencesContextValue>(
    () => ({ ...prefs, setTheme, setPreviewByDefault, setDefaultConnectionId, reset }),
    [prefs, setTheme, setPreviewByDefault, setDefaultConnectionId, reset],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}
