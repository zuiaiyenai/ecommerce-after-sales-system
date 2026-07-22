from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any


POLICY_SOURCE_TYPES = frozenset({"after_sales_policy", "refund_policy", "exchange_rule"})


@dataclass(frozen=True)
class FilterContext:
    merchant_code: str
    source_type: str | None
    policy_version: str | None
    as_of_time: datetime
    product_category: str | None
    scene: str | None
    intent: str | None


@dataclass(frozen=True)
class FilterPlan:
    level: str
    merchant_code: str
    source_type: str | None
    policy_version: str | None
    as_of_time: datetime
    product_category: str | None
    scene: str | None
    intent: str | None
    trusted_policy_eligible: bool


def build_filter_plans(ctx: FilterContext) -> list[FilterPlan]:
    strict = FilterPlan(
        level="strict",
        merchant_code=ctx.merchant_code,
        source_type=ctx.source_type,
        policy_version=ctx.policy_version,
        as_of_time=ctx.as_of_time,
        product_category=ctx.product_category,
        scene=ctx.scene,
        intent=ctx.intent,
        trusted_policy_eligible=True,
    )
    plans = [strict]
    if ctx.product_category is not None:
        plans.append(replace(strict, level="category_relaxed", product_category=None, trusted_policy_eligible=False))
    if ctx.scene is not None:
        plans.append(replace(strict, level="scene_relaxed", scene=None, trusted_policy_eligible=False))
    if ctx.product_category is not None and ctx.scene is not None:
        plans.append(
            replace(
                strict,
                level="category_and_scene_relaxed",
                product_category=None,
                scene=None,
                trusted_policy_eligible=False,
            )
        )
    if ctx.intent is not None and ctx.source_type not in POLICY_SOURCE_TYPES:
        plans.append(replace(strict, level="intent_relaxed", intent=None, trusted_policy_eligible=False))
    return plans


def build_hard_filter_sql(plan: FilterPlan) -> tuple[str, list[Any]]:
    """Return the single hard-filter contract shared by every retrieval channel."""
    sql = """
        kd.status = 1
        AND COALESCE(kd.metadata ->> 'deleted', 'false') <> 'true'
        AND kd.published_revision IS NOT NULL
        AND kc.revision = kd.published_revision
        AND kd.merchant_code IN (%s, 'GLOBAL')
        AND (%s IS NULL OR kd.source_type = %s)
        AND (%s IS NULL OR kd.policy_version = %s)
        AND (kd.valid_from IS NULL OR kd.valid_from <= %s)
        AND (kd.valid_to IS NULL OR %s < kd.valid_to)
        AND (%s IS NULL OR kc.product_categories = '{}' OR %s = ANY(kc.product_categories))
        AND (%s IS NULL OR kc.scenes = '{}' OR %s = ANY(kc.scenes))
        AND (%s IS NULL OR kc.intents = '{}' OR %s = ANY(kc.intents))
    """.strip()
    params: list[Any] = [
        plan.merchant_code,
        plan.source_type,
        plan.source_type,
        plan.policy_version,
        plan.policy_version,
        plan.as_of_time,
        plan.as_of_time,
        plan.product_category,
        plan.product_category,
        plan.scene,
        plan.scene,
        plan.intent,
        plan.intent,
    ]
    return sql, params
