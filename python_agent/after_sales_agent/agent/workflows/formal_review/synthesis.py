from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from .contracts import (
    EvidenceAssessment,
    PolicyAssessment,
    ReviewProposal,
    TrustedCaseContext,
)


class JsonLlm(Protocol):
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...


_SYNTHESIZE_SCHEMA = {
    "type": "object",
    "required": [
        "proposed_verdict",
        "reason",
        "confidence",
        "risk_reasons",
        "assistant_reply",
    ],
    "properties": {
        "proposed_verdict": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
        "risk_reasons": {"type": "array", "items": {"type": "string"}},
        "assistant_reply": {"type": "string"},
    },
}


@dataclass
class ComplexReviewSynthesizer:
    """仅综合复杂案例，不负责 Skill 调度或最终业务决策。"""

    llm: JsonLlm

    def synthesize(
        self,
        context: TrustedCaseContext,
        issue: str,
        policy: PolicyAssessment,
        evidence: EvidenceAssessment,
    ) -> ReviewProposal:
        raw = self.llm.generate_structured(
            system_prompt=(
                "你是正式售后审核 Skill 内的复杂案例综合节点。"
                "只综合政策与凭证工作流的结构化结果，提出 APPROVE 或 "
                "MANUAL_REVIEW_REQUIRED 建议。不得执行工具、修改业务状态或绕过"
                "确定性 Gate。只输出 JSON：proposed_verdict、reason、confidence、"
                "risk_reasons、assistant_reply。不得添加输入中不存在的事实。"
            ),
            user_prompt=json.dumps(
                {
                    "issue": issue,
                    "trusted_context": {
                        "ticket_status": context.ticket_status,
                        "policy_version": context.policy_version,
                        "context_version": context.context_version,
                    },
                    "policy_assessment": policy.to_dict(),
                    "evidence_assessment": evidence.to_dict(),
                },
                ensure_ascii=False,
                default=str,
            ),
            schema=_SYNTHESIZE_SCHEMA,
            temperature=0.1,
            max_tokens=500,
        )
        verdict = str(raw.get("proposed_verdict") or "").strip().upper()
        if verdict not in {"APPROVE", "MANUAL_REVIEW_REQUIRED"}:
            verdict = "MANUAL_REVIEW_REQUIRED"
        try:
            confidence = max(
                0.0,
                min(float(raw.get("confidence") or 0.0), 1.0),
            )
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            reason = "工作流结果存在不确定性，建议人工复核。"
        reply = str(raw.get("assistant_reply") or "").strip()
        if not reply:
            reply = "您的售后申请已完成智能初审，实际结果以系统审核状态为准。"
        return ReviewProposal(
            proposed_verdict=verdict,
            reason=reason[:500],
            confidence=0.0,
            risk_reasons=tuple(
                str(item)
                for item in raw.get("risk_reasons") or []
                if str(item or "").strip()
            ),
            assistant_reply=reply[:500],
            model_confidence=confidence,
        )
