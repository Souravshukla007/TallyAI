# 🧭 TallyAI: The AI Database Consultant with a Deterministic Safety Boundary

[![Next.js](https://img.shields.io/badge/Next.js-16.2.9-black?style=flat-square&logo=next.js)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.2-61DAFB?style=flat-square&logo=react)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-1C3C3C?style=flat-square&logo=langchain)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Read--Only_Role-4169E1?style=flat-square&logo=postgresql)](https://www.postgresql.org/)
[![sqlglot](https://img.shields.io/badge/sqlglot-SQL_Safety_Gate-FF6B35?style=flat-square)](https://github.com/tobymao/sqlglot)
[![MCP](https://img.shields.io/badge/MCP-1.28-6E56CF?style=flat-square)](https://modelcontextprotocol.io/)
[![Tests](https://img.shields.io/badge/Tests-156_passing-2ECC71?style=flat-square)](#-testing--correctness)

TallyAI turns plain-English business questions into **safe, read-only SQL**, executes it against your PostgreSQL database, and answers like a consultant — not just a query box. It returns the number, the chart, the supporting query, and the reasoning behind it. The defining architectural decision: **the LLM is never the security boundary.** Every generated query passes through a deterministic, non-model safety gate before a single byte touches your database.

---

## ⚡ Recruiter Fast-Track (30-Second Summary)

If you are a Recruiter, Hiring Manager, or SDE Interviewer evaluating the technical depth of this repository, here is what makes it stand out immediately:

*   **Deterministic Safety Layer (not "trust the model")**: A pure, side-effect-free function parses every candidate query with `sqlglot`, enforces a SELECT-only allowlist, blocks credential-column patterns, rejects oversized `LIMIT`s, and auto-injects a row cap — *before* execution. The model proposes; deterministic code disposes. This invariant is locked down with **property-based tests** (Hypothesis), not just examples.
*   **LangGraph "Brain", Trusted Tools as "Hands"**: A single `StateGraph` orchestrates the pipeline `schema → semantics → SQL → safety gate → (preview) → execution → analytics → reasoning → grounding`. Routing is deterministic; the security gate sits in non-model code and is MCP-ready as an in-process tool boundary.
*   **Consultant-Grade Grounding**: Every quantitative claim carries the `query_id` that produced it. A deterministic `grounding_filter` *suppresses any claim with no backing query* — eliminating fabricated numbers structurally rather than by prompt-begging.
*   **Production Security Posture**: Per-tenant read-only DB roles, Fernet-encrypted credentials at rest, privilege detection that refuses write/DDL/admin connections, and strict multi-tenant isolation on every retrieval path.

---

## 📂 Direct Code Navigation (Key Implementation Anchors)

Skip the folder tree and jump straight into the production code behind the headline features:

| Feature | Key Logic File | Role / Purpose |
| :--- | :--- | :--- |
| **⛔ Deterministic Safety Gate** | [`backend/tallyai/core/safety.py`](./backend/tallyai/core/safety.py) | Pure function: `sqlglot` parse + SELECT allowlist + blocked-column scan + row-cap injection. No LLM, no DB, no side effects. |
| **🧠 LangGraph Orchestrator** | [`backend/tallyai/core/orchestrator.py`](./backend/tallyai/core/orchestrator.py) | The `StateGraph` wiring every node, the deterministic routers, grounding filter, and run tracing. |
| **📖 Semantic Business Layer** | [`backend/tallyai/core/semantic_layer.py`](./backend/tallyai/core/semantic_layer.py) | Versioned YAML metric definitions (revenue, churn, MRR) resolved into canonical SQL formulas. |
| **▶️ Safe Query Executor** | [`backend/tallyai/services/query_executor.py`](./backend/tallyai/services/query_executor.py) | Executes only approved SQL, enforces statement timeout + row cap, writes the audit log. No retries. |
| **🔌 Connection Manager** | [`backend/tallyai/services/connection_manager.py`](./backend/tallyai/services/connection_manager.py) | Privilege detection — rejects superuser / CREATE / DDL roles before any connection persists. |
| **🔐 Credential Store** | [`backend/tallyai/services/credential_store.py`](./backend/tallyai/services/credential_store.py) | Fernet encryption at rest, tenant-scoped retrieval, zero credential values in logs. |
| **💬 Reasoning Layer** | [`backend/tallyai/services/reasoning_layer.py`](./backend/tallyai/services/reasoning_layer.py) | Facts vs. interpretation vs. recommendations, with claims bound to supporting query IDs. |
| **🔗 Typed API Seam** | [`src/types/tallyai.ts`](./src/types/tallyai.ts) | Single source of truth for the contract shared by the Next.js client and FastAPI backend. |

---

## 📌 Problem Statement

Business teams sit on top of rich relational databases but cannot speak SQL. The obvious fix — "let an LLM write and run the SQL" — is dangerous in three ways that most demos ignore:

1.  **The LLM as a security hole**: If a language model is allowed to decide what runs against your database, one clever prompt (or one hallucinated `DELETE`/`DROP`) is a production incident. Treating the model as the safety boundary is the core anti-pattern.
2.  **Confidently wrong numbers**: General-purpose models happily invent metrics. "Revenue dropped 18%" means nothing if you cannot click through to the exact query that produced the 18%.
3.  **Answers without insight**: A raw table is not a consultant. Stakeholders want the number, the chart, the *why*, and a recommended next action — grounded in real data, not vibes.

**TallyAI** solves this with a layered architecture where the model is a powerful *proposer* hemmed in by deterministic, auditable code. It maps natural language to canonical business metrics, generates SQL, forces that SQL through a non-model safety gate, executes read-only under a least-privilege role, and returns a grounded, traceable, consultant-style answer.

---

## ✨ Key Features

### ⛔ Deterministic Safety (the non-negotiable core)
*   **SELECT-only allowlist**: Statement type is checked against an allowlist after a real `sqlglot` parse — `INSERT`, `UPDATE`, `DELETE`, `DROP`, and friends are rejected before execution.
*   **Row-cap enforcement**: Queries with no `LIMIT` get one injected automatically; queries with an explicit oversized `LIMIT` are rejected.
*   **Credential-column blocklist**: Column names matching patterns like `password`, `api_key`, `token`, `secret`, `ssn`, `credit_card` are refused.
*   **Pure & property-tested**: `SafetyLayer.validate()` is a pure function (same input → same decision), validated with Hypothesis-driven property tests so the guarantee holds across generated inputs, not just hand-picked ones.

### 🧠 LangGraph Orchestration
*   **Deterministic pipeline**: `schema_context → semantic_resolution → sql_generation → safety_gate → user_confirm? → execution → analytics_charts → reasoning_recommendations → grounding_filter`.
*   **Model-independent routing**: A non-SELECT short-circuits to a rejection message and *never reaches the executor*; a translation failure returns a friendly message and executes nothing.
*   **Run tracing**: Every run records a `Trace` (question, generated SQL, ordered tool calls, latency, cost) on a best-effort basis that can never interrupt answering.

### 📖 Semantic Business Layer
*   **Versioned metric definitions**: Business terms (`revenue`, `churn_rate`, `active_users`, `MRR`) are stored as versioned formulas so "what's our churn trend?" resolves to one canonical definition instead of being re-guessed each time.
*   **YAML-seeded, DB-versioned**: Metrics load from YAML and are versioned in the database, with prior versions superseded — improving SQL accuracy and consistency.

### 🔍 Grounding & Traceability
*   **Claims bound to queries**: Every quantitative claim carries the `query_id` that produced it; the UI renders "Supporting Queries" directly from the Execution Log.
*   **Structural suppression**: A deterministic filter drops any claim lacking a backing query — fabricated numbers can't survive the pipeline.

### 💬 Consultant-Style Reasoning
*   **Layered output**: Natural Language → SQL → Results → Analytics → Business Reasoning → Recommendations.
*   **Honest framing**: Facts are separated from interpretation; recommendations are hypotheses, not commands; correlation is flagged, never sold as causation; confidence and coverage are surfaced.

### 📊 Analytics & Charts First
*   **Chart + Summary + Insights by default**: Results return a chart-ready payload, a plain-language summary, and insight bullets — because people read charts faster than tables.

### 🔐 Security & Multi-Tenancy
*   **Least-privilege connections**: Privilege detection refuses superuser/CREATE/DDL roles at connection time.
*   **Encrypted credentials**: Fernet symmetric encryption at rest; credential values never logged; tenant-scoped decryption only.
*   **Preview-before-execute**: Optionally halt on a previewed query and require explicit user confirmation before anything runs.

### 🛰️ Streaming & Observability
*   **Live run updates**: WebSocket + SSE streaming surfaces pipeline progress to the UI.
*   **Query history & eval harness**: Persisted run history plus an evaluation harness scaffold for measuring NL→SQL accuracy.

---

## 🏗️ System Architecture

TallyAI is a thin Next.js client over a FastAPI + LangGraph backend. The trust boundary is the API layer and the deterministic safety gate — never the client and never the model.

```mermaid
graph TD
    User([Business User]) -->|Plain-English question| UI[Next.js 16 Thin Client]

    subgraph Client [Client Layer · pluggable]
        UI -->|Typed API seam| SDK[API Client + Mock/HTTP adapter]
    end

    subgraph API [FastAPI Backend API Layer · trust boundary]
        SDK -->|/runs ask| RUNS[Runs API]
        SDK -->|/connections| CONN[Connections API]
        SDK -->|/schema| SCHEMA_API[Schema API]
        SDK -->|/metrics| METRICS[Metrics API]
        SDK -->|/stream WS+SSE| STREAM[Streaming API]
    end

    subgraph Brain [LangGraph Orchestrator]
        RUNS --> SEM[Semantic Resolution]
        SEM --> GEN[SQL Generation - LLM]
        GEN --> SAFE[⛔ Deterministic Safety Gate]
        SAFE -->|reject| REJECT[Rejection message · no execution]
        SAFE -->|approve| PREVIEW{Preview enabled?}
        PREVIEW -->|await confirm| HALT[Awaiting Confirmation]
        PREVIEW -->|run| EXEC[Safe Query Executor]
        EXEC --> CHARTS[Analytics + Charts]
        CHARTS --> REASON[Reasoning + Recommendations]
        REASON --> GROUND[Grounding Filter]
    end

    subgraph Data [Persistence]
        EXEC -->|read-only role| PG[(Target PostgreSQL)]
        EXEC -->|audit| LOG[(Execution Log · query IDs)]
        SEM -->|metric defs| APPDB[(App DB · SQLAlchemy)]
        SAFE -.->|MCP-ready tool boundary| TOOLS[Trusted Tool Layer]
    end

    subgraph Models [LLM Providers]
        GEN -->|langchain| LLM[OpenAI / Anthropic]
        REASON -->|langchain| LLM
    end

    classDef client fill:#3B82F6,stroke:#1d4ed8,stroke-width:2px,color:#fff;
    classDef api fill:#009688,stroke:#00695c,stroke-width:2px,color:#fff;
    classDef brain fill:#6E56CF,stroke:#4c3a9c,stroke-width:2px,color:#fff;
    classDef safe fill:#FF6B35,stroke:#c0392b,stroke-width:2px,color:#fff;
    classDef db fill:#2ECC71,stroke:#27ae60,stroke-width:2px,color:#fff;

    class User,UI,SDK client;
    class RUNS,CONN,SCHEMA_API,METRICS,STREAM api;
    class SEM,GEN,PREVIEW,EXEC,CHARTS,REASON,GROUND,HALT,REJECT,TOOLS brain;
    class SAFE safe;
    class PG,LOG,APPDB db;
```

---

## 💻 Tech Stack

| Technology | Category | Usage / Context |
| :--- | :--- | :--- |
| **Next.js 16.2.9** | Frontend Framework | App Router thin client, server/client component boundaries |
| **React 19.2** | Frontend UI | Workspace dashboard, ask/insights/history views |
| **TypeScript** | Language (Frontend) | Typed API seam shared with the backend contract |
| **Tailwind CSS 4** | Styling | Utility-first design system inherited from the prototype foundation |
| **FastAPI 0.115** | Backend Framework | Async REST API, WebSocket + SSE streaming endpoints |
| **LangGraph 1.x** | Orchestration | `StateGraph` pipeline with deterministic routing |
| **LangChain (OpenAI / Anthropic)** | LLM Integration | NL→SQL generation and reasoning, provider-agnostic |
| **sqlglot 23** | SQL Safety | Parsing + AST inspection inside the deterministic safety gate |
| **SQLAlchemy 2 (async)** | App ORM | Connections, metrics, execution log, traces |
| **asyncpg** | DB Driver | Async access to target PostgreSQL databases |
| **PostgreSQL** | Target Database | Queried through a per-tenant read-only role |
| **cryptography (Fernet)** | Security | Symmetric encryption of stored DB credentials |
| **MCP 1.28** | Tooling Protocol | Tool-server boundary for schema / safe-query / metric tools |
| **Hypothesis** | Testing | Property-based tests for safety-layer invariants |
| **pytest / pytest-asyncio** | Testing | 156+ unit, integration, and property tests |

---

## 🗃️ Data Model

The application database (SQLAlchemy) stores connections, credentials, semantic metrics, the execution audit log, and run traces. The *target* business database is never modified — it is read through a least-privilege role.

```
                    ┌────────────────────────┐
                    │    TenantConnection    │
                    │  (host, port, db, role)│
                    └───────────┬────────────┘
                                │ (1)
            ┌───────────────────┼────────────────────┐
            │ (1)               │ (1)                │ (N)
 ┌──────────▼─────────┐ ┌───────▼────────┐ ┌─────────▼────────┐
 │ EncryptedCredential│ │  CachedSchema  │ │ ExecutionLogEntry│
 │  (Fernet at rest)  │ │ (tables + FKs) │ │ (query_id, sql)  │
 └────────────────────┘ └────────────────┘ └─────────▲────────┘
                                                      │ grounds
 ┌────────────────────┐ ┌────────────────┐ ┌─────────┴────────┐
 │  MetricDefinition  │ │     Trace      │ │  Reasoning Claim │
 │ (versioned formula)│ │ (tool_calls)   │ │ (supporting_ids) │
 └────────────────────┘ └────────────────┘ └──────────────────┘
```

### Key Models Explained:
*   **TenantConnection**: A registered target database, persisted *only after* privilege detection confirms it is safe (read-only). Carries `tenant_id` for strict isolation.
*   **EncryptedCredential**: Fernet-encrypted credential blob plus a key label. Decryption is tenant-scoped; there is deliberately no "dump all" path that could leak plaintext into a prompt.
*   **CachedSchema**: Introspected `information_schema` structure (tables, columns, foreign keys) versioned per connection, feeding SQL generation without re-hitting the target DB each turn.
*   **MetricDefinition**: Versioned business metrics (`name`, `formula`, `condition`, `grain`). New versions supersede old ones so resolution is deterministic and auditable.
*   **ExecutionLogEntry**: One row per executed query with a unique `query_id`, exact SQL, row count, truncation flag, and latency — the anchor for grounding and "supporting queries".
*   **Trace**: Per-run observability record (question, generated SQL, ordered tool calls, latency, cost), written best-effort so tracing never blocks answering.

---

## 🛡️ Safety & Query Pipeline Flow

This is the heart of the project. A question becomes an answer only by passing through deterministic gates — the model gets a vote on *what to propose*, never on *what runs*.

```
[NL Question] ──► Schema Context ──► Semantic Resolution ──► SQL Generation (LLM)
                                                                    │
                                                                    ▼
                                              ┌──────────────────────────────────┐
                                              │   ⛔ DETERMINISTIC SAFETY GATE    │
                                              │   1. sqlglot parse                │
                                              │   2. SELECT-only allowlist        │
                                              │   3. blocked-column scan          │
                                              │   4. reject oversized LIMIT       │
                                              │   5. inject row cap if absent     │
                                              └───────────────┬──────────────────┘
                                       reject  │              │  approve
                                ┌──────────────┘              └───────────────┐
                                ▼                                             ▼
                   [Rejection · NO execution]              [Preview?] ──await──► [Halt for confirm]
                                                                 │ run / confirmed
                                                                 ▼
                                                    Safe Executor (read-only role,
                                                    statement timeout, row cap,
                                                    audit log entry + query_id)
                                                                 │
                                                                 ▼
                              Analytics+Charts ──► Reasoning+Recommendations ──► Grounding Filter
                                                                                       │
                                                                                       ▼
                                                                  [Grounded consultant answer]
```

### Invariants enforced by code (not prompts):
1.  **`safety_gate` calls only `SafetyLayer.validate()`** — never an LLM. A rejected query short-circuits before the executor is constructed.
2.  **`SafetyLayer.validate()` is pure** — no DB, no model, no side effects; identical input always yields an identical decision.
3.  **`grounding_filter` suppresses unbacked claims** — a claim survives only if it carries at least one supporting `query_id`.

---

## 🤖 AI Pipeline (Consultant Reasoning Chain)

TallyAI does not stop at "here's a number." It answers the way an analyst would.

```
"Why did revenue drop last month?"
        │
        ▼
Semantic Resolution ──► canonical `revenue`, `churn_rate`, `new_subscriptions` formulas
        │
        ▼
SQL Generation (LLM) ──► Safety Gate ──► Read-only Execution ──► Results + query_id
        │
        ▼
Analytics ──► trend deltas, breakdowns, chart payloads
        │
        ▼
Reasoning ──► facts (grounded) | interpretation | correlation flags | confidence/coverage
        │
        ▼
Recommendations ──► hypotheses & next actions (never blind commands)
```

### Example consultant-style answer:
> **Revenue dropped 18%.** *(grounded → Query #a1f3)*
> **Primary drivers:** 31% fewer new subscriptions; 14% higher churn; mobile conversion fell 5.2% → 3.7%.
> **Recommended actions:** investigate the onboarding funnel; analyze mobile checkout logs; run a retention campaign for inactive users.
> *Confidence: medium · Coverage: full · Correlation ≠ causation flagged.*

Every number above links back to the exact query in the Execution Log that produced it. Numbers without a backing query are structurally suppressed before they ever reach the user.

---

## 🔌 MCP-Ready Tool Boundary

The architecture treats the LangGraph graph as the **brain** and trusted, auditable functions as the **hands**. These tool functions — `get_schema`, `run_query`, `resolve_metrics` — are designed to refactor cleanly into an **MCP (Model Context Protocol)** server without moving the security boundary.

```
        LangGraph "Brain"                     Trusted Tool Layer ("Hands")
 ┌──────────────────────────┐         ┌───────────────────────────────────────┐
 │  sql_generation (LLM)    │         │  get_schema(connection_id)             │
 │  reasoning (LLM)         │ ──tool─►│  resolve_metrics(question)             │
 │  deterministic routers   │  calls  │  run_query(sql)                        │
 │                          │         │   └─► ⛔ SafetyLayer.validate() RUNS   │
 │                          │         │        IN-PROCESS before execution     │
 └──────────────────────────┘         └───────────────────────────────────────┘
```

**Critical design rule:** even when `run_query` is exposed as an MCP tool, `SafetyLayer.validate()` executes as in-process, deterministic code *inside* the trusted tool — it is never delegated to the model or a remote endpoint. The security boundary travels with the tool, never into a prompt.

---

## 🖥️ Thin-Client Frontend

The Next.js UI is a deliberately replaceable client. The trust boundary is the FastAPI layer, so swapping frontends never weakens security.

```
        Next.js 16 App Router (Workspace)
 ┌─────────────────────────────────────────────┐
 │  /workspace/ask          Ask a question      │
 │  /workspace/dashboard    KPIs + charts       │
 │  /workspace/insights     Consultant answers  │
 │  /workspace/connections  Manage DB sources   │
 │  /workspace/schema       Browse cached schema│
 │  /workspace/metrics      Semantic metric defs│
 │  /workspace/history      Past runs + queries │
 │  /workspace/eval         Accuracy harness    │
 └───────────────────────┬─────────────────────┘
                         │  Typed API seam (src/types/tallyai.ts)
                         ▼
         API Client ── mock adapter | http adapter
        (toggle via NEXT_PUBLIC_USE_MOCK)
```

A `NEXT_PUBLIC_USE_MOCK` toggle lets the UI run fully against in-repo mock data (great for design work and demos) or against the live FastAPI backend — without changing a single component.

---

## 📂 Project Structure

```text
mcpApps/
├── app/                          # Next.js App Router (thin client)
│   ├── layout.tsx                # Root layout + providers
│   ├── page.tsx                  # Landing page
│   └── workspace/                # Authenticated workspace surface
│       ├── ask/                  # Natural-language question entry
│       ├── dashboard/            # KPIs, charts, summaries
│       ├── insights/             # Consultant-style grounded answers
│       ├── connections/          # Database connection management
│       ├── schema/               # Cached schema browser
│       ├── metrics/              # Semantic metric definitions
│       ├── history/              # Run history + supporting queries
│       └── eval/                 # NL→SQL evaluation harness UI
├── src/
│   ├── types/tallyai.ts        # Single source of truth API contract
│   ├── lib/api/                  # API client + mock/http adapters
│   │   ├── client.ts             # Adapter selection
│   │   ├── http-adapter.ts       # Live FastAPI backend calls
│   │   └── mock.ts               # In-repo mock backend
│   ├── components/workspace/     # Workspace UI components
│   ├── contexts/ · hooks/        # Demo context, data hooks
├── backend/
│   └── tallyai/
│       ├── core/
│       │   ├── safety.py         # ⛔ Deterministic safety gate (pure fn)
│       │   ├── orchestrator.py   # LangGraph StateGraph + routers + tracing
│       │   └── semantic_layer.py # Versioned metric resolution
│       ├── services/
│       │   ├── connection_manager.py   # Privilege detection
│       │   ├── credential_store.py     # Fernet encryption at rest
│       │   ├── schema_introspector.py  # information_schema → CachedSchema
│       │   ├── query_executor.py       # Safe, capped, audited execution
│       │   ├── nl_translator.py        # NL → candidate SQL (LLM)
│       │   ├── explainer.py            # Plain-language query explanations
│       │   ├── reasoning_layer.py      # Facts / interpretation / actions
│       │   ├── analytics.py            # Chart + summary + insights
│       │   ├── execution_log.py        # query_id audit log writer
│       │   ├── query_history.py        # Persisted run history
│       │   └── eval_harness.py         # Accuracy evaluation scaffold
│       ├── api/                  # FastAPI routers (connections, runs,
│       │                         #   schema, metrics, eval, stream)
│       ├── db/                   # SQLAlchemy models + async session
│       └── main.py               # FastAPI app entry point
├── backend/tests/                # 156+ pytest tests (incl. Hypothesis PBT)
├── package.json                  # Frontend dependencies + scripts
└── README.md
```

---

## 🛠️ Installation & Setup

### 1. Prerequisites
*   Node.js (v18.0.0 or higher)
*   Python 3.11+
*   PostgreSQL (a target database to query; a read-only role is strongly recommended)

### 2. Clone the Repository
```bash
git clone <your-repo-url> mcpApps
cd mcpApps
```

### 3. Backend Setup (FastAPI + LangGraph)
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
```

### 4. Run the Backend
```bash
uvicorn tallyai.main:app --reload
```
The API serves at [http://localhost:8000](http://localhost:8000) (docs at `/docs`).

### 5. Frontend Setup (Next.js)
```bash
cd ..
npm install
npm run dev
```
The UI runs at [http://localhost:3000](http://localhost:3000). It starts in mock mode by default — set `NEXT_PUBLIC_USE_MOCK=false` to talk to the live backend.

### 6. Run the Test Suite
```bash
cd backend
pytest
```

---

## 📄 Environment Variables

### Backend (`backend/.env`)
```env
# App database (SQLAlchemy) — async driver required
DATABASE_URL="postgresql+asyncpg://user:password@host:5432/tallyai"

# Credential encryption (Fernet key derivation) — set a strong value
SECRET_KEY="generate-a-long-random-string"

# LLM provider (choose one; required for live NL→SQL & reasoning)
OPENAI_API_KEY="sk-..."
# or
ANTHROPIC_API_KEY="sk-ant-..."
```

### Frontend (`.env.local`)
```env
# Toggle between in-repo mock data and the live FastAPI backend
NEXT_PUBLIC_USE_MOCK="true"

# Backend base URL (used when mock mode is off)
NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
```

> **Note:** Target database credentials are **not** placed in env files. They are submitted through the Connections flow, validated by privilege detection, and stored Fernet-encrypted at rest.

---

## 🧪 Testing & Correctness

Correctness is treated as a first-class design artifact, not an afterthought.

*   **156+ tests passing** across unit, integration, and property-based suites.
*   **Property-based testing (Hypothesis)** locks down the safety-layer invariants — e.g. *no non-SELECT statement is ever approved*, *an approved query always carries a row cap* — across generated inputs.
*   **Orchestrator integration tests** prove the design-critical flows: happy-path SELECT, non-SELECT rejected before the executor, preview-halts-until-confirm, translation-failure-returns-message, and unbacked-claim suppression.
*   **Multi-tenant isolation tests** verify cross-tenant credential and data access is refused.

### Honest caveats (transparency over polish)
*   **Live NL→SQL accuracy** has not been measured end-to-end — that requires a configured LLM API key and the eval harness run against a seeded database.
*   **Integration tests run against in-memory SQLite**; PostgreSQL-specific behaviors are mocked. A disposable seeded Postgres (via Docker) is the recommended next validation step.

---

## 🔮 Future Improvements

- [ ] **Full MCP Server**: Promote the trusted tool functions into a standalone MCP server (`get_schema`, `run_query`, `resolve_metrics`) consumed via `MultiServerMCPClient`, keeping `SafetyLayer.validate()` strictly in-process.
- [ ] **Live Accuracy Benchmark**: Wire an LLM key and run the eval harness against a seeded Postgres to publish a real NL→SQL accuracy number against the ≥85% target.
- [ ] **Dockerized Postgres Validation**: Ship a disposable, seeded, read-only Postgres via `docker-compose` to exercise Postgres-specific behavior in CI.
- [ ] **Vector Schema Retrieval**: Add optional embedding-based schema retrieval (Qdrant) for very large databases where the full schema won't fit in context.
- [ ] **Multi-Agent Specialization**: Split `sql_generation` and `reasoning_recommendations` into specialized agents — additively, without moving the security boundary.

---

## 🎖️ Why This Project Matters (Recruiter Corner)

TallyAI is not a "chat with your database" toy. It is a study in **building trustworthy AI systems where the model is powerful but never in charge of safety**:

1.  **Security-First AI Architecture**: The deterministic safety gate — `sqlglot` parse, SELECT allowlist, row caps, credential-column blocking — is non-model code, property-tested, and impossible for the LLM to bypass. This is the single most important design decision and it is enforced structurally.
2.  **Grounded, Auditable Output**: Every claim is bound to a `query_id` and unbacked claims are suppressed by deterministic code. The system is honest by construction, not by prompt.
3.  **Clean Orchestration & Tool Boundaries**: A LangGraph `StateGraph` with deterministic routing, MCP-ready tool seams, and best-effort tracing demonstrates production-minded orchestration rather than a single mega-prompt.
4.  **Pragmatic Engineering Judgment**: Read-only roles, encrypted credentials, multi-tenant isolation, a pluggable thin client, and *transparent caveats* about what has and hasn't been validated — the kind of judgment that separates demos from systems.

---
*Built with 🧭 to make databases speak business — safely.*
