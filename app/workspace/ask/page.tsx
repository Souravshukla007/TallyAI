"use client";

import { useState, useRef, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Sparkles, ArrowUp, RefreshCw, User, Eye, Zap, X, Clock } from "lucide-react";
import { AnswerCard } from "@/components/workspace/ask/AnswerCard";
import { api, USE_MOCK } from "@/lib/api";
import { usePreferences } from "@/hooks/usePreferences";
import type { RunEvent } from "@/lib/api";
import type { AnswerData, AnswerKind, AskFixtures, Step, SupportingQuery, Suggestion } from "@/types/tallyai";

const stepLabels = [
  "Schema",
  "Resolve metrics",
  "Generate SQL",
  "Safety check",
  "Execute",
  "Analyze",
  "Reason",
];

function buildSteps(progress: number): Step[] {
  return stepLabels.map((label, i): Step => {
    if (i < progress) return { label, state: "done", ms: Math.floor(Math.random() * 300) + 30 };
    if (i === progress) return { label, state: "running" };
    return { label, state: "pending" };
  });
}

function completedSteps(): Step[] {
  return stepLabels.map((label): Step => ({ label, state: "done", ms: Math.floor(Math.random() * 300) + 30 }));
}

function failedSteps(atIndex: number): Step[] {
  return stepLabels.map((label, i): Step => {
    if (i < atIndex) return { label, state: "done", ms: Math.floor(Math.random() * 200) + 40 };
    if (i === atIndex) return { label, state: "done", ms: Math.floor(Math.random() * 200) + 40 };
    return { label, state: "skipped" };
  });
}

function makeAnswer(seed: AnswerData, q: string, kind: AnswerKind): AnswerData {
  if (kind === "blocked") {
    // Reconciled with the spec: the deterministic safety layer rejects any
    // non-SELECT statement. The LLM is never the security boundary (Req 3).
    return {
      ...seed,
      question: q,
      sql: "-- Resolved to a write statement; rejected before execution\nDELETE FROM users\nWHERE last_login < '2024-01-01';",
      explanation:
        "This request resolves to a DELETE, a write statement. TallyAI's deterministic safety layer parses every query and only allows SELECT — the language model is never the security boundary. The statement is rejected before execution.",
      metrics: [],
      steps: failedSteps(3),
      pipelineState: "failed",
      failure: {
        kind: "blocked",
        title: "Blocked by safety",
        reason:
          "Non-SELECT statement (DELETE) rejected by the read-only safety layer. TallyAI never executes write or DDL statements against your database.",
      },
    };
  }
  if (kind === "insufficient") {
    return {
      ...seed,
      question: q,
      sql: "SELECT region, SUM(revenue) FROM orders\nWHERE region = 'Antarctica'\nGROUP BY region;",
      explanation: "Filters paid revenue to the requested region.",
      metrics: ["revenue"],
      steps: failedSteps(4),
      pipelineState: "failed",
      failure: {
        kind: "insufficient_data",
        title: "Insufficient data",
        reason:
          "0 rows match region = 'Antarctica' in the last 5 years. Try broadening the region filter or pick a different dimension.",
      },
    };
  }
  if (kind === "timeout") {
    return {
      ...seed,
      question: q,
      sql: "SELECT * FROM event_log\nORDER BY created_at DESC;",
      explanation: "A full-table scan of event_log (~480M rows). TallyAI recommends adding a time filter or sampling.",
      metrics: [],
      steps: failedSteps(4),
      pipelineState: "failed",
      failure: {
        kind: "timeout",
        title: "Query timed out at 30s",
        reason:
          "Execution exceeded the safety timeout. We did not auto-retry. Add a WHERE clause on created_at or LIMIT, then retry.",
      },
    };
  }
  return { ...seed, question: q, steps: completedSteps(), pipelineState: "complete" };
}

type ThreadItem = { id: string; q: string; kind: AnswerKind; runId: string; answer: AnswerData };

/** Minimal answer shell for HTTP mode before any results arrive. */
const emptyHttpAnswer: AnswerData = {
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
};

/** Maps a backend orchestration node to the UI's progress step index. */
const NODE_STEP: Record<string, number> = {
  schema_context: 0,
  semantic_resolution: 1,
  sql_generation: 2,
  safety_gate: 3,
  user_confirm: 3,
  execution: 4,
  analytics_charts: 5,
  reasoning_recommendations: 6,
  grounding_filter: 6,
};

export default function AskPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading…</div>}>
      <AskWorkspace />
    </Suspense>
  );
}

function AskWorkspace() {
  const searchParams = useSearchParams();
  const { previewByDefault } = usePreferences();
  const [fixtures, setFixtures] = useState<AskFixtures | null>(null);
  const [input, setInput] = useState("");
  const [previewMode, setPreviewMode] = useState(true);
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const streamsRef = useRef<Record<string, () => void>>({});
  const prefApplied = useRef(false);
  const autoSubmitted = useRef(false);

  // Supporting-query modal: the exact SQL behind a clicked source chip (Req 9.3, 9.4).
  const [sourceModal, setSourceModal] = useState<{
    open: boolean;
    loading: boolean;
    error: string | null;
    query: SupportingQuery | null;
  }>({ open: false, loading: false, error: null, query: null });

  // Load demo fixtures through the API seam, then seed the thread (mock only).
  useEffect(() => {
    let cancelled = false;
    api.getAskFixtures("prod").then((f) => {
      if (cancelled) return;
      setFixtures(f);
      if (USE_MOCK) {
        setThread([
          { id: "seed", q: f.seedAnswer.question, kind: "normal", runId: "seed-run", answer: makeAnswer(f.seedAnswer, f.seedAnswer.question, "normal") },
        ]);
      }
    });
    return () => {
      cancelled = true;
      // Tear down any open SSE streams on unmount.
      Object.values(streamsRef.current).forEach((stop) => stop());
      streamsRef.current = {};
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread]);

  // Simulated streaming — mock mode only. HTTP mode is driven by real SSE events.
  useEffect(() => {
    if (!USE_MOCK) return;
    if (!fixtures) return;
    const hasStreaming = thread.some((t) => t.answer.pipelineState === "streaming");
    if (!hasStreaming) return;
    const timer = setInterval(() => {
      setThread((prev) =>
        prev.map((t) => {
          if (t.answer.pipelineState !== "streaming") return t;
          const doneCount = t.answer.steps.filter((s) => s.state === "done").length;
          const nextProgress = doneCount + 1;
          const final = makeAnswer(fixtures.seedAnswer, t.q, t.kind);
          // Pause for preview after the safety check (index 3), before execution.
          if (previewMode && nextProgress === 4 && final.pipelineState !== "failed") {
            return {
              ...t,
              answer: {
                ...final,
                steps: buildSteps(4).map((s, i) => (i < 4 ? { ...s, state: "done" as const } : s)),
                pipelineState: "preview",
              },
            };
          }
          if (nextProgress >= stepLabels.length) {
            return { ...t, answer: final };
          }
          return { ...t, answer: { ...t.answer, steps: buildSteps(nextProgress) } };
        })
      );
    }, 350);
    return () => clearInterval(timer);
  }, [thread, previewMode, fixtures]);

  const detectKind = (q: string): AnswerKind => {
    const found = fixtures?.suggestions.find((s) => s.label.toLowerCase() === q.toLowerCase());
    return found?.kind ?? "normal";
  };

  const submit = (q: string) => {
    if (!q.trim() || !fixtures) return;
    if (!USE_MOCK) {
      void submitHttp(q);
      return;
    }
    const kind = detectKind(q);
    const id = String(Date.now());
    setThread((prev) => [
      ...prev,
      { id, q, kind, runId: `mock-${id}`, answer: { ...fixtures.seedAnswer, question: q, steps: buildSteps(0), pipelineState: "streaming" } },
    ]);
    setInput("");
  };

  // Apply the saved "preview before run" default once preferences hydrate.
  useEffect(() => {
    if (prefApplied.current) return;
    prefApplied.current = true;
    setPreviewMode(previewByDefault);
  }, [previewByDefault]);

  // Auto-run a question passed from the top-bar search (?q=...).
  useEffect(() => {
    const q = searchParams.get("q");
    if (autoSubmitted.current || !q || !fixtures) return;
    autoSubmitted.current = true;
    submit(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, fixtures]);

  /** Update one thread item's answer immutably. */
  const patchAnswer = (id: string, patch: (a: AnswerData) => AnswerData) =>
    setThread((prev) => prev.map((t) => (t.id === id ? { ...t, answer: patch(t.answer) } : t)));

  /** Map an incoming SSE run event to progress-stepper state. */
  const applyEvent = (id: string, e: RunEvent) => {
    if ((e.node === "safety_gate" || e.node === "grounding_filter") && e.phase === "rejected") {
      patchAnswer(id, (a) => ({
        ...a,
        steps: failedSteps(NODE_STEP[e.node] ?? 3),
        pipelineState: "failed",
        failure: {
          kind: "blocked",
          title: "Blocked by safety",
          reason: "Rejected by the deterministic read-only safety layer before execution.",
        },
      }));
      return;
    }
    const idx = NODE_STEP[e.node];
    if (idx === undefined) return;
    patchAnswer(id, (a) =>
      a.pipelineState === "failed" ? a : { ...a, steps: buildSteps(Math.min(idx + 1, stepLabels.length)) },
    );
  };

  /** Open the real SSE stream for a run and drive the stepper from events. */
  const openStream = (id: string, runId: string) => {
    const stop = api.streamRunEvents(runId, {
      onEvent: (e) => applyEvent(id, e),
      onError: () =>
        patchAnswer(id, (a) => ({
          ...a,
          steps: failedSteps(4),
          pipelineState: "failed",
          failure: { kind: "timeout", title: "Run stream interrupted", reason: "The run event stream ended unexpectedly." },
        })),
      onDone: () => {
        patchAnswer(id, (a) => (a.pipelineState === "failed" ? a : { ...a, steps: completedSteps(), pipelineState: "complete" }));
        delete streamsRef.current[id];
      },
    });
    streamsRef.current[id] = stop;
  };

  /** HTTP-mode submit: ask the backend, then stream node transitions over SSE. */
  const submitHttp = async (q: string) => {
    const id = String(Date.now());
    const base: AnswerData = { ...emptyHttpAnswer, question: q, steps: buildSteps(0), pipelineState: "streaming" };
    setThread((prev) => [...prev, { id, q, kind: "normal", runId: "", answer: base }]);
    setInput("");
    try {
      const handle = await api.askQuestion("prod", q, previewMode);
      patchAnswer(id, (a) => ({
        ...a,
        sql: handle.generatedSql ?? "",
        explanation: handle.explanation ?? "",
        metrics: handle.resolvedMetrics ?? [],
      }));
      setThread((prev) => prev.map((t) => (t.id === id ? { ...t, runId: handle.runId } : t)));

      if (handle.previewState === "REJECTED_BY_SAFETY") {
        patchAnswer(id, (a) => ({
          ...a,
          steps: failedSteps(3),
          pipelineState: "failed",
          failure: { kind: "blocked", title: "Blocked by safety", reason: handle.rejectionReason ?? "Rejected by the read-only safety layer." },
        }));
        return;
      }
      if (handle.previewState === "AWAITING_CONFIRMATION") {
        patchAnswer(id, (a) => ({ ...a, steps: buildSteps(4), pipelineState: "preview" }));
        return;
      }
      openStream(id, handle.runId);
    } catch (err) {
      patchAnswer(id, (a) => ({
        ...a,
        steps: failedSteps(2),
        pipelineState: "failed",
        failure: { kind: "insufficient_data", title: "Could not start run", reason: err instanceof Error ? err.message : "Request failed." },
      }));
    }
  };

  const runPreview = (id: string) => {
    if (!USE_MOCK) {
      const item = thread.find((t) => t.id === id);
      if (!item || !item.runId) return;
      patchAnswer(id, (a) => ({ ...a, pipelineState: "streaming", steps: buildSteps(4) }));
      void api.confirmRun(item.runId, "confirm").then(() => openStream(id, item.runId));
      return;
    }
    setThread((prev) =>
      prev.map((t) => (t.id === id ? { ...t, answer: { ...t.answer, pipelineState: "streaming", steps: buildSteps(4) } } : t))
    );
  };

  const retry = (id: string) => {
    const item = thread.find((t) => t.id === id);
    if (!item) return;
    streamsRef.current[id]?.();
    delete streamsRef.current[id];
    setThread((prev) => prev.filter((t) => t.id !== id));
    setTimeout(() => submit(item.q), 0);
  };

  /** Fetch and show the exact SQL behind a clicked source chip (Req 9.3, 9.4). */
  const openSource = async (itemId: string, queryId: string) => {
    const item = thread.find((t) => t.id === itemId);
    setSourceModal({ open: true, loading: true, error: null, query: null });
    try {
      const query = await api.getSupportingQuery(item?.runId ?? "", queryId);
      setSourceModal({ open: true, loading: false, error: null, query });
    } catch (err) {
      setSourceModal({ open: true, loading: false, error: err instanceof Error ? err.message : "Failed to load query", query: null });
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit(input.trim());
  };

  const suggestions: Suggestion[] = fixtures?.suggestions ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 py-8 space-y-6">
          {thread.length === 0 ? (
            <div className="text-center py-12">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Sparkles className="h-5 w-5" />
              </div>
              <h1 className="mt-4 text-2xl font-semibold tracking-tight">What do you want to know?</h1>
              <p className="mt-2 text-sm text-muted-foreground">Try one of these to see different agent states.</p>
              <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-xl mx-auto">
                {suggestions.map((s) => (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => submit(s.label)}
                    className="rounded-lg border border-border bg-card px-4 py-3 text-left text-sm hover:border-primary/40 hover:bg-muted/40 transition-colors"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            thread.map((m) => (
              <div key={m.id} className="space-y-3">
                <div className="flex items-start gap-3 justify-end">
                  <div className="rounded-2xl bg-primary text-primary-foreground px-4 py-2.5 text-sm max-w-xl">{m.q}</div>
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-muted text-muted-foreground shrink-0">
                    <User className="h-3.5 w-3.5" />
                  </span>
                </div>
                <AnswerCard
                  data={m.answer}
                  onOpenSource={(queryId) => openSource(m.id, queryId)}
                  onRun={() => runPreview(m.id)}
                  onRetry={() => retry(m.id)}
                  onEdit={() => setInput(m.q)}
                />
              </div>
            ))
          )}
          <div ref={endRef} />
        </div>
      </div>

      {/* Sticky input */}
      <div className="border-t border-border bg-background/95 backdrop-blur px-4 py-3">
        <form onSubmit={handleSubmit} className="mx-auto max-w-4xl">
          <div className="flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2 focus-within:border-primary/40 transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={1}
              placeholder="Ask a question about your data…"
              className="flex-1 resize-none bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none py-1.5 max-h-32"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
            />
            <button
              type="button"
              onClick={() => setThread([])}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted transition-colors"
              title="New conversation"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            <button
              type="submit"
              disabled={!input.trim()}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground disabled:opacity-40 transition-all hover:brightness-110"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 flex-wrap text-[11px]">
            <button
              type="button"
              onClick={() => setPreviewMode((p) => !p)}
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-medium transition-colors ${
                previewMode
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-card text-muted-foreground hover:text-foreground"
              }`}
              title="Toggle preview-before-run"
            >
              {previewMode ? <Eye className="h-3 w-3" /> : <Zap className="h-3 w-3" />}
              {previewMode ? "Preview before run" : "Auto-run"}
            </button>
            <span className="text-muted-foreground">Read-only · Shift+Enter for newline</span>
          </div>
        </form>
      </div>

      <SupportingQueryModal
        state={sourceModal}
        onClose={() => setSourceModal({ open: false, loading: false, error: null, query: null })}
      />
    </div>
  );
}

/** Modal showing the verbatim SQL that backs a clicked source chip (Req 9.3, 9.4). */
function SupportingQueryModal({
  state,
  onClose,
}: {
  state: { open: boolean; loading: boolean; error: string | null; query: SupportingQuery | null };
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (state.open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state.open, onClose]);

  if (!state.open) return null;
  const q = state.query;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-foreground/30" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl border border-border bg-background shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold">{q?.label ?? "Supporting query"}</h2>
            <p className="text-xs text-muted-foreground">Exact SQL from the execution log — read-only, never regenerated.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-3">
          {state.loading && <div className="text-sm text-muted-foreground">Loading exact SQL…</div>}
          {state.error && <div className="text-sm text-destructive">{state.error}</div>}
          {q && (
            <>
              <pre className="rounded-xl border border-border bg-foreground/[0.03] px-4 py-3 text-[11px] leading-relaxed font-mono text-foreground overflow-x-auto">
                {q.sql}
              </pre>
              {q.params && Object.keys(q.params).length > 0 && (
                <div className="rounded-lg border border-border bg-card px-4 py-2 text-[11px] text-muted-foreground font-mono">
                  {Object.entries(q.params).map(([k, v]) => (
                    <div key={k}>
                      {k} = <span className="text-foreground">{v}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                <Clock className="h-3 w-3" /> {q.latencyMs}ms{q.timestamp ? ` · ran ${q.timestamp}` : ""} · read-only
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
