"use client";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * Browser Supabase client.
 *
 * Reads configuration from public env vars:
 *   NEXT_PUBLIC_SUPABASE_URL
 *   NEXT_PUBLIC_SUPABASE_ANON_KEY
 *
 * The client is created lazily and memoized. When the project is not yet
 * configured (env vars missing), `getSupabase()` returns null so the app can
 * still build and render an informative message instead of crashing.
 */

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

let client: SupabaseClient | null | undefined;

export const isSupabaseConfigured = Boolean(url && anonKey);

export function getSupabase(): SupabaseClient | null {
  if (client !== undefined) return client;

  if (!url || !anonKey) {
    client = null;
    return client;
  }

  client = createClient(url, anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storageKey: "tallyai-auth",
    },
  });
  return client;
}
