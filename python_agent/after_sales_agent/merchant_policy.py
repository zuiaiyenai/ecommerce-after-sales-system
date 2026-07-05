from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO"
DEFAULT_POLICY_BASE_URL = "http://127.0.0.1:8080/api/agent/policies"

DEFAULT_STATE_RULES: dict[str, tuple[str, ...]] = {
    "not_applied": ("提交售后申请",),
    "submitted": ("进入商家审核", "要求补充凭证"),
    "waiting_evidence": ("上传凭证",),
    "merchant_review": ("等待商家审核", "转人工"),
    "platform_review": ("等待平台复核", "转人工"),
    "approved": ("自动通过", "退款处理中", "待用户退货", "换货处理"),
    "rejected": ("申诉", "转人工"),
    "waiting_return": ("填写退货物流",),
    "refund_processing": ("查询退款进度",),
    "exchange_processing": ("查询换货进度",),
    "completed": ("查看结果", "评价"),
    "human_processing": ("等待人工处理",),
}

DEFAULT_INTENT_ACTIONS: dict[str, tuple[str, ...]] = {
    "apply_after_sales": ("提交售后申请",),
    "refund_progress": ("查询退款进度", "等待商家审核", "等待平台复核"),
    "return_logistics": ("填写退货物流", "查看结果"),
    "supplement_evidence": ("上传凭证", "要求补充凭证"),
    "merchant_rejected": ("申诉", "平台复核", "转人工"),
    "refund_only": ("提交售后申请", "退款处理中", "自动通过"),
    "exchange_repair": ("换货处理", "提交售后申请"),
    "human_service": ("转人工",),
    "complaint": ("转人工", "平台复核"),
    "general": (),
}

DEFAULT_SCENE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "product_damage": ("破损照片", "问题描述"),
    "package_damage": ("外包装照片", "问题描述"),
    "wrong_or_missing_items": ("商品照片", "问题描述"),
    "quality_issue": ("问题描述",),
    "logistics_issue": ("问题描述",),
    "progress_query": (),
    "general": ("问题描述",),
}

DEFAULT_REPLY_TEMPLATES: dict[str, str] = {
    "quality_issue.ask_for_detail": "您好，当前只有概括性的质量问题描述，图片也暂时无法直接确认具体异常。请补充实际表现，例如没有声音、无法开机、充电异常、按键失灵等，我再继续帮您处理。",
    "quality_issue.ask_for_detail_progress": "等待用户补充具体异常表现后继续判断。",
    "quality_issue.visual_handoff": "您好，已记录您的异常表现。当前图片暂时无法自动确认问题，我这边为您转客服进一步核实处理。",
    "quality_issue.visual_handoff_progress": "已记录异常描述，但图片无法自动核验，转客服进一步核实。",
    "quality_issue.auto_approved_progress": "图片核验通过，AI 已自动审核并进入处理中状态。",
    "state_reply.merchant_review": "您好，当前售后申请仍在商家审核中，审核通过后才会进入下一步处理。",
    "state_reply.platform_review": "您好，当前售后申请正在平台复核中，请您耐心等待处理结果。",
    "state_reply.refund_processing": "您好，退款正在处理中，到账时间以支付渠道实际入账为准。",
    "state_reply.completed": "您好，当前售后已经处理完成，您可以查看处理结果。",
    "state_reply.default": "您好，当前状态暂不支持该操作，请按页面提示继续处理。",
    "status.waiting_evidence": "您好，当前售后申请还需要补充材料，提交完成后平台会继续审核。",
    "status.refund_processing": "您好，退款正在处理中，到账时间以支付渠道实际入账为准，请您留意进度更新。",
    "status.waiting_return": "您好，当前待您补充退货物流信息，现有物流状态为 {logistics}。",
    "status.high_risk": "您好，当前问题还需要进一步核验，我会继续帮您跟进。",
    "status.recorded": "您好，当前售后信息已经记录，您可以继续关注处理进度。",
    "merchant_review.stalled": "您好，当前处理时间比平时略长，我会继续帮您跟进审核进度。",
    "merchant_review.anxious": "您好，我理解您在着急等待退款，我会继续帮您跟进进度，状态更新后第一时间通知您。",
    "merchant_review.default": "您好，您的退款申请已收到，当前正在由商家审核。",
    "ticket_reply.package_damage": "您好，已为您记录包装破损问题并生成售后申请 {ticket_id}。我们会继续推进包装赔付流程。",
    "ticket_reply.auto_approved": "您好，已为您提交售后申请 {ticket_id}，当前符合自动处理条件，系统会尽快推进后续流程。",
    "ticket_reply.product_damage": "您好，已为您提交售后申请 {ticket_id}，当前会先按商品破损情况进入审核，预计 {expected_hours} 小时内更新进度。",
    "ticket_reply.default": "您好，已为您提交售后申请 {ticket_id}，当前已进入审核流程，预计 {expected_hours} 小时内更新进度。",
    "progress.submitted": "{product_name} 已提交售后申请，下一步进入商家审核。",
    "progress.waiting_evidence": "{product_name} 当前待补充材料，补齐后进入审核。",
    "progress.merchant_review": "{product_name} 当前处于商家审核中。",
    "progress.refund_processing": "{product_name} 当前进入退款处理阶段。",
    "progress.human_processing": "{product_name} 当前已转人工处理。",
    "progress.default": "{product_name} 当前售后状态为 {status_value}。",
}

DEFAULT_AFTER_SALES_SCHEME_MAP: dict[str, str] = {
    "refund_only": "REFUND_ONLY",
    "apply_after_sales": "RETURN_REFUND",
    "merchant_rejected": "RETURN_REFUND",
    "exchange_repair": "RETURN_REFUND",
}


@dataclass(frozen=True)
class StatePolicy:
    submission_entry_status: str = "merchant_review"
    requires_platform_review: bool = False
    supports_auto_approve: bool = True
    rejected_resolution: str = "appeal"
    auto_review_hours: int = 12
    manual_review_hours: int = 24
    state_rules: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_STATE_RULES))
    intent_actions: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_INTENT_ACTIONS))


@dataclass(frozen=True)
class EvidencePolicy:
    default_scene_evidence: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_SCENE_EVIDENCE))
    required_evidence_overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)
    quality_issue_requires_detail: bool = True
    allow_visual_auto_approve: bool = True

    def required_evidence_for_scene(
        self,
        scene: str,
        default_items: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        if scene in self.required_evidence_overrides:
            return self.required_evidence_overrides[scene]
        if scene in self.default_scene_evidence:
            return self.default_scene_evidence[scene]
        return default_items


@dataclass(frozen=True)
class RiskPolicy:
    auto_refund_limit: float = 50.0
    high_value_amount: float = 300.0
    history_after_sales_threshold: int = 3


@dataclass(frozen=True)
class HandoffPolicy:
    emotion_handoff_min_level: str = "angry"
    complaint_to_human: bool = True
    human_request_threshold: int = 2
    visual_review_failed_to_human: bool = True


@dataclass(frozen=True)
class MerchantServicePolicy:
    """Unified business policy passed through every after-sales decision agent."""

    merchant_code: str = DEFAULT_MERCHANT_CODE
    policy_code: str = "DEFAULT_POLICY"
    policy_version: str = "2026-07-02-v3"
    display_name: str = "Default merchant"
    merchant_type: str = "SKU-GENERAL-001"
    state_policy: StatePolicy = field(default_factory=StatePolicy)
    evidence_policy: EvidencePolicy = field(default_factory=EvidencePolicy)
    risk_policy: RiskPolicy = field(default_factory=RiskPolicy)
    handoff_policy: HandoffPolicy = field(default_factory=HandoffPolicy)
    reply_guidelines: tuple[str, ...] = ()
    escalation_keywords: tuple[str, ...] = ()
    reply_templates: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_REPLY_TEMPLATES))
    after_sales_scheme_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_AFTER_SALES_SCHEME_MAP))

    @property
    def auto_refund_limit(self) -> float:
        return self.risk_policy.auto_refund_limit

    @property
    def high_value_amount(self) -> float:
        return self.risk_policy.high_value_amount

    @property
    def history_after_sales_threshold(self) -> int:
        return self.risk_policy.history_after_sales_threshold

    @property
    def auto_review_hours(self) -> int:
        return self.state_policy.auto_review_hours

    @property
    def manual_review_hours(self) -> int:
        return self.state_policy.manual_review_hours

    @property
    def submission_entry_status(self) -> str:
        return self.state_policy.submission_entry_status

    @property
    def requires_platform_review(self) -> bool:
        return self.state_policy.requires_platform_review

    @property
    def supports_auto_approve(self) -> bool:
        return self.state_policy.supports_auto_approve

    @property
    def rejected_resolution(self) -> str:
        return self.state_policy.rejected_resolution

    @property
    def human_request_threshold(self) -> int:
        return self.handoff_policy.human_request_threshold

    @property
    def complaint_to_human(self) -> bool:
        return self.handoff_policy.complaint_to_human

    @property
    def quality_issue_requires_detail(self) -> bool:
        return self.evidence_policy.quality_issue_requires_detail

    @property
    def allow_visual_auto_approve(self) -> bool:
        return self.evidence_policy.allow_visual_auto_approve

    @property
    def visual_review_failed_to_human(self) -> bool:
        return self.handoff_policy.visual_review_failed_to_human

    @property
    def emotion_handoff_min_level(self) -> str:
        return self.handoff_policy.emotion_handoff_min_level

    @property
    def angry_to_human(self) -> bool:
        return _emotion_rank("angry") >= _emotion_rank(self.handoff_policy.emotion_handoff_min_level)

    def required_evidence_for_scene(
        self,
        scene: str,
        default_items: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        return self.evidence_policy.required_evidence_for_scene(scene, default_items)

    def state_rules(self) -> dict[str, tuple[str, ...]]:
        return self.state_policy.state_rules

    def intent_actions(self) -> dict[str, tuple[str, ...]]:
        return self.state_policy.intent_actions

    def reply_template(self, key: str, default: str) -> str:
        return self.reply_templates.get(key, default)

    def after_sales_scheme(self, intent_value: str, default: str) -> str:
        return self.after_sales_scheme_map.get(intent_value, default)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "merchant_code": self.merchant_code,
            "policy_code": self.policy_code,
            "policy_version": self.policy_version,
            "display_name": self.display_name,
            "merchant_type": self.merchant_type,
            "state_policy": _policy_to_dict(self.state_policy),
            "evidence_policy": _policy_to_dict(self.evidence_policy),
            "risk_policy": _policy_to_dict(self.risk_policy),
            "handoff_policy": _policy_to_dict(self.handoff_policy),
            "reply_guidelines": list(self.reply_guidelines),
            "escalation_keywords": list(self.escalation_keywords),
            "reply_templates": dict(self.reply_templates),
            "after_sales_scheme_map": dict(self.after_sales_scheme_map),
        }

    def to_audit_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state_policy"] = _policy_to_dict(self.state_policy)
        payload["evidence_policy"] = _policy_to_dict(self.evidence_policy)
        payload["risk_policy"] = _policy_to_dict(self.risk_policy)
        payload["handoff_policy"] = _policy_to_dict(self.handoff_policy)
        payload["reply_guidelines"] = list(self.reply_guidelines)
        payload["escalation_keywords"] = list(self.escalation_keywords)
        payload["reply_templates"] = dict(self.reply_templates)
        payload["after_sales_scheme_map"] = dict(self.after_sales_scheme_map)
        return payload


@dataclass(frozen=True)
class MerchantPolicyResolution:
    service_policy: MerchantServicePolicy
    source: str = "registry"
    knowledge_base: dict[str, Any] = field(default_factory=dict)


DEFAULT_POLICY = MerchantServicePolicy(
    policy_code="DEFAULT_POLICY",
    display_name="Default after-sales policy",
    merchant_type="SKU-GENERAL-001",
    reply_guidelines=(
        "Keep replies concise and do not promise exact refund arrival time.",
        "Ask only for materials required by the current scene.",
    ),
)


BUILT_IN_POLICIES: dict[str, MerchantServicePolicy] = {
    DEFAULT_MERCHANT_CODE: DEFAULT_POLICY,
    "DIGITAL_STRICT": replace(
        DEFAULT_POLICY,
        merchant_code="DIGITAL_STRICT",
        policy_code="DIGITAL_STRICT",
        display_name="Digital products strict review",
        merchant_type="SKU-DIGITAL-001",
        state_policy=replace(
            DEFAULT_POLICY.state_policy,
            supports_auto_approve=False,
            requires_platform_review=True,
            submission_entry_status="platform_review",
            manual_review_hours=48,
            state_rules={
                **DEFAULT_STATE_RULES,
                "submitted": ("进入平台复核", "要求补充凭证"),
                "merchant_review": ("等待商家审核", "平台复核", "转人工"),
                "approved": ("退款处理中", "待用户退货", "换货处理"),
            },
        ),
        evidence_policy=replace(
            DEFAULT_POLICY.evidence_policy,
            quality_issue_requires_detail=True,
            allow_visual_auto_approve=False,
            required_evidence_overrides={
                "quality_issue": ("问题描述", "故障照片或视频"),
                "product_damage": ("破损照片", "问题描述"),
            },
        ),
        risk_policy=replace(
            DEFAULT_POLICY.risk_policy,
            auto_refund_limit=30.0,
            high_value_amount=200.0,
            history_after_sales_threshold=2,
        ),
        handoff_policy=replace(
            DEFAULT_POLICY.handoff_policy,
            emotion_handoff_min_level="dissatisfied",
            visual_review_failed_to_human=True,
        ),
        after_sales_scheme_map={
            **DEFAULT_AFTER_SALES_SCHEME_MAP,
            "exchange_repair": "RETURN_REFUND",
        },
        reply_guidelines=(
            "For digital products, prioritize fault description and verifiable evidence.",
            "Do not auto-approve function issues based on product photos alone.",
        ),
    ),
    "FASHION_FAST": replace(
        DEFAULT_POLICY,
        merchant_code="FASHION_FAST",
        policy_code="FASHION_FAST",
        display_name="Fashion fast-service policy",
        merchant_type="SKU-FASHION-001",
        state_policy=replace(
            DEFAULT_POLICY.state_policy,
            supports_auto_approve=True,
            auto_review_hours=6,
            manual_review_hours=12,
        ),
        evidence_policy=replace(
            DEFAULT_POLICY.evidence_policy,
            quality_issue_requires_detail=False,
            required_evidence_overrides={
                "wrong_or_missing_items": ("商品照片", "问题描述"),
                "package_damage": ("外包装照片", "问题描述"),
            },
        ),
        risk_policy=replace(
            DEFAULT_POLICY.risk_policy,
            auto_refund_limit=80.0,
            high_value_amount=500.0,
            history_after_sales_threshold=4,
        ),
        handoff_policy=replace(
            DEFAULT_POLICY.handoff_policy,
            emotion_handoff_min_level="angry",
            human_request_threshold=3,
        ),
        after_sales_scheme_map={
            **DEFAULT_AFTER_SALES_SCHEME_MAP,
            "merchant_rejected": "PARTIAL_REFUND",
            "exchange_repair": "REISSUE",
            "apply_after_sales:wrong_or_missing_items": "REISSUE",
        },
        reply_guidelines=(
            "For low-value fashion orders, prefer fast confirmation after basic evidence is complete.",
        ),
    ),
}


class MerchantPolicyRegistry:
    def __init__(
        self,
        policies: dict[str, MerchantServicePolicy] | None = None,
        *,
        remote_base_url: str | None = None,
        remote_timeout_ms: int | None = None,
    ) -> None:
        self._policies = {key.upper(): value for key, value in (policies or BUILT_IN_POLICIES).items()}
        self._remote_base_url = (remote_base_url or "").strip().rstrip("/")
        self._remote_timeout_ms = remote_timeout_ms or int(os.getenv("AFTERSALES_POLICY_TIMEOUT_MS", "3000"))

    @classmethod
    def from_env(cls) -> "MerchantPolicyRegistry":
        config_path = os.getenv("MERCHANT_POLICY_FILE")
        remote_base_url = os.getenv("AFTERSALES_POLICY_BASE_URL", DEFAULT_POLICY_BASE_URL)
        policies = dict(BUILT_IN_POLICIES)
        if config_path:
            policies = _load_policy_file(Path(config_path))
        return cls(policies, remote_base_url=remote_base_url)

    def resolve(
        self,
        *,
        merchant_code: str | None = None,
        order: Any | None = None,
        request: Any | None = None,
    ) -> MerchantServicePolicy:
        return self.resolve_with_context(
            merchant_code=merchant_code,
            order=order,
            request=request,
        ).service_policy

    def resolve_with_context(
        self,
        *,
        merchant_code: str | None = None,
        order: Any | None = None,
        request: Any | None = None,
    ) -> MerchantPolicyResolution:
        resolved_code = (
            merchant_code
            or getattr(order, "merchant_code", None)
            or getattr(request, "merchant_code", None)
            or DEFAULT_MERCHANT_CODE
        )
        normalized_code = str(resolved_code or DEFAULT_MERCHANT_CODE).strip().upper() or DEFAULT_MERCHANT_CODE
        remote_policy = self._resolve_remote_policy(normalized_code, order=order, request=request)
        if remote_policy is not None:
            return remote_policy
        return MerchantPolicyResolution(
            service_policy=self._policies.get(normalized_code, self._policies[DEFAULT_MERCHANT_CODE]),
            source="registry_builtin",
            knowledge_base={},
        )

    def _resolve_remote_policy(
        self,
        merchant_code: str,
        *,
        order: Any | None,
        request: Any | None,
    ) -> MerchantPolicyResolution | None:
        if not self._remote_base_url:
            return None
        payload = {
            "merchantCode": merchant_code,
            "productCategory": _resolve_product_category(order),
            "orderStatus": _resolve_order_status(order),
            "afterSalesStatus": _resolve_after_sales_status(order),
            "messageScene": getattr(request, "llm_scene", None).value if getattr(request, "llm_scene", None) else None,
        }
        try:
            req = request_module.Request(
                f"{self._remote_base_url}/resolve",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with request_module.urlopen(req, timeout=self._remote_timeout_ms / 1000.0) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, TimeoutError, ValueError):
            return None

        data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
        if not isinstance(data, dict):
            return None
        service_policy = data.get("service_policy")
        if not isinstance(service_policy, dict):
            return None
        knowledge_base = data.get("knowledge_base")
        base = self._policies.get(merchant_code, self._policies[DEFAULT_MERCHANT_CODE])
        return MerchantPolicyResolution(
            service_policy=_merge_policy(base, service_policy),
            source=str(data.get("source") or "registry_remote"),
            knowledge_base=_normalize_knowledge_base(knowledge_base),
        )


request_module = request


def _load_policy_file(path: Path) -> dict[str, MerchantServicePolicy]:
    if not path.exists():
        return BUILT_IN_POLICIES

    raw = json.loads(path.read_text(encoding="utf-8"))
    policies = dict(BUILT_IN_POLICIES)
    for item in raw.get("policies", []):
        if not isinstance(item, dict):
            continue
        merchant_code = str(item.get("merchant_code") or "").strip().upper()
        if not merchant_code:
            continue
        base = policies.get(merchant_code, DEFAULT_POLICY)
        policies[merchant_code] = _merge_policy(base, item)
    return policies


def _merge_policy(base: MerchantServicePolicy, overrides: dict[str, Any]) -> MerchantServicePolicy:
    direct_overrides = {
        key: overrides[key]
        for key in ("merchant_code", "policy_code", "policy_version", "display_name", "merchant_type")
        if key in overrides
    }
    if "reply_guidelines" in overrides:
        direct_overrides["reply_guidelines"] = tuple(overrides["reply_guidelines"])
    if "escalation_keywords" in overrides:
        direct_overrides["escalation_keywords"] = tuple(overrides["escalation_keywords"])
    if "reply_templates" in overrides:
        direct_overrides["reply_templates"] = {
            **base.reply_templates,
            **{str(key): str(value) for key, value in dict(overrides["reply_templates"]).items()},
        }
    if "after_sales_scheme_map" in overrides:
        direct_overrides["after_sales_scheme_map"] = {
            **base.after_sales_scheme_map,
            **{str(key): str(value) for key, value in dict(overrides["after_sales_scheme_map"]).items()},
        }

    state_overrides = _normalize_state_overrides(overrides)
    evidence_overrides = _normalize_evidence_overrides(overrides)
    risk_overrides = _normalize_risk_overrides(overrides)
    handoff_overrides = _normalize_handoff_overrides(overrides)

    base_direct = replace(base, **direct_overrides)
    return replace(
        base_direct,
        state_policy=replace(base_direct.state_policy, **state_overrides),
        evidence_policy=replace(base_direct.evidence_policy, **evidence_overrides),
        risk_policy=replace(base_direct.risk_policy, **risk_overrides),
        handoff_policy=replace(base_direct.handoff_policy, **handoff_overrides),
    )


def _normalize_state_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    nested = dict(overrides.get("state_policy") or overrides.get("statePolicy") or {})
    if "state_rules" in nested:
        nested["state_rules"] = _normalize_tuple_mapping(nested["state_rules"])
    if "intent_actions" in nested:
        nested["intent_actions"] = _normalize_tuple_mapping(nested["intent_actions"])
    return {
        key: value
        for key, value in nested.items()
        if key in StatePolicy.__dataclass_fields__
    }


def _normalize_evidence_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    nested = dict(overrides.get("evidence_policy") or overrides.get("evidencePolicy") or {})
    if "default_scene_evidence" in nested:
        nested["default_scene_evidence"] = _normalize_tuple_mapping(nested["default_scene_evidence"])
    if "required_evidence_overrides" in nested:
        nested["required_evidence_overrides"] = _normalize_tuple_mapping(nested["required_evidence_overrides"])
    return {
        key: value
        for key, value in nested.items()
        if key in EvidencePolicy.__dataclass_fields__
    }


def _normalize_risk_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    nested = dict(overrides.get("risk_policy") or overrides.get("riskPolicy") or {})
    return {
        key: value
        for key, value in nested.items()
        if key in RiskPolicy.__dataclass_fields__
    }


def _normalize_handoff_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    nested = dict(overrides.get("handoff_policy") or overrides.get("handoffPolicy") or {})
    return {
        key: value
        for key, value in nested.items()
        if key in HandoffPolicy.__dataclass_fields__
    }


def _normalize_tuple_mapping(raw_mapping: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw_mapping, dict):
        return {}
    return {
        str(key): tuple(str(item) for item in value)
        for key, value in raw_mapping.items()
        if isinstance(value, (list, tuple))
    }


def _policy_to_dict(policy: Any) -> dict[str, Any]:
    payload = asdict(policy)
    for key in ("state_rules", "intent_actions", "default_scene_evidence", "required_evidence_overrides"):
        if key in payload:
            payload[key] = {name: list(values) for name, values in payload[key].items()}
    return payload


def _normalize_knowledge_base(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        normalized[str(key)] = value
    return normalized


def _resolve_product_category(order: Any | None) -> str | None:
    if order is None:
        return None
    items = getattr(order, "items", ()) or ()
    if items:
        return str(getattr(items[0], "category", "") or "") or None
    return None


def _resolve_order_status(order: Any | None) -> str | None:
    if order is None:
        return None
    status = getattr(order, "status", None)
    return getattr(status, "value", status)


def _resolve_after_sales_status(order: Any | None) -> str | None:
    if order is None:
        return None
    status = getattr(order, "after_sales_status", None)
    return getattr(status, "value", status)


def _emotion_rank(label: str) -> int:
    mapping = {
        "satisfied": 0,
        "calm": 1,
        "anxious": 2,
        "dissatisfied": 3,
        "angry": 4,
    }
    return mapping.get(str(label or "").strip().lower(), 1)
