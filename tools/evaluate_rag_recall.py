"""Evaluate layered RAG retrieval modes from a versioned JSONL dataset."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_agent"))

from after_sales_agent.evaluation.rag_metrics import (  # noqa: E402
    Case,
    enforce_reliable_holdout_filter_gate,
    evaluate,
    load_cases,
)


MODES = ("dense", "keyword", "rrf", "rerank")
DEFAULT_DATASET = ROOT / "python_agent" / "evaluation" / "rag_retrieval_cases.jsonl"
DEFAULT_JSON_OUTPUT = ROOT / "docs" / "rag-recall-baseline.json"
DEFAULT_MARKDOWN_OUTPUT = ROOT / "docs" / "rag-recall-baseline.md"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=(*MODES, "all"), default="all")
    parser.add_argument("--dry-run", action="store_true", help="validate and summarize without providers or DB")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument(
        "--rerank-cost-per-call",
        type=float,
        default=_safe_non_negative_float(os.getenv("RERANK_COST_PER_CALL"), 0.0),
        help="configured cost estimate per hosted rerank request",
    )
    return parser.parse_args(argv)


def _safe_non_negative_float(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def dataset_summary(cases: Sequence[Case]) -> dict[str, Any]:
    return {
        "sample_count": len(cases),
        "split_distribution": dict(sorted(Counter(case.split for case in cases).items())),
        "category_distribution": dict(sorted(Counter(case.category for case in cases).items())),
        "annotation_method_distribution": dict(
            sorted(Counter(case.annotation_method for case in cases).items())
        ),
        "expect_no_answer_count": sum(case.expect_no_answer for case in cases),
        "reliably_annotated_holdout_count": sum(case.is_reliable_holdout for case in cases),
    }


def _retrieval_arguments(case: Case) -> dict[str, Any]:
    allowed = {
        "merchant_code",
        "product_category",
        "scene",
        "intent",
        "source_type",
        "policy_version",
        "top_k",
    }
    arguments = {key: value for key, value in case.filters.items() if key in allowed}
    raw_as_of = case.filters.get("as_of_time")
    if raw_as_of:
        arguments["as_of_time"] = datetime.fromisoformat(str(raw_as_of).replace("Z", "+00:00"))
    return arguments


def run_mode(
    cases: Sequence[Case],
    mode: str,
    *,
    retriever: Any,
    rerank_cost_per_call: float,
) -> dict[str, Any]:
    runs: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()
    for case in cases:
        case_started = time.perf_counter()
        result = retriever.retrieve(
            query=case.query,
            query_id=case.case_id,
            retrieval_mode=mode,
            **_retrieval_arguments(case),
        )
        latency_ms = round((time.perf_counter() - case_started) * 1000, 3)
        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        if trace.get("retrieval_mode") == "compatibility":
            raise RuntimeError(
                f"ablation mode {mode} reached the compatibility path; "
                "set RAG_LAYERED_RETRIEVAL_ENABLED=true"
            )
        rerank_called = mode == "rerank" and int(trace.get("rerank_candidate_count") or 0) > 0
        runs[case.case_id] = {
            "hits": result.get("hits") or [],
            "no_answer": bool(result.get("no_answer")),
            "latency_ms": latency_ms,
            "rerank_cost": rerank_cost_per_call if rerank_called else None,
            "trace": {
                key: trace.get(key)
                for key in (
                    "filter_level",
                    "dense_candidate_count",
                    "keyword_candidate_count",
                    "rrf_candidate_count",
                    "rerank_candidate_count",
                    "retrieval_mode",
                    "stage_latency_ms",
                    "fallback_reason",
                )
            },
        }
    return {
        "runs": runs,
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }


def require_layered_retrieval(retriever: Any) -> None:
    config = getattr(retriever, "config", None)
    if getattr(config, "layered_retrieval_enabled", False) is not True:
        raise RuntimeError(
            "real ablation requires RAG_LAYERED_RETRIEVAL_ENABLED=true; "
            "the compatibility path cannot be reported as dense/keyword/rrf/rerank"
        )


def _configuration() -> dict[str, Any]:
    from after_sales_agent.retrieval.pgvector_retriever import RERANK_THRESHOLDS

    return {
        "embedding_provider": os.getenv("EMBEDDING_PROVIDER", "dashscope"),
        "embedding_model": os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
        "rerank_provider": os.getenv("RERANK_PROVIDER", ""),
        "rerank_model": os.getenv("RERANK_MODEL", "text-rerank-v2"),
        "rerank_thresholds": RERANK_THRESHOLDS,
        "rerank_cost_currency": os.getenv("RERANK_COST_CURRENCY", "configured_currency_unit"),
    }


def render_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    lines = [
        "# 分层 RAG 离线评测",
        "",
        f"- 样本数：{dataset['sample_count']}",
        f"- Split：`{json.dumps(dataset['split_distribution'], ensure_ascii=False)}`",
        f"- 标注方法：`{json.dumps(dataset['annotation_method_distribution'], ensure_ascii=False)}`",
        f"- 可靠 Holdout：{dataset['reliably_annotated_holdout_count']}",
        f"- 运行时间：{report['generated_at']}",
        "",
        "> 当前 18 条为 smoke 数据，不是 Holdout；未完成 chunk 级双人标注，不能用于 Recall 阈值或上线效果结论。",
        "",
    ]
    if report.get("dry_run"):
        lines.extend(["本次为 dry-run，仅校验数据契约和分布，未访问模型或数据库。", ""])
        return "\n".join(lines)
    lines.extend(
        [
            "| 模式 | Recall@5 | Recall@20 | MRR@10 | NDCG@5 | HitRate@5 | Filter Violation | No-answer FPR | Rerank Uplift | p50/p95(ms) | 单次 Rerank 成本 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for mode, entry in report["modes"].items():
        metrics = entry["metrics"]
        latency = metrics["latency_ms"]
        lines.append(
            "| {mode} | {r5} | {r20} | {mrr} | {ndcg} | {hit} | {filter_rate} | {fpr} | {uplift} | {p50}/{p95} | {cost} |".format(
                mode=mode,
                r5=_display(metrics.get("recall_at_5")),
                r20=_display(metrics.get("recall_at_20")),
                mrr=_display(metrics.get("mrr_at_10")),
                ndcg=_display(metrics.get("ndcg_at_5")),
                hit=_display(metrics.get("hit_rate_at_5")),
                filter_rate=_display(metrics.get("filter_violation_rate")),
                fpr=_display(metrics.get("no_answer_false_positive_rate")),
                uplift=_display(metrics.get("rerank_uplift")),
                p50=_display(latency.get("p50")),
                p95=_display(latency.get("p95")),
                cost=_display(metrics.get("average_rerank_cost")),
            )
        )
    lines.extend(
        [
            "",
            "## 局限",
            "",
            "- smoke 查询由旧场景集迁移，只验证链路和数据契约。",
            "- `relevant_chunk_ids` 尚未经过双人标注或争议复核，因此 Recall/MRR/NDCG/HitRate 不作门禁。",
            "- Filter Violation Rate 的硬门禁只适用于可靠标注 Holdout。",
            "- 单次 Rerank 成本是通过 `RERANK_COST_PER_CALL` 配置的估算，不代表账单。",
            "",
        ]
    )
    return "\n".join(lines)


def _display(value: Any) -> str:
    return "N/A" if value is None else str(value)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cases = load_cases(args.dataset)
    summary = dataset_summary(cases)
    report: dict[str, Any] = {
        "dataset": summary,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "limitations": [
            "smoke is not holdout",
            "recall thresholds require dual annotation or adjudication",
            "rerank cost is a configured estimate",
        ],
    }
    if args.dry_run:
        report["dry_run"] = True
        report["provider_accessed"] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    from after_sales_agent.config.environment import load_agent_env
    from after_sales_agent.retrieval.pgvector_retriever import PgVectorKnowledgeRetriever

    load_agent_env()
    retriever = PgVectorKnowledgeRetriever()
    require_layered_retrieval(retriever)
    selected_modes = MODES if args.mode == "all" else (args.mode,)
    mode_reports: dict[str, Any] = {}
    mode_runs: dict[str, dict[str, Any]] = {}
    for mode in selected_modes:
        execution = run_mode(
            cases,
            mode,
            retriever=retriever,
            rerank_cost_per_call=args.rerank_cost_per_call,
        )
        mode_runs[mode] = execution["runs"]
        baseline = mode_runs.get("rrf") if mode == "rerank" else None
        mode_reports[mode] = {
            "runtime_seconds": execution["runtime_seconds"],
            "metrics": evaluate(cases, execution["runs"], baseline_runs=baseline),
            "traces": {case_id: run["trace"] for case_id, run in execution["runs"].items()},
        }
        mode_reports[mode]["safety_gate"] = enforce_reliable_holdout_filter_gate(cases, execution["runs"])
    report.update({"dry_run": False, "configuration": _configuration(), "modes": mode_reports})
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
