"""
Tests for execution-based SQL equivalence (tallyai.services.eval_execution).

The headline test replays the *actual* SQL that Gemini 2.5 Flash produced on the
golden set (captured from a live run) and shows that result-set comparison
correctly scores the cosmetic differences as matches while still catching the
one genuine semantic miss — lifting measured accuracy from 58% (string match) to
~92% (execution match) without changing the model.
"""

import pytest

from tallyai.services.eval_execution import (
    build_seed_connection,
    make_comparator,
    results_equivalent,
)

# --- Golden expected SQL (subset, verbatim from eval_golden_set.json) ---------
EXPECTED = {
    "revenue_total": "SELECT SUM(amount) FROM payments WHERE status = 'completed'",
    "revenue_by_month": "SELECT date_trunc('month', created_at) AS month, SUM(amount) AS revenue FROM payments WHERE status = 'completed' GROUP BY 1 ORDER BY 1",
    "mrr_current": "SELECT SUM(monthly_amount) FROM subscriptions WHERE status = 'active'",
    "active_users_30d": "SELECT COUNT(DISTINCT id) FROM users WHERE last_login >= NOW() - INTERVAL '30 days'",
    "new_customers_this_month": "SELECT COUNT(*) FROM customers WHERE created_at >= date_trunc('month', NOW())",
    "churn_rate": "SELECT COUNT(CASE WHEN status = 'canceled' THEN 1 END)::float / NULLIF(COUNT(*), 0) FROM subscriptions",
    "ltv_average": "SELECT AVG(total_spend) FROM customers",
    "top_customers_by_revenue": "SELECT customer_id, SUM(amount) AS revenue FROM payments WHERE status = 'completed' GROUP BY customer_id ORDER BY revenue DESC LIMIT 10",
    "active_subscriptions_count": "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'",
    "revenue_by_plan": "SELECT plan, SUM(amount) AS revenue FROM payments WHERE status = 'completed' GROUP BY plan ORDER BY revenue DESC",
    "failed_payments_count": "SELECT COUNT(*) FROM payments WHERE status = 'failed'",
    "trials_converted": "SELECT COUNT(*) FROM subscriptions WHERE status = 'active' AND trial_converted = true",
}

# --- Actual SQL produced by Gemini 2.5 Flash on the live run ------------------
# The 7 string-match passes are reproduced as-generated; the 5 string-match
# "failures" are the verbatim model outputs that the old exact-match scored 0.
GENERATED = {
    # exact-match passes
    "revenue_total": "SELECT SUM(amount) FROM payments WHERE status = 'completed'",
    "mrr_current": "SELECT SUM(monthly_amount) FROM subscriptions WHERE status = 'active'",
    "active_users_30d": "SELECT COUNT(DISTINCT id) FROM users WHERE last_login >= NOW() - INTERVAL '30 days'",
    "churn_rate": "SELECT COUNT(CASE WHEN status = 'canceled' THEN 1 END)::float / NULLIF(COUNT(*), 0) FROM subscriptions",
    "ltv_average": "SELECT AVG(total_spend) FROM customers",
    "top_customers_by_revenue": "SELECT customer_id, SUM(amount) AS revenue FROM payments WHERE status = 'completed' GROUP BY customer_id ORDER BY revenue DESC LIMIT 10",
    "failed_payments_count": "SELECT COUNT(*) FROM payments WHERE status = 'failed'",
    # string-match "failures" that are actually correct (cosmetic differences)
    "revenue_by_month": "SELECT DATE_TRUNC('month', created_at) AS month, SUM(amount) AS total_revenue FROM payments WHERE status = 'completed' GROUP BY DATE_TRUNC('month', created_at) ORDER BY month",
    "new_customers_this_month": "SELECT COUNT(id) FROM customers WHERE created_at >= date_trunc('month', NOW()) AND created_at < date_trunc('month', NOW()) + INTERVAL '1 month'",
    "active_subscriptions_count": "SELECT COUNT(id) FROM subscriptions WHERE status = 'active'",
    "revenue_by_plan": "SELECT plan, SUM(amount) AS revenue FROM payments WHERE status = 'completed' GROUP BY plan",
    # the one GENUINE semantic miss: drops the status = 'active' filter
    "trials_converted": "SELECT COUNT(CASE WHEN trial_converted = TRUE THEN 1 END) FROM subscriptions",
}

# Expected verdict of execution-based comparison for each pair.
EXPECTED_EQUIVALENCE = {
    "revenue_total": True,
    "revenue_by_month": True,            # alias + GROUP BY expression vs positional
    "mrr_current": True,
    "active_users_30d": True,
    "new_customers_this_month": True,    # extra upper bound, same rows
    "churn_rate": True,
    "ltv_average": True,
    "top_customers_by_revenue": True,
    "active_subscriptions_count": True,  # COUNT(id) vs COUNT(*)
    "revenue_by_plan": True,             # missing ORDER BY, same multiset
    "failed_payments_count": True,
    "trials_converted": False,           # genuinely different result
}


@pytest.fixture()
def conn():
    c = build_seed_connection()
    yield c
    c.close()


@pytest.mark.parametrize("pair_id", list(EXPECTED.keys()))
def test_execution_equivalence_per_pair(conn, pair_id):
    verdict = results_equivalent(EXPECTED[pair_id], GENERATED[pair_id], conn=conn)
    assert verdict is EXPECTED_EQUIVALENCE[pair_id], (
        f"{pair_id}: expected equivalence={EXPECTED_EQUIVALENCE[pair_id]}, got {verdict}"
    )


def test_execution_accuracy_meets_target():
    """The captured live outputs reach >= 85% under execution-based scoring."""
    compare = make_comparator()
    matched = sum(
        1 for pid in EXPECTED if compare(EXPECTED[pid], GENERATED[pid])
    )
    accuracy = matched / len(EXPECTED)
    assert accuracy >= 0.85, f"execution accuracy {accuracy:.1%} < 85%"
    # Exactly the one genuine miss should remain.
    assert matched == len(EXPECTED) - 1


def test_none_generated_is_not_equivalent(conn):
    assert results_equivalent("SELECT 1", None, conn=conn) is False


def test_clearly_wrong_query_is_not_equivalent(conn):
    # Wrong table/aggregate must not be scored equivalent.
    assert results_equivalent(
        "SELECT COUNT(*) FROM payments WHERE status = 'completed'",
        "SELECT COUNT(*) FROM users",
        conn=conn,
    ) is False


def test_alias_and_order_insensitive(conn):
    assert results_equivalent(
        "SELECT plan, SUM(amount) AS revenue FROM payments WHERE status = 'completed' GROUP BY plan ORDER BY revenue DESC",
        "SELECT plan AS p, SUM(amount) AS total FROM payments WHERE status = 'completed' GROUP BY plan",
        conn=conn,
    ) is True
