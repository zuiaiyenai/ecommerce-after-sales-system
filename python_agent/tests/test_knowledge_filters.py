from __future__ import annotations

from datetime import datetime

from after_sales_agent.retrieval.knowledge_filters import (
    FilterContext,
    build_hard_filter_sql,
    build_filter_plans,
)


def test_hard_filters_never_relax_merchant_revision_or_validity() -> None:
    as_of_time = datetime(2026, 7, 21)
    plans = build_filter_plans(
        FilterContext(
            merchant_code="M1",
            source_type="after_sales_policy",
            policy_version="v2",
            as_of_time=as_of_time,
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
        )
    )

    assert all(plan.merchant_code == "M1" for plan in plans)
    assert all(plan.source_type == "after_sales_policy" for plan in plans)
    assert all(plan.policy_version == "v2" for plan in plans)
    assert all(plan.as_of_time == as_of_time for plan in plans)
    assert all(plan.intent == "refund" for plan in plans)


def test_non_policy_filter_plan_can_relax_intent_but_not_hard_dimensions() -> None:
    as_of_time = datetime(2026, 7, 21, 12, 30)
    plans = build_filter_plans(
        FilterContext(
            merchant_code="M1",
            source_type="faq",
            policy_version=None,
            as_of_time=as_of_time,
            product_category=None,
            scene=None,
            intent="refund",
        )
    )

    intent_relaxed = next(plan for plan in plans if plan.level == "intent_relaxed")
    assert intent_relaxed.intent is None
    assert intent_relaxed.merchant_code == "M1"
    assert intent_relaxed.source_type == "faq"
    assert intent_relaxed.as_of_time == as_of_time
    assert intent_relaxed.trusted_policy_eligible is False


def test_hard_filter_sql_enforces_published_revision_merchant_and_half_open_validity() -> None:
    as_of_time = datetime(2026, 7, 21, 12, 30)
    strict = build_filter_plans(
        FilterContext(
            merchant_code="M1",
            source_type="after_sales_policy",
            policy_version="v2",
            as_of_time=as_of_time,
            product_category="headphone",
            scene="quality_issue",
            intent="refund",
        )
    )[0]

    sql, params = build_hard_filter_sql(strict)

    assert "kd.status = 1" in sql
    assert "COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'" in sql
    assert "kd.published_revision IS NOT NULL" in sql
    assert "kc.revision = kd.published_revision" in sql
    assert "kd.merchant_code IN (%s, 'GLOBAL')" in sql
    assert "kd.valid_from IS NULL OR kd.valid_from <= %s" in sql
    assert "kd.valid_to IS NULL OR %s < kd.valid_to" in sql
    assert sql.count("%s::text IS NULL") == 5
    assert params.count(as_of_time) == 2
