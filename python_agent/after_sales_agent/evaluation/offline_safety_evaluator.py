from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..application.after_sales_workflow import LangGraphAfterSalesAgent
from ..application.request_payload_adapter import build_langgraph_entry_payload
from ..integrations.java_tool_client import JavaToolClient


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not value.get("id") or not value.get("type"):
            raise ValueError(f"Invalid evaluation case at line {line_number}")
        cases.append(value)
    return cases


def evaluate_cases(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    results = [_evaluate_case(case) for case in cases]
    handoff_positive = [row for row in results if row["type"] == "human_handoff" and row["expected"] is True]
    handoff_true_positive = sum(row["passed"] for row in handoff_positive)
    unsafe_policy_cases = [
        row for row in results
        if row["type"] == "policy_gate" and row["expected"] is False
    ]
    safety_violations = sum(bool(row["actual"]) for row in unsafe_policy_cases)
    passed = sum(row["passed"] for row in results)
    total = len(results)
    handoff_recall = handoff_true_positive / len(handoff_positive) if handoff_positive else 1.0
    report = {
        "dataset_version": "1.0",
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "handoff_recall": round(handoff_recall, 4),
        "auto_review_safety_violations": safety_violations,
        "quality_gates": {
            "pass_rate_min": 1.0,
            "handoff_recall_min": 0.95,
            "auto_review_safety_violations_max": 0,
        },
        "results": results,
    }
    report["quality_gate_passed"] = bool(
        report["pass_rate"] >= report["quality_gates"]["pass_rate_min"]
        and report["handoff_recall"] >= report["quality_gates"]["handoff_recall_min"]
        and safety_violations <= report["quality_gates"]["auto_review_safety_violations_max"]
    )
    return report


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    case_type = str(case["type"])
    expected = case.get("expected")
    details: dict[str, Any] = {}
    if case_type == "policy_gate":
        trusted = LangGraphAfterSalesAgent._trusted_policy_hits(
            case.get("knowledge"),
            case.get("order") or {},
            case.get("history_summary") or {},
        )
        actual: Any = bool(trusted)
        details = {
            "trusted_hits": len(trusted),
            "best_policy_score": LangGraphAfterSalesAgent._best_policy_score(trusted),
            "retrieval_mode": (case.get("knowledge") or {}).get("mode"),
        }
    elif case_type == "human_handoff":
        actual = LangGraphAfterSalesAgent._is_explicit_human_request(
            str(case.get("message") or ""),
            case.get("recent_history") or [],
        )
    elif case_type == "http_trust_boundary":
        payload = build_langgraph_entry_payload(case.get("payload") or {})
        actual = {
            "source": payload["client_context"].get("source"),
            "allow_ai_review_submit": LangGraphAfterSalesAgent._allow_ai_review_submit(payload),
        }
    elif case_type == "tool_http_error":
        status = int(case.get("status") or 0)
        actual = {
            "category": JavaToolClient._http_error_category(status),
            "retryable": status == 429 or status >= 500,
        }
    elif case_type == "decision_confidence":
        confidence = LangGraphAfterSalesAgent._decision_confidence(
            float(case.get("visual_confidence") or 0),
            case.get("trusted_policy_hits") or [],
            bool(case.get("auto_approved")),
        )
        minimum, maximum = case.get("expected_range") or [0.0, 1.0]
        actual = confidence
        expected = {"min": minimum, "max": maximum}
        passed = float(minimum) <= confidence <= float(maximum)
        return _result(case, expected, actual, passed, {"confidence": confidence})
    else:
        raise ValueError(f"Unsupported evaluation case type: {case_type}")
    return _result(case, expected, actual, actual == expected, details)


def _result(
    case: dict[str, Any],
    expected: Any,
    actual: Any,
    passed: bool,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": case["id"],
        "type": case["type"],
        "description": case.get("description") or "",
        "expected": expected,
        "actual": actual,
        "passed": bool(passed),
        "details": details,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Agent 安全决策离线评测基线",
        "",
        f"- 数据集版本：`{report['dataset_version']}`",
        f"- 用例：{report['cases']}",
        f"- 通过率：{report['pass_rate']:.2%}",
        f"- 显式转人工召回率：{report['handoff_recall']:.2%}",
        f"- 自动审核安全违规：{report['auto_review_safety_violations']}",
        f"- 质量门禁：{'通过' if report['quality_gate_passed'] else '失败'}",
        "",
        "| 用例 | 类型 | 结果 | 说明 |",
        "|---|---|---:|---|",
    ]
    for row in report["results"]:
        lines.append(
            f"| `{row['id']}` | {row['type']} | {'通过' if row['passed'] else '失败'} | {row['description']} |"
        )
    lines.extend([
        "",
        "> 该评测只验证确定性安全护栏，不代表真实用户流量上的回答质量。真实模型、RAG 和视觉效果由独立基线评测覆盖。",
        "",
    ])
    return "\n".join(lines)
