from __future__ import annotations

from ..models import (
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesStatus,
    AgentResult,
    Intent,
    Order,
)
from .policies import PolicyEngine
from .return_decision_support import (
    ReturnDecisionContext,
    build_default_ticket_result,
    build_evidence_needed_result,
    build_handoff_result,
    build_human_service_auto_approved_result,
    build_human_service_missing_info_result,
    build_intent_clarification_result,
    build_intent_fallback_result,
    build_missing_order_result,
    build_package_damage_ticket_result,
    build_quality_issue_detail_result,
    build_quality_issue_ticket_result,
    build_quality_issue_visual_handoff_result,
    build_state_blocked_result,
    build_status_result,
    build_supplement_recorded_result,
)
from .return_ticket_support import build_ticket, has_detailed_quality_description


class ReturnAgent:
    def __init__(self, policy_engine: PolicyEngine | None = None) -> None:
        self.policy_engine = policy_engine or PolicyEngine()

    def handle(self, request: AfterSalesRequest, order: Order | None) -> AgentResult:
        if order is None and request.order_id is None:
            emotion_result = self.policy_engine.analyze_emotion(request, order)
            return build_missing_order_result(request, emotion_result)

        policy_resolution = self.policy_engine.resolve_policy(request, order)
        service_policy = policy_resolution.service_policy
        knowledge_base = policy_resolution.knowledge_base

        intent_result = self.policy_engine.classify_intent(request, order)
        scene = self.policy_engine.intent_agent.infer_scene_enum(request, intent_result.intent)
        emotion_result = self.policy_engine.analyze_emotion(
            request,
            order,
            service_policy=service_policy,
            knowledge_base=knowledge_base,
        )

        if intent_result.needs_clarification:
            return build_intent_clarification_result(
                request,
                order,
                intent_result,
                scene,
                emotion_result,
            )

        if intent_result.fallback:
            return build_intent_fallback_result(
                request,
                order,
                intent_result,
                scene,
                emotion_result,
            )

        state_result = self.policy_engine.evaluate_state(
            order,
            intent_result.intent,
            service_policy=service_policy,
        )
        evidence_result = self.policy_engine.check_evidence(
            order,
            request,
            intent_result.intent,
            service_policy=service_policy,
            knowledge_base=knowledge_base,
        )
        risk_result = self.policy_engine.assess_risk(order, request, intent_result.intent, evidence_result)
        handoff_result = self.policy_engine.evaluate_handoff(
            order,
            request,
            intent_result,
            risk_result,
            evidence_result,
            emotion_result,
        )

        ctx = ReturnDecisionContext(
            request=request,
            order=order,
            service_policy=service_policy,
            intent_result=intent_result,
            scene=scene,
            emotion_result=emotion_result,
            state_result=state_result,
            evidence_result=evidence_result,
            risk_result=risk_result,
        )

        if handoff_result.triggered:
            return build_handoff_result(ctx, handoff_result)

        if intent_result.intent == Intent.HUMAN_SERVICE:
            return self._handle_human_service(ctx)

        if not state_result.allowed:
            return build_state_blocked_result(ctx)

        if (
            intent_result.intent == Intent.SUPPLEMENT_EVIDENCE
            and state_result.current_status != AfterSalesStatus.NOT_APPLIED
        ):
            return build_supplement_recorded_result(ctx)

        if not evidence_result.evidence_complete and intent_result.intent in {
            Intent.APPLY_AFTER_SALES,
            Intent.SUPPLEMENT_EVIDENCE,
            Intent.MERCHANT_REJECTED,
            Intent.EXCHANGE_REPAIR,
            Intent.REFUND_ONLY,
        }:
            return build_evidence_needed_result(ctx)

        if intent_result.intent in {Intent.REFUND_PROGRESS, Intent.RETURN_LOGISTICS, Intent.GENERAL}:
            return build_status_result(ctx)

        special_scene_result = self._handle_special_scene(ctx)
        if special_scene_result is not None:
            return special_scene_result

        ticket = build_ticket(
            order,
            request,
            intent_result.intent,
            risk_result,
            scene,
            service_policy=service_policy,
        )
        return build_default_ticket_result(ctx, ticket)

    def _handle_human_service(self, ctx: ReturnDecisionContext) -> AgentResult:
        if (
            ctx.evidence_result.evidence_complete
            and not ctx.request.visual_review_failed
            and ctx.request.visual_evidence
        ):
            ticket = build_ticket(
                ctx.order,
                ctx.request,
                Intent.HUMAN_SERVICE,
                ctx.risk_result,
                ctx.scene,
                service_policy=ctx.service_policy,
                force_auto_approve=True,
            )
            return build_human_service_auto_approved_result(ctx, ticket)
        return build_human_service_missing_info_result(ctx)

    def _handle_special_scene(self, ctx: ReturnDecisionContext) -> AgentResult | None:
        if ctx.intent_result.intent not in {
            Intent.APPLY_AFTER_SALES,
            Intent.REFUND_ONLY,
            Intent.EXCHANGE_REPAIR,
        }:
            return None

        if ctx.scene == AfterSalesScene.QUALITY_ISSUE:
            return self._handle_quality_issue_scene(ctx)

        if ctx.scene == AfterSalesScene.PACKAGE_DAMAGE:
            ticket = build_ticket(
                ctx.order,
                ctx.request,
                ctx.intent_result.intent,
                ctx.risk_result,
                ctx.scene,
                service_policy=ctx.service_policy,
            )
            return build_package_damage_ticket_result(ctx, ticket)

        return None

    def _handle_quality_issue_scene(self, ctx: ReturnDecisionContext) -> AgentResult:
        if not has_detailed_quality_description(ctx.request):
            return build_quality_issue_detail_result(ctx)

        if ctx.request.visual_review_failed or (ctx.request.attachments and not ctx.request.visual_evidence):
            return build_quality_issue_visual_handoff_result(ctx)

        force_auto_approve = (
            bool(ctx.request.visual_evidence)
            and bool(ctx.service_policy.supports_auto_approve if ctx.service_policy else True)
            and bool(ctx.service_policy.allow_visual_auto_approve if ctx.service_policy else True)
        )
        ticket = build_ticket(
            ctx.order,
            ctx.request,
            ctx.intent_result.intent,
            ctx.risk_result,
            ctx.scene,
            service_policy=ctx.service_policy,
            force_auto_approve=force_auto_approve,
        )
        return build_quality_issue_ticket_result(
            ctx,
            ticket,
            next_agent=ctx.intent_result.next_agent,
            force_auto_approve=force_auto_approve,
        )
