"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Database, ArrowRight, Loader2, AlertTriangle, Lock, Mail } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useDemo } from "@/hooks/useDemo";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PW_MIN = 8;
const PW_MAX = 128;

type Mode = "login" | "signup";

function AuthForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, loading, configured, signIn, signUp } = useAuth();
  const { exitDemoMode } = useDemo();

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailErr, setEmailErr] = useState<string | null>(null);
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const redirectTo = params.get("redirect") || "/workspace/ask";

  // Already authenticated → leave the auth page.
  useEffect(() => {
    if (!loading && user) {
      exitDemoMode();
      router.replace(redirectTo);
    }
  }, [loading, user, router, redirectTo, exitDemoMode]);

  const switchMode = (next: Mode) => {
    setMode(next);
    setPwErr(null);
    setFormErr(null);
    setNotice(null);
    setPassword(""); // keep email, clear password
  };

  const validate = () => {
    let ok = true;
    if (!email.trim()) {
      setEmailErr("Email is required.");
      ok = false;
    } else if (email.trim().length > 254 || !EMAIL_RE.test(email.trim())) {
      setEmailErr("Enter a valid email address.");
      ok = false;
    } else {
      setEmailErr(null);
    }

    if (!password) {
      setPwErr("Password is required.");
      ok = false;
    } else if (mode === "signup" && (password.length < PW_MIN || password.length > PW_MAX)) {
      setPwErr(`Password must be ${PW_MIN}–${PW_MAX} characters.`);
      ok = false;
    } else {
      setPwErr(null);
    }
    return ok;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormErr(null);
    setNotice(null);
    if (submitting) return;
    if (!validate()) return;

    setSubmitting(true);
    const fn = mode === "login" ? signIn : signUp;
    const result = await fn(email.trim(), password);
    setSubmitting(false);

    if (!result.ok) {
      setFormErr(result.error ?? "Something went wrong. Please try again.");
      setPassword(""); // retain email, clear password
      return;
    }

    if (mode === "signup") {
      // If email confirmation is enabled, there may be no active session yet.
      if (!user) {
        setNotice("Account created. If email confirmation is on, check your inbox, then log in.");
      }
    }
    // The redirect effect handles navigation once a session is established.
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      {/* Brand bar */}
      <header className="px-4 py-4 sm:px-6">
        <Link href="/" className="inline-flex items-center gap-2">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Database className="h-4 w-4" />
          </span>
          <span className="text-lg font-semibold tracking-tight">TallyAI</span>
        </Link>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="text-center">
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              {mode === "login" ? "Welcome back" : "Create your account"}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {mode === "login"
                ? "Log in to query your databases with TallyAI."
                : "Sign up to start asking your data anything."}
            </p>
          </div>

          {!configured && (
            <div className="mt-6 flex items-start gap-2 rounded-lg border border-secondary/40 bg-secondary/10 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-secondary-foreground" />
              <span className="text-muted-foreground">
                Auth isn&apos;t configured yet. Add <code className="font-mono text-xs">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
                <code className="font-mono text-xs">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> to enable login.
              </span>
            </div>
          )}

          <div className="mt-6 rounded-2xl border border-border bg-card p-6 shadow-sm">
            {/* Tabs */}
            <div className="mb-5 grid grid-cols-2 gap-1 rounded-lg bg-muted/60 p-1">
              {(["login", "signup"] as Mode[]).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => switchMode(m)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    mode === m ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {m === "login" ? "Log in" : "Sign up"}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} noValidate className="space-y-4">
              <div>
                <label htmlFor="email" className="text-xs font-semibold text-foreground">
                  Email
                </label>
                <div className="mt-1 flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 focus-within:border-primary/60">
                  <Mail className="h-4 w-4 text-muted-foreground" />
                  <input
                    id="email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => { setEmail(e.target.value); setEmailErr(null); setFormErr(null); }}
                    placeholder="you@company.com"
                    className="flex-1 bg-transparent text-sm focus:outline-none"
                  />
                </div>
                {emailErr && <p className="mt-1 text-xs text-destructive">{emailErr}</p>}
              </div>

              <div>
                <label htmlFor="password" className="text-xs font-semibold text-foreground">
                  Password
                </label>
                <div className="mt-1 flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 focus-within:border-primary/60">
                  <Lock className="h-4 w-4 text-muted-foreground" />
                  <input
                    id="password"
                    type="password"
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    value={password}
                    onChange={(e) => { setPassword(e.target.value); setPwErr(null); setFormErr(null); }}
                    placeholder="••••••••"
                    className="flex-1 bg-transparent text-sm focus:outline-none"
                  />
                </div>
                {pwErr && <p className="mt-1 text-xs text-destructive">{pwErr}</p>}
                {mode === "signup" && !pwErr && (
                  <p className="mt-1 text-xs text-muted-foreground">At least {PW_MIN} characters.</p>
                )}
              </div>

              {formErr && (
                <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{formErr}</span>
                </div>
              )}
              {notice && (
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm text-primary">
                  {notice}
                </div>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="group inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-all hover:brightness-110 disabled:opacity-60"
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Please wait…
                  </>
                ) : (
                  <>
                    {mode === "login" ? "Log in" : "Create account"}
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </>
                )}
              </button>
            </form>
          </div>

          <p className="mt-6 text-center text-sm text-muted-foreground">
            {mode === "login" ? (
              <>Don&apos;t have an account?{" "}
                <button type="button" onClick={() => switchMode("signup")} className="font-semibold text-primary hover:underline">Sign up</button>
              </>
            ) : (
              <>Already have an account?{" "}
                <button type="button" onClick={() => switchMode("login")} className="font-semibold text-primary hover:underline">Log in</button>
              </>
            )}
          </p>
          <p className="mt-2 text-center text-sm">
            <Link href="/" className="text-muted-foreground hover:text-foreground">← Back to home</Link>
          </p>
        </div>
      </main>
    </div>
  );
}

export default function AuthPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <AuthForm />
    </Suspense>
  );
}
