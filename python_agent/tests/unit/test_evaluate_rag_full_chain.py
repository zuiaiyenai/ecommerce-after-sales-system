from __future__ import annotations

import importlib.util
from pathlib import Path

from after_sales_agent.evaluation.rag_metrics import Case


SCRIPT = Path(__file__).resolve().parents[3] / "tools" / "evaluate_rag_full_chain.py"
SPEC = importlib.util.spec_from_file_location("evaluate_rag_full_chain", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_context_and_routing_metrics() -> None:
    cases = [
        Case(case_id="positive", relevant_chunk_ids={"1", "2"}),
        Case(case_id="negative", relevant_chunk_ids=set(), expect_no_answer=True),
    ]
    runs = {
        "positive": {"hits": [{"chunk_id": "1"}, {"chunk_id": "3"}], "no_answer": False},
        "negative": {"hits": [], "no_answer": True},
    }

    context = MODULE.context_metrics(cases, runs)
    routing = MODULE.routing_metrics(cases, runs)

    assert context["context_precision"] == 0.5
    assert context["context_recall"] == 0.5
    assert routing["accuracy"] == 1.0
    assert routing["macro_f1"] == 1.0


def test_percentile_interpolates() -> None:
    assert MODULE._percentile([10.0, 20.0, 30.0], 0.95) == 29.0
