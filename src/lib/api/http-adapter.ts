import type {
  AskRunHandle,
  TallyAIApi,
  NewMetricInput,
  RunEvent,
  RunEventHandlers,
} from "./client";
import type {
  AskFixtures,
  CachedSchema,
  Connection,
  DashboardData,
  EvalReport,
  HistoryItem,
  Insight,
  MetricDefinition,
  NewConnectionInput,
  PrivilegeTestResult,
  SavedQuery,
  SchemaColumn,
  SchemaTable,
  SupportingQuery,
} from "@/types/tallyai";

/**
 * HTTP implementation of the TallyAI API — talks to the FastAPI backend
 * described in the design's "Frontend Strategy and API Contract".
 *
 * This adapter mirrors `mockApi` exactly so the two are interchangeable behind
 * the `api` seam (see ./index.ts). It is a *thin client*: it never generates,
 * validates, executes, or explains SQL, and never grounds or suppresses claims.
 * Every safety, grounding, and tenant-isolation guarantee is enforced
 * server-side at or below the FastAPI layer.
 *
 * Toggle with `NEXT_PUBLIC_USE_MOCK=false`. Configure the base URL with
 * `NEXT_PUBLIC_API_URL` (default `http://localhost:8000/api/v1`).
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * MVP tenant scope. The backend resolves the tenant from the bearer token in
 * production; for the MVP it accepts a `tenant_id` query param and a matching
 * `X-Tenant-Id` header (tallyai/main.py). We send both, kept in agreement.
 */
const TENANT_ID = process.env.NEXT_PUBLIC_TENANT_ID ?? "demo-tenant";
const USER_ID = process.env.NEXT_PUBLIC_USER_ID ?? "default-user";

/* ── Low-level fetch helpers ────────────────────────────────────────────── */

function buildUrl(path: string, params: Record<string, string | undefined> = {}): string {
  const url = new URL(`${BASE}${path}`, typeof window === "undefined" ? "http://localhost" : window.location.origin);
  // Always scope to the tenant unless a caller overrides it.
  const merged: Record<string, string | undefined> = { tenant_id: TENANT_ID, ...params };
  for (const [key, value] of Object.entries(merged)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  }
  return url.toString();
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { "X-Tenant-Id": TENANT_ID, ...extra };
}

/** Extract a human-readable message from a FastAPI error body. */
function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const d = detail as { message?: string; error?: string; detail?: string };
      return d.message ?? d.error ?? d.detail ?? `request failed (${status})`;
    }
  }
  return `request failed (${status})`;
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const res = await fetch(buildUrl(path, params), {
    method: "GET",
    headers: authHeaders(),
    credentials: "include",
  });
  const body = await parseBody(res);
  if (!res.ok) throw new Error(errorMessage(res.status, body));
  return body as T;
}

async function post<T>(
  path: string,
  jsonBody: unknown,
  params?: Record<string, string | undefined>,
): Promise<T> {
  const res = await fetch(buildUrl(path, params), {
    method: "POST",
    headers: authHeaders({ "content-type": "application/json" }),
    credentials: "include",
    body: JSON.stringify(jsonBody),
  });
  const body = await parseBody(res);
  if (!res.ok) throw new Error(errorMessage(res.status, body));
  return body as T;
}

/* ── Response → frontend-type mappers ───────────────────────────────────── */

const READ_ONLY_PRIVILEGES = new Set(["CONNECT", "SELECT", "USAGE", "TEMP", "TEMPORARY"]);

interface RawColumn {
  name?: string;
  column_name?: string;
  type?: string;
  data_type?: string;
  pk?: boolean;
  primary_key?: boolean;
  is_primary_key?: boolean;
  fk?: string;
  foreign_key?: string;
  references?: string;
}

interface RawTable {
  name?: string;
  table_name?: string;
  rows?: number | string;
  row_count?: number | string;
  approx_rows?: number | string;
  columns?: RawColumn[];
}

function mapColumn(c: RawColumn): SchemaColumn {
  const fk = c.fk ?? c.foreign_key ?? c.references;
  return {
    name: c.name ?? c.column_name ?? "",
    type: c.type ?? c.data_type ?? "",
    pk: c.pk ?? c.primary_key ?? c.is_primary_key ?? undefined,
    fk: fk ?? undefined,
  };
}

function mapTable(t: RawTable): SchemaTable {
  const rows = t.rows ?? t.row_count ?? t.approx_rows ?? "";
  return {
    name: t.name ?? t.table_name ?? "",
    rows: String(rows),
    columns: (t.columns ?? []).map(mapColumn),
  };
}

interface RawSchema {
  schema_version?: string;
  introspected_at?: string;
  tables?: RawTable[];
}

function mapSchema(connectionId: string, raw: RawSchema): CachedSchema {
  return {
    connectionId,
    schemaVersion: raw.schema_version ?? "",
    lastIntrospected: raw.introspected_at ?? "",
    tables: (raw.tables ?? []).map(mapTable),
  };
}

interface RawMetric {
  name: string;
  formula: string;
  condition?: string | null;
  grain?: string | null;
  description?: string;
  version: number;
}

function mapMetric(m: RawMetric): MetricDefinition {
  return {
    name: m.name,
    description: m.description ?? "",
    formula: m.formula,
    condition: m.condition ?? undefined,
    grain: m.grain ?? "",
    version: m.version,
    // Full version history is served by a separate endpoint; the list view
    // shows only the latest version, so history starts empty here.
    history: [],
  };
}

interface RawHistoryEntry {
  historyId: string;
  question: string;
  queryIds?: string[];
  createdAt?: string | null;
}

function mapHistory(connectionId: string, entry: RawHistoryEntry): HistoryItem {
  return {
    q: entry.question,
    conn: connectionId,
    time: entry.createdAt ?? "",
    rows: 0,
    ms: 0,
    queries: (entry.queryIds ?? []).length,
  };
}

/* ── Adapter ────────────────────────────────────────────────────────────── */

export const httpApi: TallyAIApi = {
  /* Connections (Req 1) */
  listConnections: () => get<Connection[]>("/connections"),

  testConnection: async (input: NewConnectionInput): Promise<PrivilegeTestResult> => {
    // POST /connections runs privilege detection server-side and rejects
    // write/DDL/admin credentials, reporting the disallowed privileges (Req 1.6).
    const res = await fetch(buildUrl("/connections"), {
      method: "POST",
      headers: authHeaders({ "content-type": "application/json" }),
      credentials: "include",
      body: JSON.stringify({
        host: input.host,
        port: Number.parseInt(input.port, 10) || 5432,
        database: input.database,
        role: input.username,
        credentials: { user: input.username, password: input.password },
        tenant_id: TENANT_ID,
      }),
    });
    const body = (await parseBody(res)) as
      | { ok?: boolean; read_only?: boolean; privileges?: string[] }
      | { detail?: { ok?: boolean; error?: string; detail?: string; privileges?: string[] } }
      | null;

    if (res.ok) {
      const ok = body as { read_only?: boolean; privileges?: string[] };
      return { ok: true, privileges: ok?.privileges ?? [] };
    }

    // Rejection: FastAPI wraps the failure payload in `detail`.
    const detail = (body as { detail?: { error?: string; detail?: string; privileges?: string[] } })?.detail ?? {};
    const detected = detail.privileges ?? [];
    const disallowed = detected.filter((p) => !READ_ONLY_PRIVILEGES.has(p.toUpperCase()));
    return {
      ok: false,
      privileges: detected,
      disallowed: disallowed.length > 0 ? disallowed : detected,
      reason:
        detail.error ??
        detail.detail ??
        "Credential grants write or DDL privileges. Create a read-only role and retry.",
    };
  },

  /* Schema (Req 5) */
  getSchema: async (connectionId: string): Promise<CachedSchema> => {
    const raw = await get<RawSchema>(`/connections/${connectionId}/schema`);
    return mapSchema(connectionId, raw);
  },

  refreshSchema: async (connectionId: string): Promise<CachedSchema> => {
    // The backend re-introspection endpoint requires live target-DB
    // credentials as query params; a thin client never holds secrets, so we
    // request the refresh and fall back to the freshly cached schema. If the
    // refresh cannot proceed without credentials, the prior cache is retained
    // server-side (Req 5.5) and we simply re-read it.
    try {
      const raw = await post<RawSchema & { refreshed?: boolean }>(
        `/connections/${connectionId}/schema/refresh`,
        {},
      );
      if (raw && raw.schema_version) return mapSchema(connectionId, raw);
    } catch {
      // fall through to re-read the cached schema
    }
    return httpApi.getSchema(connectionId);
  },

  /* Semantic layer (Req 6) */
  listMetrics: async (connectionId: string): Promise<MetricDefinition[]> => {
    const raw = await get<RawMetric[]>(`/connections/${connectionId}/metrics`);
    return raw.map(mapMetric);
  },

  saveMetric: (connectionId: string, input: NewMetricInput) =>
    post<{ name: string; version: number }>(`/connections/${connectionId}/metrics`, {
      name: input.name,
      formula: input.formula,
      condition: input.condition ?? null,
      grain: input.grain ?? null,
      description: input.description,
      tenant_id: TENANT_ID,
    }),

  /* Ask fixtures — no backend endpoint; real ask uses askQuestion + streaming.
   * The seed answer/supporting queries stay empty in HTTP mode (those come
   * from real runs), but we surface a few generic starter prompts so the Ask
   * page shows clickable suggestions instead of a bare prompt. */
  getAskFixtures: (): Promise<AskFixtures> =>
    Promise.resolve({
      seedAnswer: {
        question: "",
        sql: "",
        explanation: "",
        metrics: [],
        steps: [],
        chart: [],
        table: { columns: [], rows: [] },
        summaryParts: [],
        facts: [],
        hypotheses: [],
      },
      supportingQueries: [],
      suggestions: [
        { label: "How many rows are in each table?", kind: "normal" },
        { label: "Show the most recent user activity", kind: "normal" },
        { label: "Which tables have the most records?", kind: "normal" },
        { label: "List the columns of the largest table", kind: "normal" },
      ],
    }),

  /* Ask run lifecycle (Req 7, 8) */
  askQuestion: (connectionId: string, question: string, previewEnabled: boolean): Promise<AskRunHandle> =>
    post<AskRunHandle>(
      `/connections/${connectionId}/questions`,
      { question, previewEnabled },
      { user_id: USER_ID },
    ),

  streamRunEvents: (runId: string, handlers: RunEventHandlers): (() => void) => {
    // SSE fallback per design: GET /runs/{runId}/events. Frames are named by
    // node (`event: {node}`), so we attach a listener per orchestration node
    // plus the `error` frame the backend emits on a tenant-denied/unknown run.
    const url = buildUrl(`/runs/${runId}/events`);
    const source = new EventSource(url, { withCredentials: true });
    let finished = false;

    const TERMINAL_NODES = new Set(["grounding_filter"]);
    const NODE_EVENTS = [
      "schema_context",
      "semantic_resolution",
      "sql_generation",
      "safety_gate",
      "user_confirm",
      "execution",
      "analytics_charts",
      "reasoning_recommendations",
      "grounding_filter",
    ];

    const close = () => {
      if (finished) return;
      finished = true;
      source.close();
    };

    const handleNode = (raw: MessageEvent) => {
      let event: RunEvent;
      try {
        event = JSON.parse(raw.data) as RunEvent;
      } catch {
        return;
      }
      handlers.onEvent(event);
      // Reaching the grounding filter (or any rejection) ends the stream.
      if (TERMINAL_NODES.has(event.node) || event.phase === "rejected") {
        close();
        handlers.onDone?.();
      }
    };

    for (const node of NODE_EVENTS) {
      source.addEventListener(node, handleNode as EventListener);
    }

    source.addEventListener("error", (e: Event) => {
      const data = (e as MessageEvent).data;
      if (typeof data === "string" && data) {
        // A server-emitted `error` frame (e.g. unknown/cross-tenant run).
        close();
        handlers.onError?.(new Error("run stream rejected"));
        return;
      }
      // A transport-level error/close. If we have not finished, treat the
      // close as the end of the run (the backend closes the stream when the
      // run completes) and stop EventSource auto-reconnect.
      if (!finished) {
        close();
        handlers.onDone?.();
      }
    });

    return close;
  },

  confirmRun: (runId: string, decision: "confirm" | "reject") =>
    post<{ runId: string; state: "EXECUTING" | "DISCARDED" }>(`/runs/${runId}/confirm`, { decision }),

  /* Source traceability (Req 9.3, 9.4) */
  getSupportingQuery: async (runId: string, queryId: string): Promise<SupportingQuery> => {
    const raw = await get<{
      queryId: string;
      exactSql: string;
      parameters: unknown;
      executedAt: string | null;
      latencyMs: number;
    }>(`/runs/${runId}/claims/${queryId}/supporting-query`);
    const params =
      raw.parameters && typeof raw.parameters === "object"
        ? (Object.fromEntries(
            Object.entries(raw.parameters as Record<string, unknown>).map(([k, v]) => [k, String(v)]),
          ) as Record<string, string>)
        : undefined;
    return {
      id: raw.queryId,
      label: "Supporting query",
      sql: raw.exactSql,
      params,
      timestamp: raw.executedAt ?? "",
      latencyMs: raw.latencyMs,
    };
  },

  /* History (Req 13) */
  listHistory: async (connectionId: string, search?: string): Promise<HistoryItem[]> => {
    const raw = await get<{ entries: RawHistoryEntry[] }>(
      `/connections/${connectionId}/history`,
      { user_id: USER_ID, search },
    );
    return (raw.entries ?? []).map((e) => mapHistory(connectionId, e));
  },

  /* ── Endpoints outside Task 18 scope ──────────────────────────────────
   * The backend exposes no dashboard / insights / saved-query / eval-report
   * surface yet, so these return empty envelopes to keep unrelated pages from
   * crashing in HTTP mode. They are wired in a later task.                  */
  getEvalReport: (): Promise<EvalReport> =>
    Promise.resolve({
      labeledCount: 0,
      currentAccuracy: 0,
      deltaPp: 0,
      history: [],
      stats: [],
      traces: [],
    }),

  getDashboard: (): Promise<DashboardData> =>
    Promise.resolve({ metrics: [], attention: [], recent: [], supportingQueries: [] }),

  listInsights: (): Promise<Insight[]> => Promise.resolve([]),

  listSavedQueries: (): Promise<SavedQuery[]> => Promise.resolve([]),
};
