from __future__ import annotations

from dataclasses import dataclass

from ..models import (
    AfterSalesRequest,
    AfterSalesStatus,
    EvidenceCheckResult,
    EmotionAnalysisResult,
    HumanHandoffResult,
    Intent,
    IntentResult,
    Order,
    RiskAssessmentResult,
)


@dataclass(frozen=True)
class HandoffAgent:
    def evaluate(
        self,
        order: Order | None,
        request: AfterSalesRequest,
        intent_result: IntentResult,
        risk_result: RiskAssessmentResult,
        evidence_result: EvidenceCheckResult,
        emotion_result: EmotionAnalysisResult,
    ) -> HumanHandoffResult:
        triggered_reason = None
        if intent_result.intent == Intent.HUMAN_SERVICE:
            if request.human_request_count >= 2:
                triggered_reason = "用户连续两次要求人工客服。"
            elif evidence_result.evidence_complete:
                has_images = bool(request.attachments)
                if request.visual_review_failed:
                    # 场景 D：用户已上传图片但视觉模型无法核验 → 转人工
                    triggered_reason = "用户已上传图片凭证但系统无法自动核验，转人工客服进一步核实。"
                elif has_images and request.visual_evidence:
                    # 场景 B：用户上传图片且视觉核验通过，证据完整 → 不转人工，走自动审核流程
                    triggered_reason = None
                else:
                    triggered_reason = "用户已提供必要信息并要求人工客服介入。"
        elif emotion_result.need_human_priority and intent_result.intent in {Intent.COMPLAINT, Intent.GENERAL}:
            triggered_reason = "用户情绪较强烈，建议优先人工跟进。"

        summary = {
            "orderId": order.order_id if order else request.order_id or "unknown",
            "problem": request.message or request.description or "用户发起售后咨询",
            "currentStatus": order.after_sales_status.value if order else AfterSalesStatus.NOT_APPLIED.value,
            "evidence": "、".join(order.uploaded_evidence if order else ()) or "暂无完整凭证",
            "risk": risk_result.risk_level.value,
            "userEmotion": emotion_result.label.value,
            "suggestedAction": triggered_reason or "按常规流程处理",
        }
        return HumanHandoffResult(
            triggered=triggered_reason is not None,
            reason=triggered_reason,
            summary=summary,
        )
