from __future__ import annotations

import json

import pytest

from after_sales_agent.evaluation.rag_metrics import (
    Case,
    enforce_reliable_holdout_filter_gate,
    evaluate,
    load_cases,
)


def test_metrics_separate_recall_from_filter_safety() -> None:
    cases = [Case("c1", relevant_chunk_ids={"A"}, forbidden_merchant_codes={"M2"})]
    runs = {
        "c1": [
            {"chunk_id": "A", "merchant_code": "M1"},
            {"chunk_id": "X", "merchant_code": "M2"},
        ]
    }

    report = evaluate(cases, runs, k_values=(5, 20))

    assert report["recall_at_5"] == 1.0
    assert report["filter_violation_rate"] > 0


def test_no_answer_false_positive_rate_counts_answered_negative_cases() -> None:
    cases = [Case("n1", relevant_chunk_ids=set(), expect_no_answer=True)]

    report = evaluate(cases, {"n1": [{"chunk_id": "X"}]})

    assert report["no_answer_false_positive_rate"] == 1.0


def test_rank_latency_cost_and_rerank_uplift_are_reported() -> None:
    cases = [Case("c1", relevant_chunk_ids={"A", "B"})]
    rrf_runs = {
        "c1": {
            "hits": [{"chunk_id": "X"}, {"chunk_id": "A"}, {"chunk_id": "B"}],
            "latency_ms": 10,
        }
    }
    rerank_runs = {
        "c1": {
            "hits": [{"chunk_id": "A"}, {"chunk_id": "B"}],
            "latency_ms": 20,
            "rerank_cost": 0.002,
        }
    }

    report = evaluate(cases, rerank_runs, baseline_runs=rrf_runs)

    assert report["recall_at_5"] == 1.0
    assert report["mrr_at_10"] == 1.0
    assert report["ndcg_at_5"] == 1.0
    assert report["hit_rate_at_5"] == 1.0
    assert report["rerank_uplift"] > 0
    assert report["latency_ms"] == {"p50": 20.0, "p95": 20.0}
    assert report["average_rerank_cost"] == 0.002


def test_jsonl_contract_and_filter_gate_require_reliable_holdout(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    rows = [
        {
            "case_id": "smoke-1",
            "query": "口语化问题",
            "filters": {"merchant_code": "M1"},
            "relevant_chunk_ids": ["A"],
            "expect_no_answer": False,
            "forbidden_merchant_codes": ["M2"],
            "forbidden_policy_versions": ["v1"],
            "split": "smoke",
            "annotation_method": "legacy_smoke",
            "category": "colloquial",
        },
        {
            "case_id": "holdout-1",
            "query": "双人标注问题",
            "filters": {"merchant_code": "M1"},
            "relevant_chunk_ids": ["B"],
            "expect_no_answer": False,
            "forbidden_merchant_codes": ["M2"],
            "forbidden_policy_versions": ["v1"],
            "split": "holdout",
            "annotation_method": "dual_annotated",
            "category": "policy",
        },
    ]
    dataset.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    cases = load_cases(dataset)

    assert [case.case_id for case in cases] == ["smoke-1", "holdout-1"]
    assert not cases[0].is_reliable_holdout
    assert cases[1].is_reliable_holdout
    with pytest.raises(ValueError, match="filter_violation_rate"):
        enforce_reliable_holdout_filter_gate(
            cases,
            {"holdout-1": [{"chunk_id": "X", "merchant_code": "M2", "policy_version": "v2"}]},
        )


def test_jsonl_contract_rejects_holdout_without_reliable_annotation(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "bad-holdout",
                "query": "未可靠标注",
                "filters": {},
                "relevant_chunk_ids": ["A"],
                "expect_no_answer": False,
                "forbidden_merchant_codes": [],
                "forbidden_policy_versions": [],
                "split": "holdout",
                "annotation_method": "single_annotated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reliable annotation"):
        load_cases(dataset)


@pytest.mark.parametrize(
    ("forbidden_merchants", "forbidden_versions"),
    [([], ["v1"]), (["M2"], [])],
)
def test_reliable_holdout_requires_both_filter_safety_labels(
    tmp_path,
    forbidden_merchants,
    forbidden_versions,
) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "unsafe-holdout",
                "query": "安全标注不完整",
                "filters": {"merchant_code": "M1", "policy_version": "v2"},
                "relevant_chunk_ids": ["A"],
                "expect_no_answer": False,
                "forbidden_merchant_codes": forbidden_merchants,
                "forbidden_policy_versions": forbidden_versions,
                "split": "holdout",
                "annotation_method": "dual_annotated",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="merchant and policy-version safety labels"):
        load_cases(dataset)


def test_filter_gate_is_not_applicable_without_checked_hits() -> None:
    cases = [
        Case(
            "h1",
            relevant_chunk_ids={"A"},
            split="holdout",
            annotation_method="dual_annotated",
            forbidden_merchant_codes={"M2"},
            forbidden_policy_versions={"v1"},
        )
    ]

    gate = enforce_reliable_holdout_filter_gate(cases, {"h1": {"hits": []}})

    assert gate == {
        "status": "not_applicable",
        "reason": "no_filter_checked_hits",
        "case_count": 1,
        "filter_checked_hit_count": 0,
        "filter_metadata_missing_count": 0,
    }


def test_filter_gate_rejects_hits_missing_required_safety_metadata() -> None:
    cases = [
        Case(
            "h1",
            relevant_chunk_ids={"A"},
            split="holdout",
            annotation_method="adjudicated",
            forbidden_merchant_codes={"M2"},
            forbidden_policy_versions={"v1"},
        )
    ]

    with pytest.raises(ValueError, match="missing merchant_code or policy_version"):
        enforce_reliable_holdout_filter_gate(
            cases,
            {"h1": {"hits": [{"chunk_id": "A", "merchant_code": "M1"}]}},
        )
