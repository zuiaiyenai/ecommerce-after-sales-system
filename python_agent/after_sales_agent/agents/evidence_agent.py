from __future__ import annotations

from dataclasses import dataclass

from .intent_agent import IntentAgent
from ..models import AfterSalesRequest, EvidenceCheckResult, Intent, Order


@dataclass(frozen=True)
class EvidenceAgent:
    intent_agent: IntentAgent = IntentAgent()

    def check(
        self,
        order: Order | None,
        request: AfterSalesRequest,
        intent: Intent,
    ) -> EvidenceCheckResult:
        requested_scene = self.intent_agent.infer_scene(request, intent)
        required_items = self._required_items_for_scene(requested_scene)

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
    def _normalize_attachment_kinds(scene: str, request: AfterSalesRequest) -> set[str]:
        normalized: set[str] = set()
        for attachment in request.attachments:
            kind = attachment.kind.strip()
            name = attachment.name.lower()
            normalized.add(kind)
            if kind in {"破损照片", "外包装照片", "商品照片", "故障照片", "故障视频", "物流面单照片"}:
                continue
            if kind in {"照片", "图片"}:
                if any(token in name for token in ("damage", "broken", "crack", "裂", "破损", "碎")):
                    normalized.add("破损照片")
                if any(token in name for token in ("package", "outer", "box", "wrap", "包装")):
                    normalized.add("外包装照片")
                if scene == "少发漏发/错发":
                    normalized.add("商品照片")
                if scene == "质量问题/功能异常" and any(
                    token in name for token in ("fault", "issue", "error", "故障", "异常")
                ):
                    normalized.add("故障照片")
        return normalized

    @staticmethod
    def _required_items_for_scene(scene: str) -> tuple[str, ...]:
        evidence_map: dict[str, tuple[str, ...]] = {
            "商品破损": ("破损照片", "问题描述"),
            "包装破损": ("外包装照片", "问题描述"),
            "少发漏发/错发": ("商品照片", "问题描述"),
            "质量问题/功能异常": ("问题描述",),
            "物流异常": ("问题描述",),
            "进度查询": (),
            "普通咨询": ("问题描述",),
        }
        return evidence_map.get(scene, ("问题描述",))

    @staticmethod
    def _build_suggestion(scene: str, missing_items: tuple[str, ...]) -> str:
        missing_text = "、".join(missing_items)
        if scene == "质量问题/功能异常":
            return (
                f"您好，当前还需要补充{missing_text}。这类功能异常单靠照片通常无法准确判断，"
                "请尽量详细描述问题表现，我会继续帮您记录并转给客服跟进。"
            )
        if scene == "包装破损":
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
            "我要",
            "帮我转",
            "转接",
        ):
            normalized = normalized.replace(phrase, "")

        normalized = "".join(ch for ch in normalized if ch not in " ，。！？,.!?:;/\\|_-")
        return len(normalized) >= 2

    @staticmethod
    def _has_required_evidence(required_item: str, existing_items: set[str]) -> bool:
        alias_map: dict[str, tuple[str, ...]] = {
            "破损照片": ("破损照片", "商品照片", "照片", "damage_photo"),
            "外包装照片": ("外包装照片", "包装照片", "照片", "package_photo"),
            "商品照片": ("商品照片", "破损照片", "照片", "product_photo"),
            "故障照片或视频": ("故障照片或视频", "故障视频", "故障照片", "商品视频", "视频"),
            "问题描述": ("问题描述",),
        }
        accepted_items = alias_map.get(required_item, (required_item,))
        return any(item in existing_items for item in accepted_items)
