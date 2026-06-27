/**
 * TallyAI shared types.
 *
 * These mirror the REST/streaming API contract in the design document
 * (.kiro/specs/tallyai/design.md). The UI consumes them through the
 * `api` client in `src/lib/api`. Swapping the mock implementation for the
 * real FastAPI backend should require no changes to these types.
 */

/* ── Connections (Req 1) ───────────────────────────── */
export interface Connection {
  id: string;
  name: string;
  engine: string;
  host: string;
  status: "Connected" | "Error";
  readOnly: boolean;
}

export interface PrivilegeTestResult {
  ok: boolean;
  /** Privileges detected on the credential. */
  privileges: string[];
  /** Present when ok === false: the disallowed privileges that caused rejection (Req 1.6). */
  disallowed?: string[];
  reason?: string;
}

export interface NewConnectionInput {
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
}

/* ── Schema (Req 5) ────────────────────────────────── */
export interface SchemaColumn {
  name: string;
  type: string;
  pk?: boolean;
  fk?: string;
}

export interface SchemaTable {
  name: string;
  rows: string;
  columns: SchemaColumn[];
}

export interface CachedSchema {
  connectionId: string;
  schemaVersion: string;
  lastIntrospected: string;
  tables: SchemaTable[];
}

/* ── Semantic layer / metrics (Req 6) ──────────────── */
export interface MetricVersion {
  version: number;
  createdAt: string;
  formula: string;
}

export interface MetricDefinition {
  name: string;
  description: string;
  formula: string;
  condition?: string;
  grain: string;
  version: number;
  history: MetricVersion[];
}

/* ── Source traceability (Req 9) ───────────────────── */
export interface SupportingQuery {
  id: string;
  label: string;
  sql: string;
  params?: Record<string, string>;
  timestamp: string;
  latencyMs: number;
}

/* ── Ask answer model (Req 7, 8, 10, 11) ───────────── */
export type StepState = "done" | "running" | "pending" | "skipped";

export interface Step {
  label: string;
  state: StepState;
  ms?: number;
}

export type SummaryPart =
  | { type: "text"; text: string }
  | { type: "chip"; label: string; value: string; queryId: string };

export interface Hypothesis {
  title: string;
  body: string;
  confidence: "low" | "medium" | "high";
  coverage: string;
  correlation?: boolean;
  chips?: Array<{ label: string; value: string; queryId: string }>;
}

export type PipelineState = "complete" | "streaming" | "preview" | "failed";

export interface AnswerFailure {
  kind: "blocked" | "insufficient_data" | "timeout";
  title: string;
  reason: string;
}

export interface AnswerData {
  question: string;
  sql: string;
  explanation: string;
  metrics: string[];
  steps: Step[];
  chart: { label: string; value: number }[];
  table: { columns: string[]; rows: (string | number)[][] };
  summaryParts: SummaryPart[];
  facts: string[];
  hypotheses: Hypothesis[];
  truncated?: boolean;
  pipelineState?: PipelineState;
  failure?: AnswerFailure;
  /** Back-compat: equivalent to failure.kind === 'blocked'. */
  safety?: { blocked: boolean; reason?: string };
}

export type AnswerKind = "normal" | "blocked" | "insufficient" | "timeout";

export interface Suggestion {
  label: string;
  kind: AnswerKind;
}

export interface AskFixtures {
  seedAnswer: AnswerData;
  supportingQueries: SupportingQuery[];
  suggestions: Suggestion[];
}

/* ── History (Req 13) ──────────────────────────────── */
export interface HistoryItem {
  q: string;
  conn: string;
  time: string;
  rows: number;
  ms: number;
  queries: number;
}

/* ── Eval & observability (Req 12) ─────────────────── */
export interface AccuracyRun {
  run: string;
  score: number;
  examples: number;
}

export interface Trace {
  q: string;
  sql: string;
  tools: string[];
  latencyMs: number;
  costUsd: number;
  status: "ok" | "warn" | "blocked";
}

export interface EvalStat {
  label: string;
  value: string;
}

export interface EvalReport {
  labeledCount: number;
  currentAccuracy: number;
  deltaPp: number;
  history: AccuracyRun[];
  stats: EvalStat[];
  traces: Trace[];
}

/* ── Dashboard ─────────────────────────────────────── */
export interface DashboardMetric {
  id: string;
  label: string;
  value: string;
  period: string;
  delta: string;
  trend: "up" | "down";
  queryId: string;
}

export interface AttentionItem {
  title: string;
  tag: string;
  time: string;
}

export interface ActivityItem {
  q: string;
  who: string;
  time: string;
}

export interface DashboardData {
  metrics: DashboardMetric[];
  attention: AttentionItem[];
  recent: ActivityItem[];
  supportingQueries: SupportingQuery[];
}

/* ── Insights & saved queries ──────────────────────── */
export interface Insight {
  title: string;
  body: string;
  tag: string;
  schedule: string | null;
}

export interface SavedQuery {
  name: string;
  folder: string;
  last: string;
}
