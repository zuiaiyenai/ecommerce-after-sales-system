from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from ..merchant_policy import MerchantServicePolicy
from ..models import (
    AfterSalesScene,
    AfterSalesType,
    DecisionContext,
    Intent,
    RiskAssessmentResult,
    Ticket,
    TicketStatus,
)


@dataclass(frozen=True)
class TicketPlanner:
    def plan(
        self,
        context: DecisionContext,
        intent: Intent,
        scene: AfterSalesScene,
        risk_result: RiskAssessmentResult,
        *,
        force_auto_approve: bool = False,
    ) -> Ticket:
        request = context.request
        order = context.order
        service_policy = context.resolved_policy.service_policy
        state_policy = service_policy.state_policy
        after_sales_type = self._infer_type(service_policy, intent)
        can_auto_approve = state_policy.supports_auto_approve and (
            risk_result.allow_auto_refund or force_auto_approve
        )
        status = TicketStatus.AUTO_APPROVED if can_auto_approve else TicketStatus.PENDING_REVIEW
        expected_hours = (
            state_policy.auto_review_hours
            if status == TicketStatus.AUTO_APPROVED
            else state_policy.manual_review_hours
        )
        product_name = order.items[0].product_name if order and order.items else "未知商品"
        summary = f"{product_name} 售后申请：{request.message or request.description or '用户发起售后'}"
        return Ticket(
            ticket_id=f"AS{uuid4().hex[:10].upper()}",
            order_id=order.order_id if order else request.order_id or "unknown",
            user_id=request.user_id,
            after_sales_type=after_sales_type,
            intent=intent,
            status=status,
            risk_level=risk_result.risk_level,
            summary=summary,
            expected_hours=expected_hours,
            next_action=self._next_action(scene, risk_result, status),
            created_at=datetime.now(),
        )

    @staticmethod
    def _infer_type(policy: MerchantServicePolicy, intent: Intent) -> AfterSalesType:
        scheme = policy.after_sales_scheme(intent.value, "RETURN_REFUND")
        return {
            "REFUND_ONLY": AfterSalesType.REFUND_ONLY,
            "RETURN_REFUND": AfterSalesType.RETURN_AND_REFUND,
            "REISSUE": AfterSalesType.REISSUE,
            "PARTIAL_REFUND": AfterSalesType.PARTIAL_REFUND,
            "EXCHANGE": AfterSalesType.REISSUE,
            "REPAIR": AfterSalesType.RETURN_AND_REFUND,
        }.get(scheme, AfterSalesType.RETURN_AND_REFUND)

    @staticmethod
    def _next_action(
        scene: AfterSalesScene,
        risk_result: RiskAssessmentResult,
        status: TicketStatus,
    ) -> str:
        if scene == AfterSalesScene.PACKAGE_DAMAGE:
            return "等待包装补偿评估"
        if scene == AfterSalesScene.PRODUCT_DAMAGE:
            return "等待商品破损审核"
        if status == TicketStatus.AUTO_APPROVED:
            return "等待系统自动处理"
        if risk_result.allow_auto_refund:
            return "等待系统处理退款"
        return "等待审核结果"
