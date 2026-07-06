from __future__ import annotations

from dataclasses import dataclass

from ..merchant_policy import MerchantServicePolicy
from ..models import (
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesStatus,
    AgentResult,
    Decision,
    EmotionAnalysisResult,
    EvidenceCheckResult,
    HumanHandoffResult,
    Intent,
    IntentResult,
    Order,
    RiskAssessmentResult,
    StateTransitionResult,
    Ticket,
)
from .return_message_support import (
    apply_emotion_prefix,
    build_audit_note,
    build_progress_hint,
    build_quality_handoff_summary,
    build_quality_issue_auto_approved_progress,
    build_quality_issue_detail_progress,
    build_quality_issue_detail_reply,
    build_quality_issue_visual_handoff_progress,
    build_quality_issue_visual_handoff_reply,
    build_state_reply,
    build_status_answer,
    build_ticket_reply,
)


@dataclass(frozen=True)
class ReturnDecisionContext:
    request: AfterSalesRequest
    order: Order | None
    service_policy: MerchantServicePolicy | None
    intent_result: IntentResult
    scene: AfterSalesScene
    emotion_result: EmotionAnalysisResult
    state_result: StateTransitionResult
    evidence_result: EvidenceCheckResult
    risk_result: RiskAssessmentResult

    @property
    def extracted_order_id(self) -> str | None:
        return self.order.order_id if self.order else self.request.order_id


def build_missing_order_result(
    request: AfterSalesRequest,
    emotion_result: EmotionAnalysisResult,
) -> AgentResult:
    return AgentResult(
        decision=Decision.ASK_FOR_INFO,
        user_reply="请先选择需要处理的订单，我会根据订单状态继续帮您判断售后流程。",
        extracted_order_id=None,
        intent=Intent.GENERAL,
        next_agent="订单识别",
        need_human=False,
        current_status=AfterSalesStatus.NOT_APPLIED,
        scene=AfterSalesScene.GENERAL,
        missing_fields=("订单信息",),
        suggested_action="选择订单",
        audit_note="missing_order_context",
        emotion=emotion_result,
    )


def build_intent_clarification_result(
    request: AfterSalesRequest,
    order: Order | None,
    intent_result: IntentResult,
    scene: AfterSalesScene,
    emotion_result: EmotionAnalysisResult,
) -> AgentResult:
    options_text = "还是".join(intent_result.clarification_options)
    return AgentResult(
        decision=Decision.ASK_FOR_INFO,
        user_reply=apply_emotion_prefix(
            f"您好，我先帮您确认一下，您这次是想{options_text}？",
            emotion_result,
        ),
        extracted_order_id=order.order_id if order else request.order_id,
        intent=intent_result.intent,
        next_agent="意图澄清",
        need_human=False,
        current_status=order.after_sales_status if order else AfterSalesStatus.NOT_APPLIED,
        scene=scene,
        missing_fields=("意图确认",),
        suggested_action="确认问题类型",
        progress_hint="当前问题可能对应多个处理方向，需要先确认。",
        audit_note=f"intent_clarify score={intent_result.score}; options={','.join(intent_result.clarification_options)}",
        emotion=emotion_result,
    )


def build_intent_fallback_result(
    request: AfterSalesRequest,
    order: Order | None,
    intent_result: IntentResult,
    scene: AfterSalesScene,
    emotion_result: EmotionAnalysisResult,
) -> AgentResult:
    return AgentResult(
        decision=Decision.ASK_FOR_INFO,
        user_reply=apply_emotion_prefix(
            "您好，为了更快帮您处理，请再说明一下您是想申请售后、查询进度，还是联系人工客服。",
            emotion_result,
        ),
        extracted_order_id=order.order_id if order else request.order_id,
        intent=Intent.GENERAL,
        next_agent="普通咨询",
        need_human=False,
        current_status=order.after_sales_status if order else AfterSalesStatus.NOT_APPLIED,
        scene=scene,
        missing_fields=("问题类型",),
        suggested_action="补充问题描述",
        progress_hint="当前信息不足，暂时无法稳定判断问题类型。",
        audit_note=f"intent_fallback score={intent_result.score}",
        emotion=emotion_result,
    )


def build_handoff_result(
    ctx: ReturnDecisionContext,
    handoff_result: HumanHandoffResult,
) -> AgentResult:
    return AgentResult(
        decision=Decision.ESCALATE_HUMAN,
        user_reply="已为您转接人工客服，请稍等。",
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent="人工客服",
        need_human=True,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        missing_fields=ctx.evidence_result.missing_items,
        risk_level=ctx.risk_result.risk_level,
        suggested_action="转接人工客服",
        progress_hint=handoff_result.reason,
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        handoff_summary=handoff_result.summary,
        emotion=ctx.emotion_result,
    )


def build_state_blocked_result(ctx: ReturnDecisionContext) -> AgentResult:
    return AgentResult(
        decision=Decision.RESPOND,
        user_reply=apply_emotion_prefix(
            build_state_reply(ctx.state_result.current_status, service_policy=ctx.service_policy),
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent=ctx.intent_result.next_agent,
        need_human=False,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        risk_level=ctx.risk_result.risk_level,
        suggested_action="按当前状态继续处理",
        progress_hint=ctx.state_result.reason,
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_supplement_recorded_result(ctx: ReturnDecisionContext) -> AgentResult:
    return AgentResult(
        decision=Decision.RESPOND,
        user_reply=apply_emotion_prefix(
            "您好，已收到您补充的凭证材料，当前售后申请处于待审核状态，我会继续为您保留材料并等待审核结果。",
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent=ctx.intent_result.next_agent,
        need_human=False,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        risk_level=ctx.risk_result.risk_level,
        suggested_action="等待审核",
        progress_hint="补充材料已记录，待审核期间仍可继续补充凭证。",
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_evidence_needed_result(ctx: ReturnDecisionContext) -> AgentResult:
    return AgentResult(
        decision=Decision.ASK_FOR_INFO,
        user_reply=apply_emotion_prefix(ctx.evidence_result.suggestion, ctx.emotion_result),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent="证据检查",
        need_human=False,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        missing_fields=ctx.evidence_result.missing_items,
        risk_level=ctx.risk_result.risk_level,
        suggested_action="补充必要信息",
        progress_hint="材料补齐后可继续审核。",
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_status_result(ctx: ReturnDecisionContext) -> AgentResult:
    return AgentResult(
        decision=Decision.RESPOND,
        user_reply=build_status_answer(
            ctx.order,
            ctx.state_result.current_status,
            ctx.risk_result.risk_level,
            ctx.request,
            ctx.emotion_result,
            service_policy=ctx.service_policy,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent=ctx.intent_result.next_agent,
        need_human=False,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        risk_level=ctx.risk_result.risk_level,
        suggested_action="查看当前进度",
        progress_hint=build_progress_hint(
            ctx.order,
            ctx.state_result.current_status,
            service_policy=ctx.service_policy,
        ),
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_default_ticket_result(ctx: ReturnDecisionContext, ticket: Ticket) -> AgentResult:
    return AgentResult(
        decision=Decision.CREATE_TICKET,
        user_reply=apply_emotion_prefix(
            build_ticket_reply(ticket, ctx.risk_result, ctx.scene, service_policy=ctx.service_policy),
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent=ctx.intent_result.next_agent,
        need_human=ctx.risk_result.need_human_review,
        current_status=ctx.state_result.suggested_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        risk_level=ctx.risk_result.risk_level,
        ticket=ticket,
        suggested_action=ticket.next_action,
        progress_hint="已进入常规售后审核流程。",
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_human_service_auto_approved_result(
    ctx: ReturnDecisionContext,
    ticket: Ticket,
) -> AgentResult:
    return AgentResult(
        decision=Decision.CREATE_TICKET,
        user_reply=apply_emotion_prefix(
            f"您好，已根据您上传的凭证自动审核通过，当前售后申请 {ticket.ticket_id} 已进入处理中状态。",
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=Intent.HUMAN_SERVICE,
        next_agent="自动审核",
        need_human=False,
        current_status=ctx.state_result.suggested_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        risk_level=ctx.risk_result.risk_level,
        ticket=ticket,
        suggested_action=ticket.next_action,
        progress_hint="图片核验通过，已自动审核并进入处理中状态。",
        audit_note=build_audit_note(Intent.HUMAN_SERVICE, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_human_service_missing_info_result(ctx: ReturnDecisionContext) -> AgentResult:
    missing_items = ctx.evidence_result.missing_items or ("问题描述",)
    return AgentResult(
        decision=Decision.ASK_FOR_INFO,
        user_reply=apply_emotion_prefix(
            f"您好，为了尽快帮您转接人工客服，请先补充{'、'.join(missing_items)}。",
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=Intent.HUMAN_SERVICE,
        next_agent="信息补充",
        need_human=False,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        missing_fields=missing_items,
        risk_level=ctx.risk_result.risk_level,
        suggested_action="补充必要信息后转人工",
        progress_hint="补充必要信息后可继续为您转接人工客服。",
        audit_note=build_audit_note(Intent.HUMAN_SERVICE, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_quality_issue_detail_result(ctx: ReturnDecisionContext) -> AgentResult:
    return AgentResult(
        decision=Decision.ASK_FOR_INFO,
        user_reply=apply_emotion_prefix(
            build_quality_issue_detail_reply(service_policy=ctx.service_policy),
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent="信息补充",
        need_human=False,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        missing_fields=("问题描述",),
        risk_level=ctx.risk_result.risk_level,
        suggested_action="补充异常描述",
        progress_hint=build_quality_issue_detail_progress(service_policy=ctx.service_policy),
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_quality_issue_visual_handoff_result(ctx: ReturnDecisionContext) -> AgentResult:
    summary = build_quality_handoff_summary(ctx.order, ctx.request, ctx.risk_result, ctx.emotion_result)
    return AgentResult(
        decision=Decision.ESCALATE_HUMAN,
        user_reply=apply_emotion_prefix(
            build_quality_issue_visual_handoff_reply(service_policy=ctx.service_policy),
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent="人工客服",
        need_human=True,
        current_status=ctx.state_result.current_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        risk_level=ctx.risk_result.risk_level,
        suggested_action="转人工核实功能异常",
        progress_hint=build_quality_issue_visual_handoff_progress(service_policy=ctx.service_policy),
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        handoff_summary=summary,
        emotion=ctx.emotion_result,
    )


def build_quality_issue_ticket_result(
    ctx: ReturnDecisionContext,
    ticket: Ticket,
    *,
    next_agent: str,
    force_auto_approve: bool,
) -> AgentResult:
    return AgentResult(
        decision=Decision.CREATE_TICKET,
        user_reply=apply_emotion_prefix(
            build_ticket_reply(ticket, ctx.risk_result, ctx.scene, service_policy=ctx.service_policy),
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent="自动审核" if force_auto_approve else next_agent,
        need_human=False,
        current_status=ctx.state_result.suggested_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        risk_level=ctx.risk_result.risk_level,
        ticket=ticket,
        suggested_action=ticket.next_action,
        progress_hint=(
            build_quality_issue_auto_approved_progress(service_policy=ctx.service_policy)
            if force_auto_approve
            else "已记录具体异常描述，进入常规售后审核流程。"
        ),
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )


def build_package_damage_ticket_result(
    ctx: ReturnDecisionContext,
    ticket: Ticket,
) -> AgentResult:
    return AgentResult(
        decision=Decision.CREATE_TICKET,
        user_reply=apply_emotion_prefix(
            build_ticket_reply(ticket, ctx.risk_result, ctx.scene, service_policy=ctx.service_policy),
            ctx.emotion_result,
        ),
        extracted_order_id=ctx.extracted_order_id,
        intent=ctx.intent_result.intent,
        next_agent=ctx.intent_result.next_agent,
        need_human=ctx.risk_result.need_human_review,
        current_status=ctx.state_result.suggested_status,
        scene=ctx.scene,
        allowed_actions=ctx.state_result.allowed_actions,
        missing_fields=ctx.evidence_result.missing_items,
        risk_level=ctx.risk_result.risk_level,
        ticket=ticket,
        suggested_action=ticket.next_action,
        progress_hint="已进入包装破损评估流程。",
        audit_note=build_audit_note(ctx.intent_result.intent, ctx.risk_result),
        emotion=ctx.emotion_result,
    )
