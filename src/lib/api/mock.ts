import type { TallyAIApi, AskRunHandle, RunEventHandlers, NewMetricInput } from "./client";
import type { NewConnectionInput, PrivilegeTestResult, SupportingQuery } from "@/types/tallyai";
import {
  mockAskFixtures,
  mockConnections,
  mockDashboard,
  mockEval,
  mockHistory,
  mockInsights,
  mockMetrics,
  mockSaved,
  mockSchema,
} from "./mock-data";

/** Simulate network latency so loading states are exercised. */
const delay = <T>(value: T, ms = 250): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms));

/**
 * Mock implementation of the TallyAI API.
 *
 * Returns deep copies so callers can mutate locally (e.g. metric edits)
 * without corrupting the shared fixtures.
 */
const clone = <T>(value: T): T => structuredClone(value);

export const mockApi: TallyAIApi = {
  listConnections: () => delay(clone(mockConnections)),

  testConnection: (input: NewConnectionInput): Promise<PrivilegeTestResult> => {
    // Deterministic demo: a username hinting at read-only passes; anything
    // else returns a write-capable credential that the backend would reject.
    const readOnly = /read|ro|select|viewer|reporter/i.test(input.username);
    if (readOnly) {
      return delay({ ok: true, privileges: ["CONNECT", "SELECT", "USAGE"] });
    }
    return delay({
      ok: false,
      privileges: ["CONNECT", "SELECT", "INSERT", "UPDATE", "DELETE", "DROP"],
      disallowed: ["INSERT", "UPDATE", "DELETE", "DROP"],
      reason: "Credential grants write and DDL privileges. Create a read-only role and retry.",
    });
  },

  getSchema: () => delay(clone(mockSchema)),
  refreshSchema: () =>
    delay({ ...clone(mockSchema), lastIntrospected: "just now", schemaVersion: "v13" }, 700),

  listMetrics: () => delay(clone(mockMetrics)),

  saveMetric: (_connectionId: string, input: NewMetricInput) => {
    // Demo: appending a version returns the next version number. Mock fixtures
    // are not mutated; the real backend persists a new immutable version.
    const existing = mockMetrics.find((m) => m.name === input.name);
    const nextVersion = existing ? existing.version + 1 : 1;
    return delay({ name: input.name, version: nextVersion });
  },

  getAskFixtures: () => delay(clone(mockAskFixtures)),

  askQuestion: (_connectionId: string, question: string, previewEnabled: boolean): Promise<AskRunHandle> =>
    delay({
      runId: `mock-${Date.now()}`,
      generatedSql: mockAskFixtures.seedAnswer.sql,
      explanation: mockAskFixtures.seedAnswer.explanation,
      resolvedMetrics: mockAskFixtures.seedAnswer.metrics,
      previewState: previewEnabled ? "AWAITING_CONFIRMATION" : "EXECUTING",
    } satisfies AskRunHandle),

  streamRunEvents: (runId: string, handlers: RunEventHandlers): (() => void) => {
    // Simulate an ordered node stream so the prototype UI exercises the same
    // event-driven code path as the HTTP adapter.
    const nodes = [
      "schema_context",
      "semantic_resolution",
      "sql_generation",
      "safety_gate",
      "execution",
      "analytics_charts",
      "reasoning_recommendations",
      "grounding_filter",
    ];
    let i = 0;
    let cancelled = false;
    const timer = setInterval(() => {
      if (cancelled) return;
      if (i >= nodes.length) {
        clearInterval(timer);
        handlers.onDone?.();
        return;
      }
      handlers.onEvent({ runId, node: nodes[i], phase: "completed" });
      i += 1;
    }, 300);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  },

  confirmRun: (runId: string, decision: "confirm" | "reject") =>
    delay({ runId, state: decision === "confirm" ? ("EXECUTING" as const) : ("DISCARDED" as const) }),

  getSupportingQuery: (_runId: string, queryId: string): Promise<SupportingQuery> => {    const found = mockAskFixtures.supportingQueries.find((q) => q.id === queryId);
    if (found) return delay(clone(found));
    return delay({
      id: queryId,
      label: "Supporting query",
      sql: "-- exact SQL is read verbatim from the Execution Log",
      timestamp: "just now",
      latencyMs: 0,
    } satisfies SupportingQuery);
  },

  listHistory: (_connectionId, search) => {
    const term = (search ?? "").toLowerCase();
    const filtered = term
      ? mockHistory.filter((h) => h.q.toLowerCase().includes(term))
      : mockHistory;
    return delay(clone(filtered));
  },

  getEvalReport: () => delay(clone(mockEval)),

  getDashboard: () => delay(clone(mockDashboard)),

  listInsights: () => delay(clone(mockInsights)),

  listSavedQueries: () => delay(clone(mockSaved)),
};
