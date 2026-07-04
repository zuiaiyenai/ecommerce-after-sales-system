from __future__ import annotations

from dataclasses import dataclass

from ..models import AfterSalesStatus, Intent, Order, StateTransitionResult


@dataclass(frozen=True)
class StateMachineAgent:
    def evaluate(self, order: Order | None, intent: Intent) -> StateTransitionResult:
        current = order.after_sales_status if order else AfterSalesStatus.NOT_APPLIED
        state_rules: dict[AfterSalesStatus, tuple[str, ...]] = {
            AfterSalesStatus.NOT_APPLIED: ("提交售后申请",),
            AfterSalesStatus.SUBMITTED: ("进入商家审核", "要求补充凭证", "上传凭证"),
            AfterSalesStatus.WAITING_EVIDENCE: ("上传凭证",),
            AfterSalesStatus.MERCHANT_REVIEW: ("等待审核", "要求补充凭证", "上传凭证", "平台介入", "转人工"),
            AfterSalesStatus.PLATFORM_REVIEW: ("等待平台复核", "转人工"),
            AfterSalesStatus.APPROVED: ("退款处理", "待用户退货", "换货处理"),
            AfterSalesStatus.REJECTED: ("申诉", "转人工"),
            AfterSalesStatus.WAITING_RETURN: ("填写退货物流",),
            AfterSalesStatus.REFUND_PROCESSING: ("查询退款进度",),
            AfterSalesStatus.EXCHANGE_PROCESSING: ("查询换货进度",),
            AfterSalesStatus.COMPLETED: ("查看结果", "评价"),
            AfterSalesStatus.HUMAN_PROCESSING: ("等待人工处理",),
        }
        allowed_actions = state_rules[current]
        intent_to_actions: dict[Intent, tuple[str, ...]] = {
            Intent.APPLY_AFTER_SALES: ("提交售后申请",),
            Intent.REFUND_PROGRESS: ("查询退款进度", "等待审核", "等待平台复核"),
            Intent.RETURN_LOGISTICS: ("填写退货物流", "查看结果"),
            Intent.SUPPLEMENT_EVIDENCE: ("上传凭证", "要求补充凭证"),
            Intent.MERCHANT_REJECTED: ("申诉", "平台介入", "转人工"),
            Intent.REFUND_ONLY: ("提交售后申请", "退款处理"),
            Intent.EXCHANGE_REPAIR: ("换货处理", "提交售后申请"),
            Intent.HUMAN_SERVICE: ("转人工",),
            Intent.COMPLAINT: ("转人工", "平台介入"),
            Intent.GENERAL: allowed_actions,
        }
        expected_actions = intent_to_actions[intent]
        allowed = any(action in allowed_actions for action in expected_actions)

        if intent == Intent.APPLY_AFTER_SALES and current == AfterSalesStatus.NOT_APPLIED:
            return StateTransitionResult(
                current_status=current,
                allowed_actions=allowed_actions,
                allowed=True,
                reason="当前订单尚未申请售后，可以发起申请。",
                suggested_status=AfterSalesStatus.SUBMITTED,
            )
        if allowed:
            return StateTransitionResult(
                current_status=current,
                allowed_actions=allowed_actions,
                allowed=True,
                reason="当前状态支持该类操作。",
                suggested_status=current,
            )
        return StateTransitionResult(
            current_status=current,
            allowed_actions=allowed_actions,
            allowed=False,
            reason=f"当前售后状态为 {current.value}，暂不支持该操作。",
            suggested_status=current,
        )
