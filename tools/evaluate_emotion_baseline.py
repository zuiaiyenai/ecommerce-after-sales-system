"""Real-model holdout evaluation for emotion classification and queue priority."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_agent"))

from after_sales_agent.config.environment import load_agent_env  # noqa: E402
from after_sales_agent.application.emotion.emotion_service import EmotionAgent  # noqa: E402
from after_sales_agent.application.emotion.llm_emotion_classifier import LLMEmotionBackend  # noqa: E402
from after_sales_agent.domain.models import AfterSalesRequest, ConversationMessage  # noqa: E402


LABELS = ("satisfied", "calm", "anxious", "dissatisfied", "angry")
DEFAULT_DATASET = ROOT / "tools" / "emotion_priority_holdout.json"
DEFAULT_OUTPUT_PREFIX = ROOT / "docs" / "emotion-priority-holdout"


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    history = tuple(
        ConversationMessage(role=str(item.get("role") or "user"), content=str(item.get("content") or ""))
        for item in case.get("recent_history", [])
        if isinstance(item, dict) and item.get("content")
    )
    request = AfterSalesRequest(
        user_id="emotion-holdout",
        message=str(case["message"]),
        human_request_count=int(case.get("human_request_count") or 0),
    )
    started = time.perf_counter()
    try:
        result = EmotionAgent().analyze(
            request,
            recent_history=history,
            recent_user_messages=tuple(item.content for item in history if item.role == "user"),
        )
        return {
            "id": case["id"],
            "message": case["message"],
            "expected_label": case["expected_label"],
            "acceptable_labels": case.get("acceptable_labels") or [case["expected_label"]],
            "predicted_label": result.label.value,
            "expected_priority": bool(case["expected_priority"]),
            "predicted_priority": result.need_human_priority,
            "score": result.score,
            "confidence": result.confidence,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "ok": True,
            "notes": case.get("notes") or "",
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "message": case["message"],
            "expected_label": case["expected_label"],
            "acceptable_labels": case.get("acceptable_labels") or [case["expected_label"]],
            "predicted_label": None,
            "expected_priority": bool(case["expected_priority"]),
            "predicted_priority": None,
            "score": None,
            "confidence": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "ok": False,
            "error": exc.__class__.__name__,
            "notes": case.get("notes") or "",
        }


def label_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strict_correct = sum(row["predicted_label"] == row["expected_label"] for row in rows)
    tolerant_correct = sum(row["predicted_label"] in row["acceptable_labels"] for row in rows)
    confusion = {
        expected: {predicted: 0 for predicted in (*LABELS, "__error__")}
        for expected in LABELS
    }
    for row in rows:
        predicted = row["predicted_label"] if row["predicted_label"] in LABELS else "__error__"
        confusion[row["expected_label"]][predicted] += 1

    per_label: dict[str, dict[str, float | int]] = {}
    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in LABELS if other != label)
        fn = sum(confusion[label][other] for other in (*LABELS, "__error__") if other != label)
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        f1 = safe_div(2 * precision * recall, precision + recall) if precision + recall else 0.0
        per_label[label] = {
            "support": sum(confusion[label].values()),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    return {
        "strict_accuracy": round(safe_div(strict_correct, len(rows)), 4),
        "tolerant_accuracy": round(safe_div(tolerant_correct, len(rows)), 4),
        "macro_f1": round(statistics.mean(float(item["f1"]) for item in per_label.values()), 4),
        "confusion_matrix": confusion,
        "per_label": per_label,
    }


def priority_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row["predicted_priority"] is not None]
    tp = sum(row["expected_priority"] and row["predicted_priority"] for row in completed)
    fp = sum(not row["expected_priority"] and row["predicted_priority"] for row in completed)
    fn = sum(row["expected_priority"] and not row["predicted_priority"] for row in completed)
    tn = sum(not row["expected_priority"] and not row["predicted_priority"] for row in completed)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return {
        "accuracy": round(safe_div(tp + tn, len(rows)), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(safe_div(2 * precision * recall, precision + recall), 4) if precision + recall else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def render_markdown(report: dict[str, Any]) -> str:
    label = report["label_metrics"]
    priority = report["priority_metrics"]
    latency = report["latency_ms"]
    lines = [
        "# 情绪识别与人工优先级独立挑战集",
        "",
        f"> 评测时间：{report['evaluated_at']}；模型：`{report['model']}`；Provider：`{report['provider']}`。",
        "",
        "## 结果",
        "",
        f"- 样本：{report['cases']}（成功调用 {report['successful_calls']}，失败 {report['failed_calls']}）",
        f"- 五分类严格准确率：{label['strict_accuracy']:.2%}",
        f"- 五分类相邻标签容忍准确率：{label['tolerant_accuracy']:.2%}",
        f"- 五分类 Macro-F1：{label['macro_f1']:.2%}",
        f"- 人工优先级 Accuracy / Precision / Recall / F1：{priority['accuracy']:.2%} / {priority['precision']:.2%} / {priority['recall']:.2%} / {priority['f1']:.2%}",
        f"- 人工优先级混淆矩阵：TP={priority['tp']}、FP={priority['fp']}、FN={priority['fn']}、TN={priority['tn']}",
        f"- 延迟：平均 {latency['avg']:.2f} ms，P50 {latency['p50']:.2f} ms，P95 {latency['p95']:.2f} ms",
        f"- 与当前系统 Prompt 完全相同的测试句：{report['exact_prompt_overlap_count']}",
        "",
        "## 五分类混淆矩阵",
        "",
        "| 真实\\预测 | satisfied | calm | anxious | dissatisfied | angry | 调用失败 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for expected in LABELS:
        matrix = label["confusion_matrix"][expected]
        lines.append(
            f"| {expected} | {matrix['satisfied']} | {matrix['calm']} | {matrix['anxious']} | "
            f"{matrix['dissatisfied']} | {matrix['angry']} | {matrix['__error__']} |"
        )
    lines.extend([
        "",
        "## 误判样本",
        "",
        "| ID | 文本 | 期望 | 预测 | 期望优先 | 预测优先 |",
        "|---|---|---|---|---:|---:|",
    ])
    mistakes = [
        row for row in report["results"]
        if row["predicted_label"] != row["expected_label"]
        or row["predicted_priority"] != row["expected_priority"]
    ]
    if mistakes:
        for row in mistakes:
            text = str(row["message"]).replace("|", "\\|")
            lines.append(
                f"| {row['id']} | {text} | {row['expected_label']} | {row['predicted_label'] or 'ERROR'} | "
                f"{row['expected_priority']} | {row['predicted_priority']} |"
            )
    else:
        lines.append("| - | 本轮没有误判 | - | - | - | - |")
    lines.extend([
        "",
        "## 口径限制",
        "",
        "- 这是规则化预标注的独立挑战集，不是线上随机流量，也没有完成双人独立标注与一致性仲裁。",
        "- 挑战集刻意增加反讽、否定、引用、错别字、上下文反转等困难样本，类别分布不代表真实业务分布。",
        "- 五档情绪边界本身具有主观性，因此同时报告严格准确率、相邻标签容忍准确率和人工优先级指标。",
        "- 简历中不应把该结果称为线上准确率；在获得脱敏真实会话与双人标注前，只能称为独立离线挑战集。",
        "- 即使人工优先级在本挑战集全命中，也不能在简历引用 100%；标签仍由同一套业务规则单人预标注。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the current real emotion model on an independent holdout set")
    parser.add_argument("--real", action="store_true", help="required acknowledgement that real model quota will be consumed")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-prefix", type=Path, default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-requests", type=int, default=60)
    args = parser.parse_args()
    if not args.real:
        raise SystemExit("Refusing to call the real emotion model without --real")
    if args.concurrency < 1:
        parser.error("--concurrency must be positive")

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        parser.error("dataset must be a non-empty JSON array")
    if len(cases) > args.max_requests:
        parser.error(f"dataset has {len(cases)} cases, exceeding --max-requests={args.max_requests}")
    required = {"id", "message", "expected_label", "expected_priority"}
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not required.issubset(case):
            parser.error(f"case {index} is missing required fields")
        if case["expected_label"] not in LABELS:
            parser.error(f"case {case['id']} has invalid expected_label")

    load_agent_env()
    provider = os.getenv("LLM_PROVIDER", "unknown")
    model = os.getenv("EMOTION_MODEL") or os.getenv("LLM_MODEL") or "unknown"
    system_prompt = LLMEmotionBackend._system_prompt()
    overlap_ids = [case["id"] for case in cases if str(case["message"]).strip() in system_prompt]

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(evaluate_case, case) for case in cases]
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(json.dumps({key: row.get(key) for key in ("id", "predicted_label", "predicted_priority", "score", "latency_ms", "ok")}, ensure_ascii=False), flush=True)
    order = {case["id"]: index for index, case in enumerate(cases)}
    rows.sort(key=lambda row: order[row["id"]])

    latencies = [float(row["latency_ms"]) for row in rows]
    errors = Counter(str(row.get("error") or "") for row in rows if not row["ok"])
    report = {
        "evaluated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "dataset": str(args.dataset.relative_to(ROOT)),
        "annotation": "rule-authored single-annotator challenge labels; no independent double annotation",
        "cases": len(rows),
        "successful_calls": sum(bool(row["ok"]) for row in rows),
        "failed_calls": sum(not bool(row["ok"]) for row in rows),
        "completion_rate": round(safe_div(sum(bool(row["ok"]) for row in rows), len(rows)), 4),
        "exact_prompt_overlap_count": len(overlap_ids),
        "exact_prompt_overlap_ids": overlap_ids,
        "label_metrics": label_metrics(rows),
        "priority_metrics": priority_metrics(rows),
        "latency_ms": {
            "avg": round(statistics.mean(latencies), 2),
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "max": round(max(latencies), 2),
        },
        "error_counts": dict(errors),
        "results": rows,
    }

    output_prefix = args.output_prefix if args.output_prefix.is_absolute() else ROOT / args.output_prefix
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    output_prefix.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_prefix.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    summary = {key: value for key, value in report.items() if key not in {"results", "label_metrics"}}
    summary["label_metrics"] = {
        key: report["label_metrics"][key]
        for key in ("strict_accuracy", "tolerant_accuracy", "macro_f1")
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
