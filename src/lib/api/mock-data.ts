import type {
  AskFixtures,
  CachedSchema,
  Connection,
  DashboardData,
  EvalReport,
  HistoryItem,
  Insight,
  MetricDefinition,
  SavedQuery,
} from "@/types/tallyai";

/* ── Connections ───────────────────────────────────── */
export const mockConnections: Connection[] = [
  { id: "prod", name: "production_db", engine: "PostgreSQL 15", host: "db.acme.com:5432", status: "Connected", readOnly: true },
  { id: "staging", name: "staging_db", engine: "PostgreSQL 15", host: "staging.acme.com:5432", status: "Connected", readOnly: true },
  { id: "warehouse", name: "analytics_warehouse", engine: "Snowflake", host: "acme.snowflakecomputing.com", status: "Connected", readOnly: true },
];

/* ── Ask fixtures ──────────────────────────────────── */
export const mockAskFixtures: AskFixtures = {
  seedAnswer: {
    question: "What was our top revenue product last quarter?",
    sql: `SELECT
  p.name AS product_name,
  SUM(oi.quantity * oi.unit_price) AS revenue
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.status = 'paid'
  AND o.created_at BETWEEN '2026-01-01' AND '2026-03-31'
GROUP BY p.name
ORDER BY revenue DESC
LIMIT 5;`,
    explanation:
      "Sums paid order revenue per product for Q1 2026 and returns the top five. Uses the canonical 'revenue' metric, which excludes refunds and tax.",
    metrics: ["revenue"],
    steps: [],
    chart: [
      { label: "Atlas Pro", value: 84200 },
      { label: "Orbit Mini", value: 62100 },
      { label: "Lumen Kit", value: 48700 },
      { label: "Nimbus", value: 31900 },
      { label: "Vector One", value: 22400 },
    ],
    table: {
      columns: ["product_name", "revenue"],
      rows: [
        ["Atlas Pro", "$84,200"],
        ["Orbit Mini", "$62,100"],
        ["Lumen Kit", "$48,700"],
        ["Nimbus", "$31,900"],
        ["Vector One", "$22,400"],
      ],
    },
    summaryParts: [
      { type: "text", text: "Atlas Pro led Q1 with " },
      { type: "chip", label: "Atlas Pro Q1 revenue", value: "$84,200", queryId: "q1" },
      { type: "text", text: " in revenue, " },
      { type: "chip", label: "Atlas vs Orbit delta", value: "+35%", queryId: "q2" },
      { type: "text", text: " ahead of Orbit Mini. The top 3 SKUs accounted for " },
      { type: "chip", label: "Top-3 concentration", value: "75%", queryId: "q3" },
      { type: "text", text: " of paid product revenue." },
    ],
    facts: [
      "Atlas Pro generated $84,200 across 612 paid orders.",
      "Orbit Mini was the largest mover, growing 28% QoQ.",
      "5 SKUs make up 96% of paid revenue this quarter.",
    ],
    hypotheses: [
      {
        title: "Atlas Pro's lead is being driven by enterprise renewals",
        body: "84% of Atlas Pro orders this quarter came from accounts older than 12 months on the Enterprise plan.",
        confidence: "high",
        coverage: "612 / 612 orders analyzed",
        chips: [{ label: "Enterprise share", value: "84%", queryId: "q4" }],
      },
      {
        title: "Orbit Mini growth correlates with the new ads campaign",
        body: "Orbit Mini orders spiked the week the 'Ship-fast' ads launched, then plateaued. Worth A/B testing the next flight.",
        confidence: "medium",
        coverage: "Last 8 weeks",
        correlation: true,
        chips: [{ label: "Week-over-week lift", value: "+22%", queryId: "q5" }],
      },
    ],
  },
  supportingQueries: [
    {
      id: "q1",
      label: "Atlas Pro Q1 revenue",
      sql: "SELECT SUM(oi.quantity * oi.unit_price)\nFROM order_items oi\nJOIN products p ON p.id = oi.product_id\nJOIN orders o ON o.id = oi.order_id\nWHERE p.name = 'Atlas Pro' AND o.status = 'paid'\n  AND o.created_at BETWEEN '2026-01-01' AND '2026-03-31';",
      params: { quarter: "2026-Q1" },
      timestamp: "2 min ago",
      latencyMs: 96,
    },
    {
      id: "q2",
      label: "Atlas vs Orbit delta",
      sql: "WITH q1 AS (\n  SELECT p.name, SUM(oi.quantity*oi.unit_price) rev\n  FROM order_items oi JOIN products p ON p.id = oi.product_id\n  JOIN orders o ON o.id = oi.order_id\n  WHERE o.status = 'paid'\n    AND o.created_at BETWEEN '2026-01-01' AND '2026-03-31'\n  GROUP BY p.name\n) SELECT (a.rev - b.rev) / b.rev FROM q1 a, q1 b\nWHERE a.name = 'Atlas Pro' AND b.name = 'Orbit Mini';",
      timestamp: "2 min ago",
      latencyMs: 142,
    },
    { id: "q3", label: "Top-3 concentration", sql: "SELECT SUM(top3) / SUM(all_rev) FROM ...;", timestamp: "2 min ago", latencyMs: 71 },
    { id: "q4", label: "Enterprise share of Atlas Pro", sql: "SELECT COUNT(*) FILTER (WHERE plan='enterprise')::float / COUNT(*) FROM atlas_orders;", timestamp: "2 min ago", latencyMs: 53 },
    { id: "q5", label: "Orbit Mini WoW lift", sql: "SELECT week, SUM(orders) FROM weekly_orders WHERE product='Orbit Mini' ORDER BY week;", timestamp: "2 min ago", latencyMs: 88 },
  ],
  suggestions: [
    { label: "MRR trend this year", kind: "normal" },
    { label: "Delete inactive users from 2023", kind: "blocked" },
    { label: "Revenue by region for Antarctica", kind: "insufficient" },
    { label: "Full-table scan of event_log", kind: "timeout" },
  ],
};

/* ── Schema ────────────────────────────────────────── */
export const mockSchema: CachedSchema = {
  connectionId: "prod",
  schemaVersion: "v12",
  lastIntrospected: "12 min ago",
  tables: [
    { name: "users", rows: "18,402", columns: [
      { name: "id", type: "uuid", pk: true },
      { name: "email", type: "text" },
      { name: "name", type: "text" },
      { name: "created_at", type: "timestamptz" },
    ]},
    { name: "orders", rows: "247,891", columns: [
      { name: "id", type: "uuid", pk: true },
      { name: "user_id", type: "uuid", fk: "users.id" },
      { name: "status", type: "text" },
      { name: "total_cents", type: "bigint" },
      { name: "created_at", type: "timestamptz" },
    ]},
    { name: "order_items", rows: "619,402", columns: [
      { name: "id", type: "uuid", pk: true },
      { name: "order_id", type: "uuid", fk: "orders.id" },
      { name: "product_id", type: "uuid", fk: "products.id" },
      { name: "quantity", type: "int" },
      { name: "unit_price", type: "numeric" },
    ]},
    { name: "products", rows: "1,204", columns: [
      { name: "id", type: "uuid", pk: true },
      { name: "name", type: "text" },
      { name: "sku", type: "text" },
      { name: "category", type: "text" },
    ]},
    { name: "subscriptions", rows: "9,847", columns: [
      { name: "id", type: "uuid", pk: true },
      { name: "user_id", type: "uuid", fk: "users.id" },
      { name: "plan", type: "text" },
      { name: "status", type: "text" },
    ]},
  ],
};

/* ── Metrics ───────────────────────────────────────── */
export const mockMetrics: MetricDefinition[] = [
  { name: "revenue", description: "Sum of paid invoice totals", formula: "SUM(invoice.total)", condition: "invoice.status = 'paid'", grain: "day", version: 3, history: [
    { version: 3, createdAt: "Jun 18, 2026", formula: "SUM(invoice.total)" },
    { version: 2, createdAt: "Mar 04, 2026", formula: "SUM(invoice.amount)" },
    { version: 1, createdAt: "Jan 11, 2026", formula: "SUM(order.total)" },
  ]},
  { name: "mrr", description: "Monthly recurring revenue from active subscriptions", formula: "SUM(subscription.monthly_amount)", condition: "subscription.status = 'active'", grain: "month", version: 2, history: [
    { version: 2, createdAt: "May 02, 2026", formula: "SUM(subscription.monthly_amount)" },
    { version: 1, createdAt: "Feb 14, 2026", formula: "SUM(subscription.amount) / 12" },
  ]},
  { name: "churn_rate", description: "Cancellations / active subscribers in period", formula: "cancelled / active_start", grain: "month", version: 1, history: [
    { version: 1, createdAt: "Jan 22, 2026", formula: "cancelled / active_start" },
  ]},
];

/* ── History ───────────────────────────────────────── */
export const mockHistory: HistoryItem[] = [
  { q: "What was our top revenue product last quarter?", conn: "production_db", time: "2 hours ago", rows: 5, ms: 142, queries: 5 },
  { q: "Monthly active users trend over the past year", conn: "production_db", time: "Yesterday", rows: 12, ms: 87, queries: 1 },
  { q: "List customers with no orders in 90 days", conn: "production_db", time: "Yesterday", rows: 84, ms: 213, queries: 2 },
  { q: "Average order value by region", conn: "analytics_warehouse", time: "2 days ago", rows: 7, ms: 65, queries: 3 },
  { q: "Failed signups in last 7 days grouped by source", conn: "production_db", time: "3 days ago", rows: 23, ms: 198, queries: 1 },
  { q: "Top 10 customers by ARR", conn: "analytics_warehouse", time: "4 days ago", rows: 10, ms: 51, queries: 2 },
  { q: "Refund rate by SKU", conn: "production_db", time: "Last week", rows: 42, ms: 612, queries: 4 },
];

/* ── Eval ──────────────────────────────────────────── */
export const mockEval: EvalReport = {
  labeledCount: 248,
  currentAccuracy: 97.4,
  deltaPp: 0.6,
  history: [
    { run: "v2026.06.20", score: 97.4, examples: 248 },
    { run: "v2026.06.13", score: 96.8, examples: 248 },
    { run: "v2026.06.06", score: 96.1, examples: 240 },
    { run: "v2026.05.30", score: 95.4, examples: 232 },
  ],
  stats: [
    { label: "Queries (24h)", value: "1,247" },
    { label: "Avg latency", value: "184 ms" },
    { label: "Errors", value: "12" },
    { label: "Spend (24h)", value: "$2.41" },
  ],
  traces: [
    { q: "Revenue by month", sql: "SELECT ...", tools: ["resolve_metric", "execute_sql"], latencyMs: 412, costUsd: 0.0048, status: "ok" },
    { q: "Top customers in EU", sql: "SELECT ...", tools: ["resolve_metric", "execute_sql"], latencyMs: 538, costUsd: 0.0061, status: "ok" },
    { q: "Refund rate by SKU", sql: "SELECT ...", tools: ["resolve_metric", "safety_check", "execute_sql"], latencyMs: 912, costUsd: 0.0094, status: "warn" },
    { q: "MAU last 90 days", sql: "SELECT ...", tools: ["execute_sql"], latencyMs: 287, costUsd: 0.0033, status: "ok" },
    { q: "Drop users last login", sql: "DELETE ...", tools: ["safety_check"], latencyMs: 41, costUsd: 0.0009, status: "blocked" },
  ],
};

/* ── Dashboard ─────────────────────────────────────── */
export const mockDashboard: DashboardData = {
  metrics: [
    { id: "rev", label: "Revenue", value: "$248,930", period: "Last 30 days", delta: "+12.4%", trend: "up", queryId: "qrev" },
    { id: "mrr", label: "MRR", value: "$78,420", period: "Current", delta: "+4.1%", trend: "up", queryId: "qmrr" },
    { id: "users", label: "Active users", value: "18,402", period: "Last 30 days", delta: "+3.1%", trend: "up", queryId: "qmau" },
    { id: "churn", label: "Churn rate", value: "2.8%", period: "Last 30 days", delta: "+0.4%", trend: "down", queryId: "qchurn" },
  ],
  attention: [
    { title: "Churn spiked in the mid-market segment", tag: "Anomaly", time: "1h ago" },
    { title: "Atlas Pro renewals are 12% under forecast", tag: "Risk", time: "3h ago" },
    { title: "Signups from EU dropped 18% week-over-week", tag: "Drop", time: "Yesterday" },
  ],
  recent: [
    { q: "What was our top revenue product last quarter?", who: "Demo Admin", time: "2 min ago" },
    { q: "Monthly active users trend over the past year", who: "Demo Admin", time: "1h ago" },
    { q: "List customers with no orders in 90 days", who: "Demo Admin", time: "Yesterday" },
    { q: "Average order value by region", who: "Demo Admin", time: "2 days ago" },
  ],
  supportingQueries: [
    { id: "qrev", label: "Revenue (30-day window)", sql: "SELECT revenue FROM semantic_metrics WHERE window = '30d';", timestamp: "just now", latencyMs: 64 },
    { id: "qmrr", label: "MRR (current)", sql: "SELECT mrr FROM semantic_metrics WHERE window = 'current';", timestamp: "just now", latencyMs: 58 },
    { id: "qmau", label: "Active users (30-day window)", sql: "SELECT active_users FROM semantic_metrics WHERE window = '30d';", timestamp: "just now", latencyMs: 71 },
    { id: "qchurn", label: "Churn rate (30-day window)", sql: "SELECT churn_rate FROM semantic_metrics WHERE window = '30d';", timestamp: "just now", latencyMs: 66 },
  ],
};

/* ── Insights & saved ──────────────────────────────── */
export const mockInsights: Insight[] = [
  { title: "Revenue concentration risk", body: "Top 3 customers account for 42% of revenue, up from 28% a year ago.", tag: "Risk", schedule: "Weekly · Mon 9am" },
  { title: "Churn spike in mid-market segment", body: "Cancellations among $1k-$5k MRR accounts rose 18% this month.", tag: "Anomaly", schedule: "Daily · 8am" },
  { title: "Underpriced power users", body: "12% of free users exceed paid plan limits. ~$48K ARR opportunity.", tag: "Opportunity", schedule: null },
  { title: "Weekly executive snapshot", body: "Revenue, MRR, churn, NPS, top open issues.", tag: "Report", schedule: "Weekly · Fri 4pm" },
];

export const mockSaved: SavedQuery[] = [
  { name: "Daily revenue", folder: "Finance", last: "Today" },
  { name: "Weekly active users", folder: "Product", last: "Yesterday" },
  { name: "Top 10 customers by ARR", folder: "Sales", last: "2 days ago" },
  { name: "Failed payments last 24h", folder: "Ops", last: "Today" },
  { name: "New signups by source", folder: "Growth", last: "Yesterday" },
  { name: "Net Promoter Score by cohort", folder: "Product", last: "Last week" },
];
