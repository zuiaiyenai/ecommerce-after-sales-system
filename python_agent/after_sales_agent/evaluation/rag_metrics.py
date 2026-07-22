"""Pure offline metrics and JSONL contract for layered RAG evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


RELIABLE_ANNOTATION_METHODS = frozenset({"dual_annotated", "adjudicated"})
REQUIRED_JSONL_FIELDS = frozenset(
    {
        "case_id",
        "query",
        "filters",
        "relevant_chunk_ids",
        "expect_no_answer",
        "forbidden_merchant_codes",
        "forbidden_policy_versions",
    }
)


@dataclass(frozen=True)
class Case:
    case_id: str
    relevant_chunk_ids: set[str]
    query: str = ""
    filters: Mapping[str, Any] = field(default_factory=dict)
    expect_no_answer: bool = False
    forbidden_merchant_codes: set[str] = field(default_factory=set)
    forbidden_policy_versions: set[str] = field(default_factory=set)
    split: str = "smoke"
    annotation_method: str = "unverified"
    category: str = "uncategorized"

    @property
    def is_reliable_holdout(self) -> bool:
        return self.split == "holdout" and self.annotation_method in RELIABLE_ANNOTATION_METHODS


def reciprocal_rank(relevant: set[str], ranked: list[str], cutoff: int) -> float:
    return next(
        (1.0 / rank for rank, item in enumerate(ranked[:cutoff], 1) if item in relevant),
        0.0,
    )


def hit_rate(relevant: set[str], ranked: list[str], cutoff: int) -> float:
    return float(bool(relevant.intersection(ranked[:cutoff])))


def _recall(relevant: set[str], ranked: list[str], cutoff: int) -> float:
    return len(relevant.intersection(ranked[:cutoff])) / len(relevant) if relevant else 0.0


def _ndcg(relevant: set[str], ranked: list[str], cutoff: int) -> float:
    if not relevant:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(ranked[:cutoff], 1)
        if item in relevant
    )
    ideal_count = min(len(relevant), cutoff)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal if ideal else 0.0


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def _run_payload(raw: Any) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)], {}
    if isinstance(raw, Mapping):
        hits = raw.get("hits")
        return ([item for item in hits if isinstance(item, dict)] if isinstance(hits, list) else []), raw
    return [], {}


def _ranked_ids(hits: Iterable[Mapping[str, Any]]) -> list[str]:
    ranked: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        value = hit.get("chunk_id")
        if value is None:
            continue
        chunk_id = str(value)
        if chunk_id not in seen:
            seen.add(chunk_id)
            ranked.append(chunk_id)
    return ranked


def _hit_value(hit: Mapping[str, Any], key: str) -> str | None:
    value = hit.get(key)
    metadata = hit.get("metadata")
    if value is None and isinstance(metadata, Mapping):
        value = metadata.get(key)
    return None if value is None else str(value)


def evaluate(
    cases: Sequence[Case],
    runs: Mapping[str, Any],
    *,
    k_values: tuple[int, ...] = (5, 20),
    baseline_runs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate ranked retrieval output without model or database access."""
    positive_cases = [case for case in cases if case.relevant_chunk_ids and not case.expect_no_answer]
    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    costs: list[float] = []
    no_answer_false_positives = 0
    no_answer_cases = 0
    violations = 0
    filter_checked_hits = 0
    filter_metadata_missing = 0
    filter_safety_cases = 0

    for case in cases:
        hits, payload = _run_payload(runs.get(case.case_id, []))
        rankings[case.case_id] = _ranked_ids(hits)
        latency = payload.get("latency_ms")
        if isinstance(latency, (int, float)) and math.isfinite(float(latency)):
            latencies.append(float(latency))
        cost = payload.get("rerank_cost")
        if isinstance(cost, (int, float)) and math.isfinite(float(cost)):
            costs.append(float(cost))

        if case.expect_no_answer:
            no_answer_cases += 1
            explicit_no_answer = payload.get("no_answer")
            answered = not bool(explicit_no_answer) if isinstance(explicit_no_answer, bool) else bool(hits)
            no_answer_false_positives += int(answered)

        has_filter_labels = bool(case.forbidden_merchant_codes or case.forbidden_policy_versions)
        if has_filter_labels:
            filter_safety_cases += 1
            filter_checked_hits += len(hits)
            for hit in hits:
                merchant = _hit_value(hit, "merchant_code")
                version = _hit_value(hit, "policy_version")
                if not merchant or not version:
                    filter_metadata_missing += 1
                if merchant in case.forbidden_merchant_codes or version in case.forbidden_policy_versions:
                    violations += 1

    report: dict[str, Any] = {
        "case_count": len(cases),
        "positive_case_count": len(positive_cases),
    }
    for cutoff in sorted(set(k_values)):
        recalls = [_recall(case.relevant_chunk_ids, rankings[case.case_id], cutoff) for case in positive_cases]
        report[f"recall_at_{cutoff}"] = _rounded(_mean(recalls))

    mrr_values = [reciprocal_rank(case.relevant_chunk_ids, rankings[case.case_id], 10) for case in positive_cases]
    ndcg_values = [_ndcg(case.relevant_chunk_ids, rankings[case.case_id], 5) for case in positive_cases]
    hit_values = [hit_rate(case.relevant_chunk_ids, rankings[case.case_id], 5) for case in positive_cases]
    report.update(
        {
            "mrr_at_10": _rounded(_mean(mrr_values)),
            "ndcg_at_5": _rounded(_mean(ndcg_values)),
            "hit_rate_at_5": _rounded(_mean(hit_values)),
            "filter_violation_rate": _rounded(violations / filter_checked_hits) if filter_checked_hits else 0.0,
            "filter_violation_count": violations,
            "filter_checked_hit_count": filter_checked_hits,
            "filter_safety_case_count": filter_safety_cases,
            "filter_metadata_missing_count": filter_metadata_missing,
            "no_answer_false_positive_rate": _rounded(no_answer_false_positives / no_answer_cases)
            if no_answer_cases
            else 0.0,
            "no_answer_case_count": no_answer_cases,
            "latency_ms": {
                "p50": _rounded(_percentile(latencies, 0.50)),
                "p95": _rounded(_percentile(latencies, 0.95)),
            },
            "average_rerank_cost": _rounded(_mean(costs)),
        }
    )

    if baseline_runs is None:
        report["rerank_uplift"] = None
    else:
        baseline = evaluate(cases, baseline_runs, k_values=k_values)
        current_ndcg = report["ndcg_at_5"]
        baseline_ndcg = baseline["ndcg_at_5"]
        report["rerank_uplift"] = (
            _rounded(float(current_ndcg) - float(baseline_ndcg))
            if current_ndcg is not None and baseline_ndcg is not None
            else None
        )
    return report


def load_cases(path: str | Path) -> list[Case]:
    dataset_path = Path(path)
    cases: list[Case] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"line {line_number} must be a JSON object")
        missing = REQUIRED_JSONL_FIELDS.difference(row)
        if missing:
            raise ValueError(f"line {line_number} missing required fields: {sorted(missing)}")
        case_id = str(row["case_id"]).strip()
        query = str(row["query"]).strip()
        if not case_id or not query:
            raise ValueError(f"line {line_number} case_id and query must be non-empty")
        if case_id in seen_ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen_ids.add(case_id)
        filters = row["filters"]
        if not isinstance(filters, dict):
            raise ValueError(f"line {line_number} filters must be an object")
        split = str(row.get("split") or "smoke").strip().lower()
        annotation_method = str(row.get("annotation_method") or "unverified").strip().lower()
        if split == "holdout" and annotation_method not in RELIABLE_ANNOTATION_METHODS:
            raise ValueError(
                f"line {line_number} holdout requires reliable annotation: "
                f"{sorted(RELIABLE_ANNOTATION_METHODS)}"
            )
        forbidden_merchant_codes = _require_safety_label_set(
            row, "forbidden_merchant_codes", line_number
        )
        forbidden_policy_versions = _require_safety_label_set(
            row, "forbidden_policy_versions", line_number
        )
        if (
            split == "holdout"
            and annotation_method in RELIABLE_ANNOTATION_METHODS
            and (not forbidden_merchant_codes or not forbidden_policy_versions)
        ):
            raise ValueError(
                f"line {line_number} reliable holdout requires merchant and policy-version safety labels"
            )
        cases.append(
            Case(
                case_id=case_id,
                query=query,
                filters=dict(filters),
                relevant_chunk_ids={str(value) for value in _require_list(row, "relevant_chunk_ids", line_number)},
                expect_no_answer=bool(row["expect_no_answer"]),
                forbidden_merchant_codes=forbidden_merchant_codes,
                forbidden_policy_versions=forbidden_policy_versions,
                split=split,
                annotation_method=annotation_method,
                category=str(row.get("category") or "uncategorized").strip().lower(),
            )
        )
    if not cases:
        raise ValueError("dataset must contain at least one case")
    return cases


def _require_list(row: Mapping[str, Any], key: str, line_number: int) -> list[Any]:
    value = row.get(key)
    if not isinstance(value, list):
        raise ValueError(f"line {line_number} {key} must be an array")
    return value


def _require_safety_label_set(
    row: Mapping[str, Any],
    key: str,
    line_number: int,
) -> set[str]:
    values = _require_list(row, key, line_number)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(
            f"line {line_number} {key} must contain non-empty string safety labels"
        )
    return {value.strip() for value in values}


def _has_valid_safety_labels(values: set[str]) -> bool:
    return bool(values) and all(
        isinstance(value, str) and bool(value) and value == value.strip()
        for value in values
    )


def enforce_reliable_holdout_filter_gate(cases: Sequence[Case], runs: Mapping[str, Any]) -> dict[str, Any]:
    reliable_holdout = [case for case in cases if case.is_reliable_holdout]
    if not reliable_holdout:
        return {"status": "not_applicable", "reason": "no_reliably_annotated_holdout"}
    incomplete_labels = [
        case.case_id
        for case in reliable_holdout
        if not _has_valid_safety_labels(case.forbidden_merchant_codes)
        or not _has_valid_safety_labels(case.forbidden_policy_versions)
    ]
    if incomplete_labels:
        raise ValueError(
            "reliably annotated holdout requires non-empty string safety labels "
            "for merchant and policy-version filters; "
            f"missing for {len(incomplete_labels)} case(s)"
        )
    report = evaluate(reliable_holdout, runs)
    evidence = {
        "case_count": len(reliable_holdout),
        "filter_checked_hit_count": report["filter_checked_hit_count"],
        "filter_metadata_missing_count": report["filter_metadata_missing_count"],
    }
    if report["filter_checked_hit_count"] == 0:
        return {
            "status": "not_applicable",
            "reason": "no_filter_checked_hits",
            **evidence,
        }
    if report["filter_metadata_missing_count"]:
        raise ValueError(
            "reliably annotated holdout hit is missing merchant_code or policy_version; "
            f"missing metadata on {report['filter_metadata_missing_count']} hit(s)"
        )
    if report["filter_violation_rate"] != 0.0:
        raise ValueError(
            "reliably annotated holdout filter_violation_rate must equal 0; "
            f"got {report['filter_violation_rate']}"
        )
    return {"status": "passed", "filter_violation_rate": 0.0, **evidence}
