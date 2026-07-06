from __future__ import annotations

from dataclasses import dataclass

from ..models import AfterSalesRequest, EvidenceCheckResult, Intent, Order, RiskAssessmentResult, RiskLevel


@dataclass(frozen=True)
class RiskAgent:
    def assess(
        self,
        order: Order | None,
        request: AfterSalesRequest,
        intent: Intent,
        evidence: EvidenceCheckResult,
    ) -> RiskAssessmentResult:
        if order is None:
            return RiskAssessmentResult(
                risk_level=RiskLevel.HIGH,
                allow_auto_refund=False,
                need_human_review=True,
                reason="缺少订单信息，必须人工确认。",
                score=90,
            )

        score = 50
        reasons: list[str] = []
        if order.amount < 50:
            score -= 20
            reasons.append("订单金额较低")
        elif order.amount > 300:
            score += 25
            reasons.append("订单金额较高")

        if evidence.evidence_complete:
            score -= 15
            reasons.append("凭证较完整")
        else:
            score += 20
            reasons.append("凭证不完整")

        if order.user_after_sales_count >= 3:
            score += 20
            reasons.append("历史售后次数较多")
        if intent == Intent.REFUND_ONLY:
            score += 20
            reasons.append("申请仅退款")
        if order.merchant_rejected_before or intent == Intent.MERCHANT_REJECTED:
            score += 15
            reasons.append("存在商家拒绝记录")
        if intent == Intent.RETURN_LOGISTICS and order.logistics_status in {"异常", "待确认"}:
            score += 10
            reasons.append("物流责任待确认")

        if score <= 35:
            risk_level = RiskLevel.LOW
        elif score <= 70:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.HIGH

        allow_auto_refund = (
            risk_level == RiskLevel.LOW
            and evidence.evidence_complete
            and order.amount < 50
            and intent == Intent.REFUND_ONLY
        )
        need_human_review = risk_level != RiskLevel.LOW or not evidence.evidence_complete
        return RiskAssessmentResult(
            risk_level=risk_level,
            allow_auto_refund=allow_auto_refund,
            need_human_review=need_human_review,
            reason="；".join(reasons) or "规则命中较少，按常规流程处理。",
            score=score,
        )
