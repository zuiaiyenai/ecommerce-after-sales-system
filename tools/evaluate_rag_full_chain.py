"""Evaluate final RAG context, grounded generation, and answer routing without business writes."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PYTHON_AGENT = ROOT / "python_agent"
TOOLS = ROOT / "tools"
if str(PYTHON_AGENT) not in sys.path:
    sys.path.insert(0, str(PYTHON_AGENT))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from after_sales_agent.agent.workflows.consultation import ConsultationWorkflow  # noqa: E402
from after_sales_agent.config.environment import load_agent_env  # noqa: E402
from after_sales_agent.evaluation.rag_metrics import Case, load_cases  # noqa: E402
from after_sales_agent.providers.llm_client import LLM_CLIENTS, get_llm_client  # noqa: E402
from after_sales_agent.retrieval.pgvector_retriever import PgVectorKnowledgeRetriever  # noqa: E402

from evaluate_rag_recall import require_layered_retrieval, run_mode  # noqa: E402


DEFAULT_DATASET = PYTHON_AGENT / "evaluation" / "rag_full_chain_cases.jsonl"
DEFAULT_OUTPUT = ROOT / "docs" / "rag-full-chain-evaluation.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generation-limit", type=int, default=0, help="0 evaluates every answerable case")
    return parser.parse_args()


def _ranked_ids(hits: Iterable[dict[str, Any]]) -> list[str]:
    return [str(hit["chunk_id"]) for hit in hits if hit.get("chunk_id") is not None]


def context_metrics(cases: list[Case], runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.expect_no_answer or not case.relevant_chunk_ids:
            continue
        hits = runs[case.case_id].get("hits") or []
        ranked = _ranked_ids(hits)
        overlap = case.relevant_chunk_ids.intersection(ranked)
        precision = len(overlap) / len(ranked) if ranked else 0.0
        recall = len(overlap) / len(case.relevant_chunk_ids)
        rows.append(
            {
                "case_id": case.case_id,
                "retrieved_chunk_ids": ranked,
                "relevant_chunk_ids": sorted(case.relevant_chunk_ids),
                "precision": precision,
                "recall": recall,
            }
        )
    return {
        "case_count": len(rows),
        "context_precision": _mean(row["precision"] for row in rows),
        "context_recall": _mean(row["recall"] for row in rows),
        "empty_context_rate": _mean(not row["retrieved_chunk_ids"] for row in rows),
        "results": rows,
    }


def routing_metrics(cases: list[Case], runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    labels = ("ANSWER", "NO_ANSWER")
    rows: list[dict[str, Any]] = []
    for case in cases:
        run = runs[case.case_id]
        expected = "NO_ANSWER" if case.expect_no_answer else "ANSWER"
        predicted = "NO_ANSWER" if run.get("no_answer") or not run.get("hits") else "ANSWER"
        rows.append(
            {
                "case_id": case.case_id,
                "expected": expected,
                "predicted": predicted,
                "correct": expected == predicted,
            }
        )
    f1_values = []
    for label in labels:
        tp = sum(row["expected"] == label and row["predicted"] == label for row in rows)
        fp = sum(row["expected"] != label and row["predicted"] == label for row in rows)
        fn = sum(row["expected"] == label and row["predicted"] != label for row in rows)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1_values.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {
        "case_count": len(rows),
        "accuracy": _mean(row["correct"] for row in rows),
        "macro_f1": _mean(f1_values),
        "results": rows,
    }


def generation_metrics(
    cases: list[Case],
    runs: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    llm = get_llm_client()
    service = ConsultationWorkflow(llm=llm)
    selected = [
        case
        for case in cases
        if not case.expect_no_answer and runs[case.case_id].get("hits")
    ]
    if limit > 0:
        selected = selected[:limit]
    rows: list[dict[str, Any]] = []
    for case in selected:
        hits = runs[case.case_id]["hits"]
        started = time.perf_counter()
        answer = service._generate_answer(
            {"message": case.query, "recent_history": []},
            {"mode": "hybrid_reranked"},
            hits,
        )
        generation_latency_ms = (time.perf_counter() - started) * 1000
        judgment = _judge_faithfulness(llm, question=case.query, answer=answer, hits=hits)
        total_claims = max(0, int(judgment.get("total_claims") or 0))
        supported_claims = min(
            total_claims,
            max(0, int(judgment.get("supported_claims") or 0)),
        )
        score = supported_claims / total_claims if total_claims else 1.0
        rows.append(
            {
                "case_id": case.case_id,
                "answer": answer,
                "faithfulness": score,
                "total_claims": total_claims,
                "supported_claims": supported_claims,
                "unsupported_claims": judgment.get("unsupported_claims") or [],
                "generation_latency_ms": round(generation_latency_ms, 3),
            }
        )
    return {
        "case_count": len(rows),
        "faithfulness": _mean(row["faithfulness"] for row in rows),
        "fully_grounded_rate": _mean(row["faithfulness"] == 1.0 for row in rows),
        "latency_ms": {
            "p50": _percentile([row["generation_latency_ms"] for row in rows], 0.5),
            "p95": _percentile([row["generation_latency_ms"] for row in rows], 0.95),
        },
        "results": rows,
    }


def _judge_faithfulness(llm: Any, *, question: str, answer: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    context = [
        {
            "chunk_id": hit.get("chunk_id"),
            "source_code": hit.get("source_code"),
            "content": hit.get("snippet"),
        }
        for hit in hits
    ]
    return llm.generate_structured(
        system_prompt=(
            "你是严格的RAG忠实度评审。把回答拆成可验证事实声明，逐项判断是否能由给定上下文直接支持。"
            "不得使用常识补全；建议、时效、条件、承诺和业务状态都算声明。只输出JSON。"
        ),
        user_prompt=json.dumps(
            {"question": question, "answer": answer, "context": context},
            ensure_ascii=False,
            default=str,
        ),
        schema={
            "type": "object",
            "required": ["total_claims", "supported_claims", "unsupported_claims"],
            "properties": {
                "total_claims": {"type": "integer", "minimum": 0},
                "supported_claims": {"type": "integer", "minimum": 0},
                "unsupported_claims": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        temperature=0.0,
        max_tokens=500,
    )


def _mean(values: Iterable[Any]) -> float | None:
    normalized = [float(value) for value in values]
    return round(statistics.mean(normalized), 6) if normalized else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 3)


def main() -> int:
    args = parse_args()
    load_agent_env()
    cases = load_cases(args.dataset)
    retriever = PgVectorKnowledgeRetriever()
    require_layered_retrieval(retriever)
    execution = run_mode(cases, "rerank", retriever=retriever, rerank_cost_per_call=0.0)
    try:
        report = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "dataset": {
                "path": str(args.dataset),
                "case_count": len(cases),
                "positive_count": sum(not case.expect_no_answer for case in cases),
                "no_answer_count": sum(case.expect_no_answer for case in cases),
                "annotation_method": "single_curated",
            },
            "context": context_metrics(cases, execution["runs"]),
            "generation": generation_metrics(
                cases,
                execution["runs"],
                limit=max(0, args.generation_limit),
            ),
            "business_routing": routing_metrics(cases, execution["runs"]),
            "limitations": [
                "faithfulness uses an LLM-as-judge and should be spot-checked by humans",
                "business metrics cover ANSWER/NO_ANSWER routing, not refund approval accuracy",
                "the evaluation set is single-curated rather than dual-annotated holdout",
                "generation bypasses persistence and performs no Java business writes",
            ],
        }
    finally:
        LLM_CLIENTS.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "dataset": report["dataset"],
        "context": {key: value for key, value in report["context"].items() if key != "results"},
        "generation": {key: value for key, value in report["generation"].items() if key != "results"},
        "business_routing": {
            key: value for key, value in report["business_routing"].items() if key != "results"
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
