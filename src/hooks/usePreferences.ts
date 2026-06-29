import { useContext } from "react";
import { PreferencesContext, type PreferencesContextValue } from "@/contexts/PreferencesContext";

export type { ThemePref, Preferences } from "@/contexts/PreferencesContext";

/**
 * Convenience hook for PreferencesContext.
 * Throws if used outside <PreferencesProvider>.
 */
export function usePreferences(): PreferencesContextValue {
  const ctx = useContext(PreferencesContext);
  if (!ctx) {
    throw new Error("usePreferences must be used within a <PreferencesProvider>.");
  }
  return ctx;
}
