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
  SupportingQuery,
} from "@/types/tallyai";

/* ── Run lifecycle / streaming (design §"Streaming agent progress") ─────── */

/**
 * Run handle returned by `askQuestion`. Mirrors the FastAPI
 * `POST /connections/{id}/questions` response. The candidate SQL has already
 * passed (or been rejected by) the deterministic Safety Layer server-side.
 */
export interface AskRunHandle {
  runId: string;
  generatedSql?: string;
  explanation?: string;
  resolvedMetrics: string[];
  previewState?:
    | "AWAITING_CONFIRMATION"
    | "EXECUTING"
    | "REJECTED_BY_SAFETY"
    | "TRANSLATION_FAILED"
    | "DISCARDED";
  rejectionReason?: string;
}

/**
 * A single orchestration node transition pushed over the SSE/WebSocket stream.
 * Schema: `{runId, node, phase, payload?}`.
 */
export interface RunEvent {
  runId: string;
  node: string;
  phase: "started" | "completed" | "rejected";
  payload?: Record<string, unknown> | null;
}

/** Callbacks for a streamed run. `unsubscribe` is the return of `streamRunEvents`. */
export interface RunEventHandlers {
  onEvent: (event: RunEvent) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
}

/** Request body for creating / versioning a semantic metric (Req 6.1, 6.6). */
export interface NewMetricInput {
  name: string;
  formula: string;
  condition?: string;
  grain?: string;
  description: string;
}

/**
 * TallyAIApi is the single seam between the UI and the backend.
 *
 * The UI depends only on this interface. `mockApi` returns demo fixtures;
 * `httpApi` (TODO) will call the real FastAPI endpoints described in the
 * design's API contract. Every method is tenant-scoped server-side; the
 * client never enforces safety, grounding, or authorization.
 */
export interface TallyAIApi {
  // Connections (Req 1)
  listConnections(): Promise<Connection[]>;
  testConnection(input: NewConnectionInput): Promise<PrivilegeTestResult>;

  // Schema (Req 5)
  getSchema(connectionId: string): Promise<CachedSchema>;
  refreshSchema(connectionId: string): Promise<CachedSchema>;

  // Semantic layer (Req 6)
  listMetrics(connectionId: string): Promise<MetricDefinition[]>;
  /** Create or version a metric definition; appends a new version (Req 6.1, 6.6). */
  saveMetric(connectionId: string, input: NewMetricInput): Promise<{ name: string; version: number }>;

  // Ask fixtures (Req 7, 8, 9, 10, 11)
  getAskFixtures(connectionId: string): Promise<AskFixtures>;

  // Ask run lifecycle + streaming (Req 7, 8)
  /** Submit a question and start an orchestration run. */
  askQuestion(connectionId: string, question: string, previewEnabled: boolean): Promise<AskRunHandle>;
  /** Subscribe to a run's SSE event stream. Returns an unsubscribe function. */
  streamRunEvents(runId: string, handlers: RunEventHandlers): () => void;
  /** Confirm or reject a previewed query before execution (Req 8.2–8.4). */
  confirmRun(runId: string, decision: "confirm" | "reject"): Promise<{ runId: string; state: "EXECUTING" | "DISCARDED" }>;

  // Source traceability (Req 9.3, 9.4)
  /** Fetch the verbatim SQL backing a claim's query id, read from the Execution Log. */
  getSupportingQuery(runId: string, queryId: string): Promise<SupportingQuery>;

  // History (Req 13)
  listHistory(connectionId: string, search?: string): Promise<HistoryItem[]>;

  // Eval & observability (Req 12)
  getEvalReport(): Promise<EvalReport>;

  // Dashboard
  getDashboard(connectionId: string): Promise<DashboardData>;

  // Intelligence
  listInsights(connectionId: string): Promise<Insight[]>;
  listSavedQueries(connectionId: string): Promise<SavedQuery[]>;
}
