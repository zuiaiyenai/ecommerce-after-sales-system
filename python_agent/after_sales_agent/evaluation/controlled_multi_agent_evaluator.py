from __future__ import annotations

import json
from math import sqrt
from pathlib import Path
from typing import Any, Iterable


def load_controlled_multi_agent_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} must be a JSON object")
        if not str(value.get("case_id") or "").strip():
            raise ValueError(f"line {line_number} case_id is required")
        cases.append(value)
    return cases


def evaluate_controlled_multi_agent_cases(
    cases: Iterable[dict[str, Any]],
    *,
    minimum_auto_approve_samples: int = 300,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    predicted_approvals = 0
    correct_approvals = 0
    false_auto_approvals = 0
    critical_safety_violations = 0
    fact_violations = 0
    evidence_f1_values: list[float] = []
    for case in cases:
        expected = _verdict(case.get("expected_verdict"))
        predicted = _verdict(case.get("predicted_verdict"))
        false_approve = predicted == "APPROVE" and expected != "APPROVE"
        if predicted == "APPROVE":
            predicted_approvals += 1
            if expected == "APPROVE":
                correct_approvals += 1
        if false_approve:
            false_auto_approvals += 1
        critical = bool(case.get("safety_critical")) and false_approve
        if critical:
            critical_safety_violations += 1
        reply = str(case.get("assistant_reply") or "")
        matched_forbidden = [
            str(pattern)
            for pattern in case.get("forbidden_reply_patterns") or []
            if str(pattern or "") and str(pattern) in reply
        ]
        fact_violations += len(matched_forbidden)
        evidence_f1 = _set_f1(
            case.get("expected_evidence") or [],
            case.get("predicted_evidence") or [],
        )
        evidence_f1_values.append(evidence_f1)
        results.append({
            "case_id": str(case.get("case_id") or ""),
            "expected_verdict": expected,
            "predicted_verdict": predicted,
            "false_auto_approval": false_approve,
            "critical_safety_violation": critical,
            "matched_forbidden_reply_patterns": matched_forbidden,
            "evidence_f1": evidence_f1,
        })
    total = len(results)
    precision = (
        correct_approvals / predicted_approvals
        if predicted_approvals
        else 0.0
    )
    precision_lower_bound = _wilson_lower_bound(
        correct_approvals,
        predicted_approvals,
    )
    evidence_macro_f1 = (
        sum(evidence_f1_values) / len(evidence_f1_values)
        if evidence_f1_values
        else 0.0
    )
    statistically_ready = predicted_approvals >= minimum_auto_approve_samples
    safety_passed = (
        false_auto_approvals == 0
        and critical_safety_violations == 0
        and fact_violations == 0
        and evidence_macro_f1 >= 0.95
    )
    statistical_passed = statistically_ready and precision_lower_bound >= 0.99
    return {
        "cases": total,
        "predicted_auto_approvals": predicted_approvals,
        "correct_auto_approvals": correct_approvals,
        "false_auto_approvals": false_auto_approvals,
        "critical_safety_violations": critical_safety_violations,
        "fact_violations": fact_violations,
        "auto_approve_precision": round(precision, 6),
        "auto_approve_precision_lower_bound_95": round(precision_lower_bound, 6),
        "evidence_macro_f1": round(evidence_macro_f1, 6),
        "quality_gate": {
            "passed": safety_passed and statistical_passed,
            "safety_passed": safety_passed,
            "statistical_status": "ready" if statistically_ready else "insufficient_data",
            "minimum_auto_approve_samples": minimum_auto_approve_samples,
            "required_precision_lower_bound": 0.99,
        },
        "results": results,
    }


def render_controlled_multi_agent_markdown(report: dict[str, Any]) -> str:
    gate = report["quality_gate"]
    return "\n".join([
        "# Controlled Multi-Agent 准确率评测",
        "",
        f"- 案例数：{report['cases']}",
        f"- 自动通过提案：{report['predicted_auto_approvals']}",
        f"- 错误自动通过：{report['false_auto_approvals']}",
        f"- 关键安全违规：{report['critical_safety_violations']}",
        f"- 事实违规：{report['fact_violations']}",
        f"- 自动通过 Precision：{report['auto_approve_precision']:.2%}",
        f"- Precision 单侧 95% 下界：{report['auto_approve_precision_lower_bound_95']:.2%}",
        f"- 凭证 Macro-F1：{report['evidence_macro_f1']:.2%}",
        f"- 统计状态：{gate['statistical_status']}",
        f"- 质量门禁：{'通过' if gate['passed'] else '未通过'}",
        "",
    ])


def _verdict(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == "MANUAL_REVIEW":
        return "MANUAL_REVIEW_REQUIRED"
    return normalized or "UNKNOWN"


def _set_f1(expected: Iterable[Any], predicted: Iterable[Any]) -> float:
    expected_set = {str(item).strip() for item in expected if str(item).strip()}
    predicted_set = {str(item).strip() for item in predicted if str(item).strip()}
    if not expected_set and not predicted_set:
        return 1.0
    if not expected_set or not predicted_set:
        return 0.0
    overlap = len(expected_set.intersection(predicted_set))
    precision = overlap / len(predicted_set)
    recall = overlap / len(expected_set)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _wilson_lower_bound(successes: int, total: int, z: float = 1.6448536269514722) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + (z * z / total)
    center = proportion + (z * z / (2 * total))
    margin = z * sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return max(0.0, (center - margin) / denominator)
