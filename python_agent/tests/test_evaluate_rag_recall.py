from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import evaluate_rag_recall  # noqa: E402


def test_real_ablation_requires_layered_retrieval_switch() -> None:
    retriever = type(
        "DisabledRetriever",
        (),
        {"config": type("Config", (), {"layered_retrieval_enabled": False})()},
    )()

    with pytest.raises(RuntimeError, match="RAG_LAYERED_RETRIEVAL_ENABLED=true"):
        evaluate_rag_recall.require_layered_retrieval(retriever)


def test_ablation_run_rejects_compatibility_trace() -> None:
    class CompatibilityRetriever:
        def retrieve(self, **_kwargs):
            return {
                "hits": [],
                "no_answer": True,
                "trace": {"retrieval_mode": "compatibility"},
            }

    case = evaluate_rag_recall.Case("c1", relevant_chunk_ids=set(), query="test")

    with pytest.raises(RuntimeError, match="compatibility path"):
        evaluate_rag_recall.run_mode(
            [case],
            "dense",
            retriever=CompatibilityRetriever(),
            rerank_cost_per_call=0.0,
        )
