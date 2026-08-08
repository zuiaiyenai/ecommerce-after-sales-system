from __future__ import annotations

from dataclasses import replace

from .contracts import EvidenceAssessment, PolicyAssessment, ReviewProposal


CONFIDENCE_MODEL_VERSION = "deterministic-v1"
CONFIDENCE_KIND = "deterministic_decision_support"

_POLICY_RELEVANCE_WEIGHT = 0.35
_VISUAL_CONFIDENCE_WEIGHT = 0.30
_POLICY_INTEGRITY_WEIGHT = 0.20
_EVIDENCE_INTEGRITY_WEIGHT = 0.15


def apply_deterministic_confidence(
    proposal: ReviewProposal,
    policy: PolicyAssessment,
    evidence: EvidenceAssessment,
) -> ReviewProposal:
    """Replace uncalibrated LLM self-confidence with traceable review signals.

    This score is a deterministic decision-support score, not an empirically
    calibrated probability of correctness. The raw model value is retained
    separately for auditing and has no authority over the business gate.
    """

    policy_relevance = _score(policy.policy_match_score)
    visual_confidence = _score(evidence.visual_confidence)
    policy_integrity = float(
        policy.success
        and policy.trusted_policy_eligible
        and policy.policy_version_matched
        and policy.filter_level == "strict"
        and policy.reranker_succeeded
        and bool(policy.citations)
    )
    evidence_integrity = float(
        evidence.success
        and evidence.visual_verifiable
        and evidence.evidence_consistent is True
        and not evidence.missing_evidence
        and not evidence.risk_signals
    )
    contributions = {
        "policy_relevance": round(
            policy_relevance * _POLICY_RELEVANCE_WEIGHT,
            4,
        ),
        "visual_confidence": round(
            visual_confidence * _VISUAL_CONFIDENCE_WEIGHT,
            4,
        ),
        "policy_integrity": round(
            policy_integrity * _POLICY_INTEGRITY_WEIGHT,
            4,
        ),
        "evidence_integrity": round(
            evidence_integrity * _EVIDENCE_INTEGRITY_WEIGHT,
            4,
        ),
    }
    confidence = round(min(sum(contributions.values()), 1.0), 4)
    breakdown = {
        "kind": CONFIDENCE_KIND,
        "model_version": CONFIDENCE_MODEL_VERSION,
        "calibration_status": "rule_based_uncalibrated",
        "signals": {
            "policy_relevance": policy_relevance,
            "policy_threshold": _score(policy.policy_threshold),
            "visual_confidence": visual_confidence,
            "policy_integrity": policy_integrity,
            "evidence_integrity": evidence_integrity,
        },
        "weights": {
            "policy_relevance": _POLICY_RELEVANCE_WEIGHT,
            "visual_confidence": _VISUAL_CONFIDENCE_WEIGHT,
            "policy_integrity": _POLICY_INTEGRITY_WEIGHT,
            "evidence_integrity": _EVIDENCE_INTEGRITY_WEIGHT,
        },
        "contributions": contributions,
    }
    return replace(
        proposal,
        confidence=confidence,
        confidence_model_version=CONFIDENCE_MODEL_VERSION,
        confidence_breakdown=breakdown,
    )


def _score(value: object) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0
