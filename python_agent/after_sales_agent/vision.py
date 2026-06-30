from __future__ import annotations

import json
import os

from .llm import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig
from .models import Attachment, ImageReviewItem, ImageReviewResult
from .trace import TraceRecorder


class VisionReviewService:
    def __init__(self, config: OpenAICompatibleConfig | None = None) -> None:
        timeout_seconds = int(os.getenv("VISION_TIMEOUT_SECONDS", "45"))
        self.client = OpenAICompatibleClient(
            config
            or OpenAICompatibleConfig(
                base_url="http://127.0.0.1:11434",
                api_key="EMPTY",
                model="qwen2.5vl:7b",
                timeout_seconds=timeout_seconds,
            )
        )

    def bind_trace(self, trace_recorder: TraceRecorder | None) -> None:
        self.client.bind_trace(trace_recorder)

    def review_attachments(
        self,
        attachments: tuple[Attachment, ...],
        *,
        order_hint: str | None = None,
    ) -> ImageReviewResult:
        image_attachments = [attachment for attachment in attachments if attachment.source]
        if not image_attachments:
            return ImageReviewResult(
                success=False,
                items=(),
                all_clear=False,
                has_damage_area=False,
                has_outer_package=False,
                has_logistics_label=False,
                logistics_matches_order=False,
                courier_company="",
                tracking_number="",
                sender_name="",
                receiver_name="",
                missing_visual_evidence=("商品照片",),
                summary="当前还没有可识别的照片。",
                raw={"mode": "no_images"},
            )

        try:
            items = tuple(
                self._review_single_attachment(attachment, index=index, order_hint=order_hint)
                for index, attachment in enumerate(image_attachments, start=1)
            )
            missing = self._collect_missing(items)
            first_waybill = next((item for item in items if item.contains_logistics_label), None)
            return ImageReviewResult(
                success=True,
                items=items,
                all_clear=all(item.is_clear for item in items),
                has_damage_area=any(item.contains_damage_area for item in items),
                has_outer_package=any(item.contains_outer_package for item in items),
                has_logistics_label=any(item.contains_logistics_label for item in items),
                logistics_matches_order=any(item.logistics_matches_order for item in items),
                courier_company=first_waybill.courier_company if first_waybill else "",
                tracking_number=first_waybill.tracking_number if first_waybill else "",
                sender_name=first_waybill.sender_name if first_waybill else "",
                receiver_name=first_waybill.receiver_name if first_waybill else "",
                missing_visual_evidence=missing,
                summary=self._build_summary(items, missing),
                raw={
                    "mode": "staged_single_image_review",
                    "items": [self._item_to_raw(item) for item in items],
                },
            )
        except LLMError as exc:
            error_text = str(exc)
            model_missing = "model" in error_text.lower() and "not found" in error_text.lower()
            timeout_like = any(keyword in error_text.lower() for keyword in ("timed out", "timeout", "超时"))
            missing_visual_evidence = ("视觉模型不可用",) if model_missing else ("图片分析结果待补充",)
            summary = "图片审核模型暂时不可用，已跳过视觉审核。" if model_missing else "图片分析暂时异常，我会先根据您的描述继续处理，稍后补充图片分析结果。"
            mode = "vision_unavailable" if model_missing else "vision_timeout_or_error"
            return ImageReviewResult(
                success=False,
                items=(),
                all_clear=False,
                has_damage_area=False,
                has_outer_package=False,
                has_logistics_label=False,
                logistics_matches_order=False,
                courier_company="",
                tracking_number="",
                sender_name="",
                receiver_name="",
                missing_visual_evidence=missing_visual_evidence,
                summary=summary,
                raw={
                    "mode": mode,
                    "error": error_text,
                    "model_missing": model_missing,
                    "timeout_like": timeout_like,
                },
            )

    def _review_single_attachment(
        self,
        attachment: Attachment,
        *,
        index: int,
        order_hint: str | None,
    ) -> ImageReviewItem:
        raw = self.client.chat_multimodal_json(
            system_prompt=self._single_pass_system_prompt(),
            user_text=self._single_pass_user_text(order_hint),
            image_urls=[attachment.source or ""],
            temperature=0.0,
            max_tokens=180,
        )
        return self._parse_single_pass_item(raw, index)

    @staticmethod
    def _single_pass_system_prompt() -> str:
        schema = {
            "image_type": "商品照片|外包装照片|物流面单照片|不确定",
            "is_clear": True,
            "has_damage": False,
            "has_outer_package": False,
            "has_logistics_label": False,
            "matches_order": False,
            "courier_company": "",
            "tracking_number": "",
            "sender_name": "",
            "receiver_name": "",
            "notes": "20字以内简短说明",
        }
        return (
            "你是售后图片审核 Agent。\n"
            "你的职责：\n"
            "1. 只分析当前这1张图片；\n"
            "2. 一次性返回图片类型、清晰度、是否有破损、是否含外包装、是否含物流面单；\n"
            "3. 如果图片是物流面单，再补充提取关键信息并判断是否与订单提示匹配；\n"
            "4. 只根据图片内容判断，不参考文件名；\n"
            "5. 无法确定时返回不确定或 false，不要猜测；\n"
            "6. 不做售后建议，不做客服回复。\n"
            "判断规则：\n"
            "1. 如果主体是商品本体，返回商品照片；\n"
            "2. 如果主体是快递袋、纸箱、包装盒、缓冲袋等外包装，返回外包装照片；\n"
            "3. 如果主体是物流面单、运单标签、快递单，返回物流面单照片；\n"
            "4. 以上三类互斥，只能返回其中一个；\n"
            "5. 只要图片里能明确看到外包装主体，has_outer_package 必须为 true；\n"
            "6. 外包装破损不能归类成商品照片；\n"
            "7. 物流面单不能归类成商品照片或外包装照片；\n"
            "8. has_damage 只表示是否看到了肉眼可见的破损、裂纹、断裂、碎裂、明显变形；\n"
            "9. 如果不是物流面单照片，matches_order 与面单字段返回 false 或空字符串；\n"
            "10. 如果是物流面单但看不清信息，也不要猜测。\n"
            "限制：\n"
            "1. 只能看当前这1张图片；\n"
            "2. 不要补充额外解释；\n"
            "3. 不要猜测图片外的信息。\n"
            "输出要求：\n"
            "1. 只输出 JSON；\n"
            "2. 不要输出 Markdown；\n"
            "3. 不要输出额外解释。\n"
            f"JSON 字段示例：{json.dumps(schema, ensure_ascii=False)}"
        )

    @staticmethod
    def _single_pass_user_text(order_hint: str | None) -> str:
        payload = {
            "task": "review_single_image_once",
            "focus": [
                "image_type",
                "is_clear",
                "has_damage",
                "has_outer_package",
                "has_logistics_label",
                "matches_order",
                "courier_company",
                "tracking_number",
                "sender_name",
                "receiver_name",
            ],
            "order_hint": order_hint,
            "decision_rules": {
                "product": "商品本体为主体时才返回商品照片",
                "package": "快递袋/纸箱/包装盒/缓冲袋为主体时返回外包装照片",
                "waybill": "出现物流面单或运单标签时返回物流面单照片",
                "mutual_exclusive": True,
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _parse_single_pass_item(raw: dict, index: int) -> ImageReviewItem:
        image_type = str(raw.get("image_type") or "不确定")
        item = ImageReviewItem(
            name=f"image_{index}",
            image_type=image_type,
            is_clear=bool(raw.get("is_clear")),
            contains_damage_area=bool(raw.get("has_damage")),
            contains_outer_package=bool(raw.get("has_outer_package")),
            contains_logistics_label=bool(raw.get("has_logistics_label")),
            logistics_matches_order=bool(raw.get("matches_order")),
            courier_company=str(raw.get("courier_company") or ""),
            tracking_number=str(raw.get("tracking_number") or ""),
            sender_name=str(raw.get("sender_name") or ""),
            receiver_name=str(raw.get("receiver_name") or ""),
            notes=str(raw.get("notes") or ""),
        )
        return VisionReviewService._normalize_classification_item(item)

    @staticmethod
    def _normalize_classification_item(item: ImageReviewItem) -> ImageReviewItem:
        image_type = item.image_type
        contains_outer_package = item.contains_outer_package
        contains_logistics_label = item.contains_logistics_label

        if image_type == "外包装照片":
            contains_outer_package = True
            contains_logistics_label = False
        elif image_type == "物流面单照片":
            contains_logistics_label = True
        elif image_type == "商品照片" and item.contains_logistics_label:
            contains_logistics_label = False

        return ImageReviewItem(
            name=item.name,
            image_type=image_type,
            is_clear=item.is_clear,
            contains_damage_area=item.contains_damage_area,
            contains_outer_package=contains_outer_package,
            contains_logistics_label=contains_logistics_label,
            logistics_matches_order=item.logistics_matches_order,
            courier_company=item.courier_company,
            tracking_number=item.tracking_number,
            sender_name=item.sender_name,
            receiver_name=item.receiver_name,
            confidence=item.confidence,
            notes=item.notes,
        )

    @staticmethod
    def _collect_missing(items: tuple[ImageReviewItem, ...]) -> tuple[str, ...]:
        missing: list[str] = []
        if not items or not all(item.is_clear for item in items):
            missing.append("清晰照片")
        if not any(item.contains_damage_area for item in items):
            missing.append("破损照片")
        if not any(item.contains_outer_package for item in items):
            missing.append("外包装照片")

        has_waybill = any(item.contains_logistics_label for item in items)
        if not has_waybill:
            missing.append("物流面单照片")
        elif not any(item.logistics_matches_order for item in items):
            missing.append("与当前订单对应的物流面单照片")
        return tuple(missing)

    @staticmethod
    def _build_summary(items: tuple[ImageReviewItem, ...], missing: tuple[str, ...]) -> str:
        if not items:
            return "暂无可识别照片。"
        seen: list[str] = []
        if any(item.contains_damage_area for item in items):
            seen.append("破损照片")
        if any(item.contains_outer_package for item in items):
            seen.append("外包装照片")
        if any(item.contains_logistics_label for item in items):
            seen.append("物流面单照片")
        if not seen:
            return "已收到照片，但暂未识别到有效售后凭证。"
        if missing:
            return f"已识别到{'、'.join(seen)}，还缺{'、'.join(missing)}。"
        return f"已识别到{'、'.join(seen)}，材料基本齐全。"

    @staticmethod
    def _item_to_raw(item: ImageReviewItem) -> dict:
        return {
            "name": item.name,
            "image_type": item.image_type,
            "is_clear": item.is_clear,
            "contains_damage_area": item.contains_damage_area,
            "contains_outer_package": item.contains_outer_package,
            "contains_logistics_label": item.contains_logistics_label,
            "logistics_matches_order": item.logistics_matches_order,
            "courier_company": item.courier_company,
            "tracking_number": item.tracking_number,
            "sender_name": item.sender_name,
            "receiver_name": item.receiver_name,
            "notes": item.notes,
        }
