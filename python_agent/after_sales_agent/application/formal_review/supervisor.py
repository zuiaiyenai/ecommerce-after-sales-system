from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from .contracts import (
    EvidenceAssessment,
    PolicyAssessment,
    ReviewProposal,
    SupervisorPlan,
    TrustedCaseContext,
)


class JsonLlm(Protocol):
    def chat_json(self, **kwargs: Any) -> dict[str, Any]:
        ...


@dataclass
class ControlledSupervisor:
    llm: JsonLlm

    def plan(
        self,
        context: TrustedCaseContext,
        issue: str,
    ) -> SupervisorPlan:
        raw = self.llm.chat_json(
            system_prompt=(
                "你是售后多专家系统的中心 Supervisor。只负责选择 POLICY、EVIDENCE、"
                "EMOTION、HANDOFF_SUMMARY 专家，不执行任何业务写入。"
                "只输出 JSON：action、specialists、policy_query、reason_codes。"
            ),
            user_prompt=json.dumps({
                "issue": issue,
                "mode": "formal_review",
                "ticket_status": context.ticket_status,
                "has_attachments": bool(context.attachments),
                "product_name": context.product_name,
                "product_category": context.product_category,
                "after_sales_type": context.after_sales_type,
            }, ensure_ascii=False),
            temperature=0.1,
            max_tokens=300,
        )
        requested = {
            str(item).strip().upper()
            for item in raw.get("specialists") or []
        }
        allowed = {"POLICY", "EVIDENCE", "EMOTION", "HANDOFF_SUMMARY"}
        specialists = requested.intersection(allowed)
        # Formal review always requires authoritative policy assessment. Image
        # evidence also requires the isolated evidence specialist.
        specialists.add("POLICY")
        if context.attachments:
            specialists.add("EVIDENCE")
        # Keep the rerank query natural and concise. Category, after-sales type,
        # merchant and policy version remain structured hard filters downstream.
        trusted_fact_query = " ".join(
            dict.fromkeys(
                item
                for item in (
                    issue,
                    context.product_name,
                )
                if item
            )
        )
        query = trusted_fact_query or str(raw.get("policy_query") or "").strip()
        return SupervisorPlan(
            action="DISPATCH_SPECIALISTS",
            specialists=tuple(sorted(specialists)),
            policy_query=query[:500],
            reason_codes=tuple(
                str(item) for item in raw.get("reason_codes") or []
                if str(item or "").strip()
            ),
        )

    def synthesize(
        self,
        context: TrustedCaseContext,
        issue: str,
        policy: PolicyAssessment,
        evidence: EvidenceAssessment,
    ) -> ReviewProposal:
        raw = self.llm.chat_json(
            system_prompt=(
                "你是售后多专家系统的中心 Supervisor。综合政策与凭证专家的结构化输出，"
                "提出 APPROVE、MANUAL_REVIEW_REQUIRED 之一。你只能提出审核提案，"
                "真实状态以业务系统返回为准。只输出 JSON：proposed_verdict、reason、"
                "confidence、risk_reasons、assistant_reply。不得添加输入中不存在的事实。"
            ),
            user_prompt=json.dumps({
                "issue": issue,
                "trusted_context": {
                    "ticket_status": context.ticket_status,
                    "policy_version": context.policy_version,
                    "context_version": context.context_version,
                },
                "policy_assessment": policy.to_dict(),
                "evidence_assessment": evidence.to_dict(),
            }, ensure_ascii=False, default=str),
            temperature=0.1,
            max_tokens=500,
        )
        verdict = str(raw.get("proposed_verdict") or "").strip().upper()
        if verdict not in {"APPROVE", "MANUAL_REVIEW_REQUIRED"}:
            verdict = "MANUAL_REVIEW_REQUIRED"
        try:
            confidence = max(0.0, min(float(raw.get("confidence") or 0.0), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            reason = "专家结果存在不确定性，建议人工复核。"
        reply = str(raw.get("assistant_reply") or "").strip()
        if not reply:
            reply = "您的售后申请已完成智能初审，实际处理结果以系统审核状态为准。"
        return ReviewProposal(
            proposed_verdict=verdict,
            reason=reason[:500],
            confidence=0.0,
            risk_reasons=tuple(
                str(item) for item in raw.get("risk_reasons") or []
                if str(item or "").strip()
            ),
            assistant_reply=reply[:500],
            model_confidence=confidence,
        )
