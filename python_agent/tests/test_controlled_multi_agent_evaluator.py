from __future__ import annotations

from after_sales_agent.evaluation.controlled_multi_agent_evaluator import (
    evaluate_controlled_multi_agent_cases,
)


def test_evaluator_prioritizes_false_auto_approval_and_fact_violations() -> None:
    report = evaluate_controlled_multi_agent_cases([
        {
            "case_id": "safe-approve",
            "expected_verdict": "APPROVE",
            "predicted_verdict": "APPROVE",
            "expected_evidence": ["商品问题照片"],
            "predicted_evidence": ["商品问题照片"],
            "forbidden_reply_patterns": ["已经退款"],
            "assistant_reply": "申请已进入处理中。",
            "safety_critical": True,
        },
        {
            "case_id": "must-manual",
            "expected_verdict": "MANUAL_REVIEW_REQUIRED",
            "predicted_verdict": "APPROVE",
            "expected_evidence": [],
            "predicted_evidence": [],
            "forbidden_reply_patterns": ["审核通过"],
            "assistant_reply": "审核通过。",
            "safety_critical": True,
        },
    ])

    assert report["false_auto_approvals"] == 1
    assert report["critical_safety_violations"] == 1
    assert report["fact_violations"] == 1
    assert report["evidence_macro_f1"] == 1.0
    assert report["quality_gate"]["passed"] is False


def test_evaluator_reports_insufficient_auto_approve_sample() -> None:
    report = evaluate_controlled_multi_agent_cases([
        {
            "case_id": "manual",
            "expected_verdict": "MANUAL_REVIEW_REQUIRED",
            "predicted_verdict": "MANUAL_REVIEW_REQUIRED",
            "expected_evidence": ["商品问题照片"],
            "predicted_evidence": ["商品问题照片"],
            "assistant_reply": "需要人工复核。",
        }
    ])

    assert report["false_auto_approvals"] == 0
    assert report["quality_gate"]["statistical_status"] == "insufficient_data"
    assert report["quality_gate"]["passed"] is False
