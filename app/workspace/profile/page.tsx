"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { User as UserIcon, Mail, Lock, Loader2, Check, AlertTriangle, LogOut } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useDemo } from "@/hooks/useDemo";

const PW_MIN = 8;
const PW_MAX = 128;

export default function ProfilePage() {
  const { user, loading, configured, updateProfile, updatePassword, signOut } = useAuth();
  const { isDemo, exitDemoMode } = useDemo();
  const router = useRouter();

  const [fullName, setFullName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameMsg, setNameMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [savingPw, setSavingPw] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (user) {
      setFullName((user.user_metadata?.full_name as string | undefined) ?? "");
    }
  }, [user]);

  const createdAt = user?.created_at ? new Date(user.created_at).toLocaleDateString() : null;

  const handleSaveName = async (e: React.FormEvent) => {
    e.preventDefault();
    setNameMsg(null);
    setSavingName(true);
    const res = await updateProfile(fullName);
    setSavingName(false);
    setNameMsg(res.ok ? { ok: true, text: "Display name updated." } : { ok: false, text: res.error ?? "Update failed." });
  };

  const handleSavePw = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwMsg(null);
    if (password.length < PW_MIN || password.length > PW_MAX) {
      setPwMsg({ ok: false, text: `Password must be ${PW_MIN}–${PW_MAX} characters.` });
      return;
    }
    if (password !== confirm) {
      setPwMsg({ ok: false, text: "Passwords do not match." });
      return;
    }
    setSavingPw(true);
    const res = await updatePassword(password);
    setSavingPw(false);
    if (res.ok) {
      setPassword("");
      setConfirm("");
      setPwMsg({ ok: true, text: "Password changed." });
    } else {
      setPwMsg({ ok: false, text: res.error ?? "Update failed." });
    }
  };

  const handleSignOut = async () => {
    await signOut();
    exitDemoMode();
    router.push("/");
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  // Demo session (no authenticated user).
  if (!user) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-8">
        <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
        <div className="mt-8 rounded-2xl border border-dashed border-border p-10 text-center">
          <span className="mx-auto inline-flex h-10 w-10 items-center justify-center rounded-full bg-secondary/15 text-secondary-foreground">
            <UserIcon className="h-5 w-5" />
          </span>
          <h2 className="mt-3 text-base font-semibold">You&apos;re in demo mode</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {isDemo ? "Exploring sample data. " : ""}Log in to create and manage your profile.
          </p>
          <Link
            href="/auth"
            className="mt-5 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:brightness-110 transition-all"
          >
            Log in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight">Profile</h1>
      <p className="mt-1 text-sm text-muted-foreground">Manage your account details.</p>

      {/* Identity card */}
      <div className="mt-8 flex items-center gap-4 rounded-2xl border border-border bg-card p-5">
        <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground text-lg font-semibold">
          {(fullName || user.email || "U").slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0">
          <div className="truncate text-base font-semibold">{fullName || user.email?.split("@")[0]}</div>
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Mail className="h-3.5 w-3.5" /> {user.email}
          </div>
          {createdAt && <div className="mt-0.5 text-xs text-muted-foreground">Member since {createdAt}</div>}
        </div>
      </div>

      {!configured && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-secondary/40 bg-secondary/10 p-3 text-sm text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-secondary-foreground" />
          Auth isn&apos;t fully configured, so changes can&apos;t be saved.
        </div>
      )}

      {/* Display name */}
      <form onSubmit={handleSaveName} className="mt-6 rounded-2xl border border-border bg-card p-5">
        <h2 className="text-sm font-semibold">Display name</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">Shown in the top bar and across the workspace.</p>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row">
          <input
            value={fullName}
            onChange={(e) => { setFullName(e.target.value); setNameMsg(null); }}
            placeholder="Your name"
            maxLength={120}
            className="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:border-primary/60"
          />
          <button
            type="submit"
            disabled={savingName}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110 transition-all disabled:opacity-60"
          >
            {savingName ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
          </button>
        </div>
        {nameMsg && (
          <p className={`mt-2 inline-flex items-center gap-1 text-xs ${nameMsg.ok ? "text-primary" : "text-destructive"}`}>
            {nameMsg.ok ? <Check className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
            {nameMsg.text}
          </p>
        )}
      </form>

      {/* Password */}
      <form onSubmit={handleSavePw} className="mt-6 rounded-2xl border border-border bg-card p-5">
        <h2 className="text-sm font-semibold">Change password</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">At least {PW_MIN} characters.</p>
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 focus-within:border-primary/60">
            <Lock className="h-4 w-4 text-muted-foreground" />
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setPwMsg(null); }}
              placeholder="New password"
              className="flex-1 bg-transparent text-sm focus:outline-none"
            />
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 focus-within:border-primary/60">
            <Lock className="h-4 w-4 text-muted-foreground" />
            <input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => { setConfirm(e.target.value); setPwMsg(null); }}
              placeholder="Confirm new password"
              className="flex-1 bg-transparent text-sm focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={savingPw || !password}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:brightness-110 transition-all disabled:opacity-60"
          >
            {savingPw ? <Loader2 className="h-4 w-4 animate-spin" /> : "Update password"}
          </button>
        </div>
        {pwMsg && (
          <p className={`mt-2 inline-flex items-center gap-1 text-xs ${pwMsg.ok ? "text-primary" : "text-destructive"}`}>
            {pwMsg.ok ? <Check className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
            {pwMsg.text}
          </p>
        )}
      </form>

      <button
        type="button"
        onClick={handleSignOut}
        className="mt-6 inline-flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2 text-sm text-foreground hover:bg-muted transition-colors"
      >
        <LogOut className="h-4 w-4" /> Sign out
      </button>
    </div>
  );
}
