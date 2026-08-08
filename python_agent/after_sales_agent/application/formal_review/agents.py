from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .contracts import EvidenceAssessment, EvidenceTask, PolicyAssessment, PolicyTask
from ..tool_registry import ToolResult


class PolicyRetrievalPort(Protocol):
    def retrieve(self, task: PolicyTask) -> ToolResult:
        ...

    def retrieve_multi(
        self,
        task: PolicyTask,
        queries: tuple[str, ...],
    ) -> ToolResult:
        ...


class EvidenceReviewPort(Protocol):
    def review(self, task: EvidenceTask) -> ToolResult:
        ...


def _score(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def is_core_evidence_requirement(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or any(
        token in text for token in ("外包装", "物流", "面单", "运单", "快递")
    ):
        return False
    return (
        any(token in text for token in ("商品", "问题", "破损", "损坏"))
        and any(token in text for token in ("图片", "照片"))
    )


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = f"{text[:-1]}+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _traceable_citations(hit: dict[str, Any]) -> list[dict[str, Any]]:
    citations = hit.get("citations")
    if not isinstance(citations, list):
        return []
    return [
        dict(item)
        for item in citations
        if isinstance(item, dict)
        and str(item.get("source_code") or "").strip()
        and str(item.get("chunk_id") or item.get("document_id") or "").strip()
    ]


@dataclass
class PolicySpecialist:
    port: PolicyRetrievalPort

    def retrieve(self, task: PolicyTask) -> ToolResult:
        return self.port.retrieve(task)

    def retrieve_multi(
        self,
        task: PolicyTask,
        queries: tuple[str, ...],
    ) -> ToolResult:
        return self.port.retrieve_multi(task, queries)

    def assess(self, task: PolicyTask, result: ToolResult) -> PolicyAssessment:
        if not result.ok or not isinstance(result.data, dict):
            return PolicyAssessment(
                context_version=task.context_version,
                success=False,
                trusted_policy_eligible=False,
                policy_version_matched=False,
                filter_level=None,
                reranker_succeeded=False,
                retrieval_mode=None,
                policy_match_score=0.0,
                uncertainty_reasons=(result.error_category or "policy_tool_failed",),
            )

        knowledge = result.data
        hits = [
            item for item in knowledge.get("hits") or []
            if isinstance(item, dict)
        ]
        trusted_hits: list[dict[str, Any]] = []
        business_time = _parse_time(task.business_time)
        for hit in hits:
            metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            source_type = str(
                hit.get("source_type") or metadata.get("source_type") or ""
            )
            merchant_code = str(
                hit.get("merchant_code") or metadata.get("merchant_code") or ""
            )
            policy_version = str(
                hit.get("policy_version") or metadata.get("policy_version") or ""
            )
            if source_type != "after_sales_policy":
                continue
            if not task.merchant_code or merchant_code != task.merchant_code:
                continue
            if not task.policy_version or policy_version != task.policy_version:
                continue
            if hit.get("trusted_policy_eligible") is not True:
                continue
            if hit.get("relaxation_level") != "strict":
                continue
            if not _traceable_citations(hit):
                continue
            valid_from = _parse_time(hit.get("valid_from") or metadata.get("valid_from"))
            valid_to = _parse_time(hit.get("valid_to") or metadata.get("valid_to"))
            if business_time is not None and valid_from is not None and valid_to is not None:
                if not (valid_from <= business_time < valid_to):
                    continue
            threshold = _score(
                hit.get("threshold")
                or knowledge.get("threshold")
                or 0.55
            )
            hit_score = _score(
                hit.get("calibrated_policy_confidence", hit.get("rerank_score"))
            )
            if hit_score < threshold:
                continue
            trusted_hits.append(hit)

        required_evidence: list[str] = []
        citations: list[dict[str, Any]] = []
        for hit in trusted_hits:
            metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            for item in metadata.get("default_evidence") or []:
                text = str(item or "").strip()
                if text and text not in required_evidence:
                    required_evidence.append(text)
            for citation in _traceable_citations(hit):
                if citation not in citations:
                    citations.append(citation)

        mode = str(knowledge.get("mode") or "")
        filter_level = str(
            knowledge.get("filter_level")
            or knowledge.get("relaxation_level")
            or ""
        ) or None
        reranker_succeeded = knowledge.get("reranker_succeeded") is True
        overall_trusted = knowledge.get("trusted_policy_eligible") is True
        eligible = bool(
            trusted_hits
            and overall_trusted
            and filter_level == "strict"
            and reranker_succeeded
            and mode in {
                "hybrid_reranked",
                "multi_query_reranked",
                "pgvector",
            }
        )
        uncertainty: list[str] = []
        if not eligible:
            uncertainty.append("policy_not_strictly_trusted")
        return PolicyAssessment(
            context_version=task.context_version,
            success=True,
            trusted_policy_eligible=eligible,
            policy_version_matched=bool(trusted_hits),
            filter_level=filter_level,
            reranker_succeeded=reranker_succeeded,
            retrieval_mode=mode or None,
            policy_match_score=max(
                (_score(hit.get("rerank_score")) for hit in trusted_hits),
                default=0.0,
            ),
            policy_threshold=_score(knowledge.get("threshold") or 0.55),
            required_evidence=tuple(required_evidence),
            citations=tuple(citations),
            uncertainty_reasons=tuple(uncertainty),
            raw_summary={"hits_count": len(hits), "trusted_hits_count": len(trusted_hits)},
        )


@dataclass
class EvidenceSpecialist:
    port: EvidenceReviewPort

    def review(self, task: EvidenceTask) -> ToolResult:
        return self.port.review(task)

    def assess(
        self,
        task: EvidenceTask,
        result: ToolResult | None,
        required_evidence: tuple[str, ...] = (),
    ) -> EvidenceAssessment:
        if not task.attachments:
            return EvidenceAssessment(
                context_version=task.context_version,
                success=True,
                visual_verifiable=False,
                evidence_consistent=None,
                visual_confidence=0.0,
                missing_evidence=required_evidence or ("商品问题照片",),
                uncertainty_reasons=("visual_evidence_missing",),
            )
        if result is None or not result.ok or not isinstance(result.data, dict):
            return EvidenceAssessment(
                context_version=task.context_version,
                success=False,
                visual_verifiable=False,
                evidence_consistent=None,
                visual_confidence=0.0,
                missing_evidence=required_evidence,
                uncertainty_reasons=(
                    (result.error_category if result is not None else None)
                    or "vision_tool_failed",
                ),
            )
        review = result.data
        items = [
            item for item in review.get("items") or []
            if isinstance(item, dict)
        ]
        confidence = _score(review.get("confidence"))
        if items:
            confidence = min(
                (_score(item.get("confidence")) for item in items),
                default=confidence,
            )
        item_has_visible_issue = any(
            item.get("issue_visible") is True
            or item.get("contains_damage_area") is True
            for item in items
        )
        has_visible_problem = bool(
            review.get("has_damage_area")
            or review.get("has_visible_issue")
            or item_has_visible_issue
        )
        item_is_relevant = any(
            (
                item.get("contains_damage_area") is True
                or _score(item.get("evidence_relevance")) >= 0.6
            )
            for item in items
            if (
                item.get("issue_visible") is True
                or item.get("contains_damage_area") is True
            )
        )
        evidence_relevant = bool(
            review.get("has_damage_area")
            or review.get("evidence_relevant")
            or item_is_relevant
        )
        tampering_suspected = bool(
            review.get("tampering_suspected")
            or any(item.get("tampering_suspected") is True for item in items)
        )
        contradictory = any(
            str(item.get("evidence_consistency") or "").strip().lower()
            == "contradictory"
            for item in items
        )
        raw_consistency = review.get("evidence_consistent")
        if (
            raw_consistency is False
            or tampering_suspected
            or contradictory
        ):
            evidence_consistent: bool | None = False
        elif raw_consistency is True or (
            has_visible_problem and evidence_relevant
        ):
            evidence_consistent = True
        else:
            evidence_consistent = None
        success = review.get("success") is True
        missing = [
            str(item) for item in review.get("missing_visual_evidence") or []
            if is_core_evidence_requirement(item)
        ]
        visual_verifiable = bool(
            success
            and has_visible_problem
            and evidence_relevant
            and evidence_consistent is True
            and not tampering_suspected
            and not missing
        )
        satisfied = (
            ("商品问题图片", "商品问题照片")
            if visual_verifiable
            else ()
        )
        categories = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in review.get("evidence_categories") or ()
                if str(value).strip()
            )
        )
        observed_issue_types = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in review.get("observed_issue_types") or ()
                if str(value).strip()
            )
        )
        limitations = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in review.get("verification_limitations") or ()
                if str(value).strip()
            )
        )
        unresolved_required = tuple(
            item for item in required_evidence
            if is_core_evidence_requirement(item) and item not in satisfied
        )
        uncertainty: list[str] = []
        risk_signals: list[str] = []
        if not success:
            uncertainty.append("vision_review_failed")
        if evidence_consistent is False:
            uncertainty.append("visual_evidence_inconsistent")
            risk_signals.append("visual_evidence_contradictory")
        if tampering_suspected:
            uncertainty.append("visual_tampering_suspected")
            risk_signals.append("visual_tampering_suspected")
        if limitations:
            uncertainty.append("visual_verification_limited")
        if not visual_verifiable:
            uncertainty.append("visual_problem_not_verified")
        return EvidenceAssessment(
            context_version=task.context_version,
            success=success,
            visual_verifiable=visual_verifiable,
            evidence_consistent=evidence_consistent,
            visual_confidence=confidence,
            satisfied_evidence=satisfied,
            missing_evidence=tuple(dict.fromkeys([*missing, *unresolved_required])),
            risk_signals=tuple(dict.fromkeys(risk_signals)),
            uncertainty_reasons=tuple(uncertainty),
            image_review=dict(review),
            evidence_categories=categories,
            observed_issue_types=observed_issue_types,
            verification_limitations=limitations,
        )
