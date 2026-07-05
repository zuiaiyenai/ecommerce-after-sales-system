from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from ..models import (
    AfterSalesScene,
    AgentResult,
    Decision,
    DecisionContext,
    DecisionEnvelope,
    DescriptionSufficiencyResult,
    EmotionAnalysisResult,
    Intent,
    RiskAssessmentResult,
    StateTransitionResult,
    Ticket,
)
from .return_message_support import (
    apply_emotion_prefix,
    build_audit_note,
    build_quality_handoff_summary,
    build_quality_issue_auto_approved_progress,
    build_quality_issue_detail_progress,
    build_quality_issue_detail_reply,
    build_quality_issue_visual_handoff_progress,
    build_quality_issue_visual_handoff_reply,
    build_ticket_reply,
)


def handle_scene_specific_flow(
    *,
    context: DecisionContext,
    intent: Intent,
    scene: AfterSalesScene,
    state_result: StateTransitionResult,
    description_result: DescriptionSufficiencyResult,
    evidence_result: Any,
    risk_result: RiskAssessmentResult,
    next_agent: str,
    emotion_result: EmotionAnalysisResult,
    plan_ticket: Callable[..., Ticket],
) -> DecisionEnvelope | None:
    request = context.request
    order = context.order
    policy = context.resolved_policy

    if intent not in {Intent.APPLY_AFTER_SALES, Intent.REFUND_ONLY, Intent.EXCHANGE_REPAIR}:
        return None

    if scene == AfterSalesScene.QUALITY_ISSUE:
        if not description_result.sufficient:
            result = AgentResult(
                decision=Decision.ASK_FOR_INFO,
                user_reply=apply_emotion_prefix(
                    build_quality_issue_detail_reply(service_policy=context.resolved_policy),
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent,
                next_agent="信息补充",
                need_human=False,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                missing_fields=description_result.missing_items or ("问题描述",),
                risk_level=risk_result.risk_level,
                suggested_action="补充异常描述",
                progress_hint=build_quality_issue_detail_progress(service_policy=context.resolved_policy),
                audit_note=(
                    f"{build_audit_note(intent, risk_result)}; "
                    f"description_reason={description_result.reason}; "
                    f"description_source={description_result.source}"
                ),
                emotion=emotion_result,
                service_policy=context.resolved_policy,
            )
            return DecisionEnvelope(context=context, result=result)

        if request.visual_review_failed or (request.attachments and not request.visual_evidence):
            summary = build_quality_handoff_summary(order, request, risk_result, emotion_result)
            result = AgentResult(
                decision=Decision.ESCALATE_HUMAN,
                user_reply=apply_emotion_prefix(
                    build_quality_issue_visual_handoff_reply(service_policy=context.resolved_policy),
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent,
                next_agent="人工客服",
                need_human=True,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                missing_fields=(),
                risk_level=risk_result.risk_level,
                suggested_action="转人工核实功能异常",
                progress_hint=build_quality_issue_visual_handoff_progress(service_policy=context.resolved_policy),
                audit_note=(
                    f"{build_audit_note(intent, risk_result)}; "
                    f"description_reason={description_result.reason}; "
                    f"description_source={description_result.source}"
                ),
                handoff_summary=summary,
                emotion=emotion_result,
                service_policy=context.resolved_policy,
            )
            return DecisionEnvelope(context=context, result=result)

        force_auto_approve = (
            policy.supports_auto_approve
            and bool(request.visual_evidence)
            and policy.allow_visual_auto_approve
        )
        ticket = plan_ticket(
            context,
            intent,
            scene,
            risk_result,
            force_auto_approve=force_auto_approve,
        )
        updated_context = replace(context, ticket=ticket)
        result = AgentResult(
            decision=Decision.CREATE_TICKET,
            user_reply=apply_emotion_prefix(
                build_ticket_reply(ticket, risk_result, scene, service_policy=context.resolved_policy),
                emotion_result,
            ),
            extracted_order_id=order.order_id if order else request.order_id,
            intent=intent,
            next_agent="自动审核" if force_auto_approve else next_agent,
            need_human=False,
            current_status=state_result.suggested_status,
            scene=scene,
            allowed_actions=state_result.allowed_actions,
            missing_fields=(),
            risk_level=risk_result.risk_level,
            ticket=ticket,
            suggested_action=ticket.next_action,
            progress_hint=(
                build_quality_issue_auto_approved_progress(service_policy=context.resolved_policy)
                if force_auto_approve
                else "已记录具体异常描述，进入常规售后审核流程。"
            ),
            audit_note=(
                f"{build_audit_note(intent, risk_result)}; "
                f"description_reason={description_result.reason}; "
                f"description_source={description_result.source}"
            ),
            emotion=emotion_result,
            service_policy=context.resolved_policy,
        )
        return DecisionEnvelope(context=updated_context, result=result)

    if scene == AfterSalesScene.PACKAGE_DAMAGE:
        ticket = plan_ticket(
            context,
            intent,
            scene,
            risk_result,
        )
        updated_context = replace(context, ticket=ticket)
        result = AgentResult(
            decision=Decision.CREATE_TICKET,
            user_reply=apply_emotion_prefix(
                build_ticket_reply(ticket, risk_result, scene, service_policy=context.resolved_policy),
                emotion_result,
            ),
            extracted_order_id=order.order_id if order else request.order_id,
            intent=intent,
            next_agent=next_agent,
            need_human=risk_result.need_human_review,
            current_status=state_result.suggested_status,
            scene=scene,
            allowed_actions=state_result.allowed_actions,
            missing_fields=evidence_result.missing_items,
            risk_level=risk_result.risk_level,
            ticket=ticket,
            suggested_action=ticket.next_action,
            progress_hint="已进入包装破损赔付评估流程。",
            audit_note=build_audit_note(intent, risk_result),
            emotion=emotion_result,
            service_policy=context.resolved_policy,
        )
        return DecisionEnvelope(context=updated_context, result=result)

    return None
