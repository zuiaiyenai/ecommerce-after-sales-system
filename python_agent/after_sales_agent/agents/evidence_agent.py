from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..merchant_policy import MerchantServicePolicy
from ..models import AfterSalesRequest, AfterSalesScene, EvidenceCheckResult, Intent, Order
from .intent_agent import IntentAgent


@dataclass(frozen=True)
class EvidenceAgent:
    intent_agent: IntentAgent = IntentAgent()

    def check(
        self,
        order: Order | None,
        request: AfterSalesRequest,
        intent: Intent,
        *,
        service_policy: MerchantServicePolicy | None = None,
        knowledge_base: dict[str, Any] | None = None,
    ) -> EvidenceCheckResult:
        requested_scene = self.intent_agent.infer_scene_enum(request, intent)
        required_items = self._required_items_for_scene(
            requested_scene,
            service_policy=service_policy,
            knowledge_base=knowledge_base,
        )

        existing_items = set(order.uploaded_evidence if order else ())
        existing_items.update(self._normalize_attachment_kinds(requested_scene, request))
        existing_items.update(request.visual_evidence)
        if self._has_meaningful_description(request):
            existing_items.add("问题描述")

        missing_items = tuple(
            item for item in required_items if not self._has_required_evidence(item, existing_items)
        )
        if not missing_items:
            return EvidenceCheckResult(
                evidence_complete=True,
                missing_items=(),
                suggestion="当前材料已经基本齐全，我会继续为您推进售后处理。",
                required_items=required_items,
            )

        return EvidenceCheckResult(
            evidence_complete=False,
            missing_items=missing_items,
            suggestion=self._build_suggestion(requested_scene, missing_items),
            required_items=required_items,
        )

    @staticmethod
    def _normalize_attachment_kinds(
        scene: AfterSalesScene,
        request: AfterSalesRequest,
    ) -> set[str]:
        normalized: set[str] = set()
        for attachment in request.attachments:
            kind = attachment.kind.strip()
            name = attachment.name.lower()
            normalized.add(kind)
            if kind in {"商品破损照片", "外包装照片", "商品照片", "故障照片", "故障视频", "物流面单照片"}:
                continue
            if kind in {"照片", "图片"}:
                if any(token in name for token in ("damage", "broken", "crack", "破", "裂", "损")):
                    normalized.add("商品破损照片")
                if any(token in name for token in ("package", "outer", "box", "wrap", "包装")):
                    normalized.add("外包装照片")
                if scene == AfterSalesScene.WRONG_OR_MISSING_ITEMS:
                    normalized.add("商品照片")
                if scene == AfterSalesScene.QUALITY_ISSUE and any(
                    token in name for token in ("fault", "issue", "error", "故障", "异常")
                ):
                    normalized.add("故障照片")
            if kind in {"视频", "录像"} and scene == AfterSalesScene.QUALITY_ISSUE:
                normalized.add("故障视频")
        return normalized

    def _required_items_for_scene(
        self,
        scene: AfterSalesScene,
        *,
        service_policy: MerchantServicePolicy | None,
        knowledge_base: dict[str, Any] | None,
    ) -> tuple[str, ...]:
        knowledge_items = self._knowledge_scene_evidence(scene, knowledge_base)
        if knowledge_items:
            return knowledge_items
        if service_policy is not None:
            policy_items = service_policy.required_evidence_for_scene(scene.value, ())
            if policy_items:
                return policy_items
        return self._default_scene_evidence(scene)

    @staticmethod
    def _knowledge_scene_evidence(
        scene: AfterSalesScene,
        knowledge_base: dict[str, Any] | None,
    ) -> tuple[str, ...]:
        if not isinstance(knowledge_base, dict):
            return ()
        raw_items = knowledge_base.get("scene_evidence_knowledge")
        if not isinstance(raw_items, list):
            return ()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            if str(item.get("scene") or "").strip() != scene.value:
                continue
            default_evidence = item.get("default_evidence")
            if isinstance(default_evidence, list):
                return tuple(str(value) for value in default_evidence if str(value).strip())
        return ()

    @staticmethod
    def _default_scene_evidence(scene: AfterSalesScene) -> tuple[str, ...]:
        evidence_map: dict[AfterSalesScene, tuple[str, ...]] = {
            AfterSalesScene.PRODUCT_DAMAGE: ("商品破损照片", "问题描述"),
            AfterSalesScene.PACKAGE_DAMAGE: ("外包装照片", "问题描述"),
            AfterSalesScene.WRONG_OR_MISSING_ITEMS: ("商品照片", "问题描述"),
            AfterSalesScene.QUALITY_ISSUE: ("问题描述",),
            AfterSalesScene.LOGISTICS_ISSUE: ("问题描述",),
            AfterSalesScene.PROGRESS_QUERY: (),
            AfterSalesScene.GENERAL: ("问题描述",),
        }
        return evidence_map.get(scene, ("问题描述",))

    @staticmethod
    def _build_suggestion(scene: AfterSalesScene, missing_items: tuple[str, ...]) -> str:
        missing_text = "、".join(missing_items)
        if scene == AfterSalesScene.QUALITY_ISSUE:
            return (
                f"您好，当前还需要补充{missing_text}。这类功能异常通常需要更具体的现象描述，"
                "如果方便，也可以一并上传照片或视频，我会继续帮您记录并推进处理。"
            )
        if scene == AfterSalesScene.PACKAGE_DAMAGE:
            return (
                f"您好，已先记录包装异常。当前还需要补充{missing_text}，"
                "补齐后我会继续帮您判断是否属于包装破损补偿场景。"
            )
        return f"您好，当前还需要补充{missing_text}，补齐后我会继续为您推进售后处理。"

    @staticmethod
    def _has_meaningful_description(request: AfterSalesRequest) -> bool:
        if request.normalized_issue or request.quality_description_detailed is True:
            return True

        combined = " ".join(
            part.strip() for part in (request.message, request.reason, request.description) if part
        )
        if not combined:
            return False

        normalized = combined
        for phrase in (
            "人工客服",
            "人工",
            "客服",
            "真人",
            "转人工",
            "联系人工",
            "我要人工",
            "我要客服",
            "帮我转",
            "转接",
        ):
            normalized = normalized.replace(phrase, "")

        normalized = "".join(ch for ch in normalized if ch not in " ，。！？?!?:;/\\|_-")
        return len(normalized) >= 2

    @staticmethod
    def _has_required_evidence(required_item: str, existing_items: set[str]) -> bool:
        alias_map: dict[str, tuple[str, ...]] = {
            "商品破损照片": ("商品破损照片", "商品照片", "照片", "图片", "damage_photo"),
            "外包装照片": ("外包装照片", "包装照片", "照片", "图片", "package_photo"),
            "商品照片": ("商品照片", "商品破损照片", "照片", "图片", "product_photo"),
            "故障照片或视频": ("故障照片或视频", "故障视频", "故障照片", "商品视频", "视频", "fault_video"),
            "问题描述": ("问题描述",),
        }
        accepted_items = alias_map.get(required_item, (required_item,))
        return any(item in existing_items for item in accepted_items)
