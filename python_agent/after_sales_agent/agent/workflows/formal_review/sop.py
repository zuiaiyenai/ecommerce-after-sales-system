from __future__ import annotations

from dataclasses import dataclass

from .evaluators import is_core_evidence_requirement
from .contracts import (
    EvidenceAssessment,
    PolicyAssessment,
    ReviewProposal,
    ReviewWorkflowPlan,
    TrustedCaseContext,
)


SOP_REVIEW_MODE = "SOP_AUTOMATED"
ESCALATED_REVIEW_MODE = "COMPLEX_SKILL_REVIEW"


@dataclass(frozen=True)
class EscalationDecision:
    required: bool
    reasons: tuple[str, ...] = ()


class FormalReviewSop:
    """Deterministic orchestration policy for the routine review path."""

    @staticmethod
    def plan(context: TrustedCaseContext, issue: str) -> ReviewWorkflowPlan:
        query = " ".join(
            dict.fromkeys(
                value
                for value in (issue.strip(), context.product_name)
                if value
            )
        )
        return ReviewWorkflowPlan(
            action="RUN_REVIEW_SKILLS",
            specialists=("EVIDENCE", "POLICY"),
            policy_query=query[:500],
            reason_codes=("FORMAL_REVIEW_SOP",),
        )

    @staticmethod
    def assess_escalation(
        policy: PolicyAssessment,
        evidence: EvidenceAssessment,
        *,
        minimum_review_confidence: float,
    ) -> EscalationDecision:
        reasons: list[str] = []
        if not policy.success:
            reasons.append("policy_skill_failed")
        if not policy.trusted_policy_eligible or not policy.policy_version_matched:
            reasons.append("policy_not_authoritative")
        if (
            policy.filter_level != "strict"
            or (
                not policy.reranker_succeeded
                and policy.retrieval_mode != "multi_query_rrf"
            )
            or not policy.citations
        ):
            reasons.append("policy_retrieval_insufficient")
        if evidence.risk_signals or evidence.evidence_consistent is False:
            reasons.append("evidence_conflict")
        if not evidence.success:
            reasons.append("evidence_skill_failed")
        elif (
            not evidence.visual_verifiable
            or evidence.visual_confidence < minimum_review_confidence
        ):
            reasons.append("visual_evidence_uncertain")
        if any(
            is_core_evidence_requirement(item)
            for item in evidence.missing_evidence
        ):
            reasons.append("core_evidence_missing")
        return EscalationDecision(
            required=bool(reasons),
            reasons=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def build_routine_proposal(
        policy: PolicyAssessment,
        evidence: EvidenceAssessment,
    ) -> ReviewProposal:
        approvable = bool(
            policy.success
            and policy.trusted_policy_eligible
            and policy.policy_version_matched
            and evidence.success
            and evidence.visual_verifiable
            and evidence.evidence_consistent is True
            and not evidence.risk_signals
        )
        return ReviewProposal(
            proposed_verdict=("APPROVE" if approvable else "MANUAL_REVIEW_REQUIRED"),
            reason=(
                "Policy and evidence checks satisfy the automated review SOP."
                if approvable
                else "The automated review SOP could not establish a reliable result."
            ),
            confidence=0.0,
            risk_reasons=(),
            assistant_reply=(
                "The automated initial review is complete."
                if approvable
                else "The request has been routed for manual review."
            ),
            model_confidence=0.0,
        )
