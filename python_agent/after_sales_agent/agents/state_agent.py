from __future__ import annotations

from dataclasses import dataclass

from ..merchant_policy import MerchantServicePolicy
from ..models import AfterSalesStatus, Intent, Order, StateTransitionResult


@dataclass(frozen=True)
class StateMachineAgent:
    def evaluate(
        self,
        order: Order | None,
        intent: Intent,
        *,
        service_policy: MerchantServicePolicy | None = None,
    ) -> StateTransitionResult:
        current = order.after_sales_status if order else AfterSalesStatus.NOT_APPLIED
        state_rules = self._state_rules(service_policy)
        allowed_actions = state_rules.get(current.value, self._default_state_rules()[current.value])
        intent_actions = self._intent_actions(service_policy, allowed_actions)
        expected_actions = intent_actions.get(intent.value, intent_actions[Intent.GENERAL.value])
        allowed = any(action in allowed_actions for action in expected_actions)

        if intent == Intent.APPLY_AFTER_SALES and current == AfterSalesStatus.NOT_APPLIED:
            return StateTransitionResult(
                current_status=current,
                allowed_actions=allowed_actions,
                allowed=True,
                reason="当前订单尚未申请售后，可以发起申请。",
                suggested_status=self._submission_entry_status(service_policy),
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

    @staticmethod
    def _default_state_rules() -> dict[str, tuple[str, ...]]:
        return {
            AfterSalesStatus.NOT_APPLIED.value: ("提交售后申请",),
            AfterSalesStatus.SUBMITTED.value: ("进入商家审核", "要求补充凭证", "上传凭证"),
            AfterSalesStatus.WAITING_EVIDENCE.value: ("上传凭证",),
            AfterSalesStatus.MERCHANT_REVIEW.value: ("等待审核", "要求补充凭证", "上传凭证", "平台介入", "转人工"),
            AfterSalesStatus.PLATFORM_REVIEW.value: ("等待平台复核", "转人工"),
            AfterSalesStatus.APPROVED.value: ("退款处理", "待用户退货", "换货处理"),
            AfterSalesStatus.REJECTED.value: ("申诉", "转人工"),
            AfterSalesStatus.WAITING_RETURN.value: ("填写退货物流",),
            AfterSalesStatus.REFUND_PROCESSING.value: ("查询退款进度",),
            AfterSalesStatus.EXCHANGE_PROCESSING.value: ("查询换货进度",),
            AfterSalesStatus.COMPLETED.value: ("查看结果", "评价"),
            AfterSalesStatus.CLOSED.value: ("查看结果",),
            AfterSalesStatus.HUMAN_PROCESSING.value: ("等待人工处理",),
        }

    def _state_rules(self, service_policy: MerchantServicePolicy | None) -> dict[str, tuple[str, ...]]:
        merged = dict(self._default_state_rules())
        if service_policy is not None:
            merged.update(service_policy.state_rules())
        return merged

    def _intent_actions(
        self,
        service_policy: MerchantServicePolicy | None,
        general_allowed_actions: tuple[str, ...],
    ) -> dict[str, tuple[str, ...]]:
        defaults = {
            Intent.APPLY_AFTER_SALES.value: ("提交售后申请",),
            Intent.REFUND_PROGRESS.value: ("查询退款进度", "等待审核", "等待平台复核"),
            Intent.RETURN_LOGISTICS.value: ("填写退货物流", "查看结果"),
            Intent.SUPPLEMENT_EVIDENCE.value: ("上传凭证", "要求补充凭证"),
            Intent.MERCHANT_REJECTED.value: ("申诉", "平台介入", "转人工"),
            Intent.REFUND_ONLY.value: ("提交售后申请", "退款处理"),
            Intent.EXCHANGE_REPAIR.value: ("换货处理", "提交售后申请"),
            Intent.HUMAN_SERVICE.value: ("转人工",),
            Intent.COMPLAINT.value: ("转人工", "平台介入"),
            Intent.GENERAL.value: general_allowed_actions,
        }
        if service_policy is not None:
            defaults.update(service_policy.intent_actions())
        defaults[Intent.GENERAL.value] = general_allowed_actions
        return defaults

    @staticmethod
    def _submission_entry_status(service_policy: MerchantServicePolicy | None) -> AfterSalesStatus:
        raw_value = ""
        if service_policy is not None:
            raw_value = str(service_policy.submission_entry_status or "").strip().lower()
        for status in AfterSalesStatus:
            if status.value == raw_value:
                return status
        return AfterSalesStatus.SUBMITTED
