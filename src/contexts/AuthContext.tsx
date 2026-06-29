"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Session, User } from "@supabase/supabase-js";
import { getSupabase, isSupabaseConfigured } from "@/lib/supabase/client";

export interface AuthResult {
  ok: boolean;
  error?: string;
}

export interface AuthContextValue {
  user: User | null;
  session: Session | null;
  /** True while the initial session is being restored/validated. */
  loading: boolean;
  /** Whether Supabase env vars are present. */
  configured: boolean;
  signIn: (email: string, password: string) => Promise<AuthResult>;
  signUp: (email: string, password: string) => Promise<AuthResult>;
  signOut: () => Promise<void>;
  /** Update the user's display name (stored in user metadata). */
  updateProfile: (fullName: string) => Promise<AuthResult>;
  /** Change the authenticated user's password. */
  updatePassword: (newPassword: string) => Promise<AuthResult>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

const NOT_CONFIGURED: AuthResult = {
  ok: false,
  error:
    "Authentication is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.",
};

/** Map Supabase errors to user-safe, non-enumerating messages. */
function friendlyError(message: string | undefined): string {
  if (!message) return "Something went wrong. Please try again.";
  const m = message.toLowerCase();
  if (m.includes("invalid login") || m.includes("invalid credentials")) {
    return "Incorrect email or password.";
  }
  if (m.includes("already registered") || m.includes("already been registered") || m.includes("user already")) {
    return "That email is already in use.";
  }
  if (m.includes("rate limit") || m.includes("too many")) {
    return "Too many attempts. Please wait a moment and try again.";
  }
  if (m.includes("email") && m.includes("confirm")) {
    return "Check your inbox to confirm your email before logging in.";
  }
  return message;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) {
      setLoading(false);
      return;
    }

    let active = true;

    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (!active) return;
        setSession(data.session);
        setUser(data.session?.user ?? null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    const { data: sub } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setUser(nextSession?.user ?? null);
    });

    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string): Promise<AuthResult> => {
    const supabase = getSupabase();
    if (!supabase) return NOT_CONFIGURED;
    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (error) return { ok: false, error: friendlyError(error.message) };
    return { ok: true };
  }, []);

  const signUp = useCallback(async (email: string, password: string): Promise<AuthResult> => {
    const supabase = getSupabase();
    if (!supabase) return NOT_CONFIGURED;
    const { error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
    });
    if (error) return { ok: false, error: friendlyError(error.message) };
    return { ok: true };
  }, []);

  const signOut = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    await supabase.auth.signOut();
    setSession(null);
    setUser(null);
  }, []);

  const updateProfile = useCallback(async (fullName: string): Promise<AuthResult> => {
    const supabase = getSupabase();
    if (!supabase) return NOT_CONFIGURED;
    const { data, error } = await supabase.auth.updateUser({
      data: { full_name: fullName.trim() },
    });
    if (error) return { ok: false, error: friendlyError(error.message) };
    if (data.user) setUser(data.user);
    return { ok: true };
  }, []);

  const updatePassword = useCallback(async (newPassword: string): Promise<AuthResult> => {
    const supabase = getSupabase();
    if (!supabase) return NOT_CONFIGURED;
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) return { ok: false, error: friendlyError(error.message) };
    return { ok: true };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      session,
      loading,
      configured: isSupabaseConfigured,
      signIn,
      signUp,
      signOut,
      updateProfile,
      updatePassword,
    }),
    [user, session, loading, signIn, signUp, signOut, updateProfile, updatePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
