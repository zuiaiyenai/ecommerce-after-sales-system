from __future__ import annotations

import json
import hashlib
import base64
import logging
import os
import re
import sqlite3
import threading
import time
from urllib import request
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from typing import ClassVar

from .llm_client import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig, get_llm_client
from ..domain.models import Attachment, ImageReviewItem, ImageReviewResult
from ..infrastructure.request_tracing import TraceRecorder

logger = logging.getLogger("after_sales_agent.vision")


class VisionReviewService:
    PROMPT_VERSION: ClassVar[str] = "2026-07-31-generic-evidence-v2"
    _cache: ClassVar[OrderedDict[str, tuple[float, ImageReviewItem]]] = OrderedDict()
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()
    def __init__(self, config: OpenAICompatibleConfig | None = None) -> None:
        timeout_seconds = int(os.getenv("VISION_TIMEOUT_SECONDS", "45"))
        vision_base_url = os.getenv("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode")
        self.client = get_llm_client(
            config
            or OpenAICompatibleConfig(
                provider=os.getenv("VISION_PROVIDER", "remote").strip().lower(),
                base_url=vision_base_url,
                api_key=os.getenv("VISION_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")),
                model=os.getenv("VISION_MODEL", "qwen3-vl-plus"),
                timeout_seconds=timeout_seconds,
                ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            )
        )

    def bind_trace(self, trace_recorder: TraceRecorder | None) -> None:
        self.client.bind_trace(trace_recorder)

    def review_attachments(
        self,
        attachments: tuple[Attachment, ...],
        *,
        order_hint: str | None = None,
        issue_hint: str | None = None,
        skill_name: str | None = None,
        skill_version: str | None = None,
        skill_instructions: str | None = None,
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
                self._review_single_attachment(
                    attachment,
                    index=index,
                    order_hint=order_hint,
                    issue_hint=issue_hint,
                    skill_name=skill_name,
                    skill_version=skill_version,
                    skill_instructions=skill_instructions,
                )
                for index, attachment in enumerate(image_attachments, start=1)
            )
            missing = self._collect_missing(items)
            generic_evidence = self._aggregate_generic_evidence(items)
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
                    "model": self.client.config.model,
                    "items": [self._item_to_raw(item) for item in items],
                },
                **generic_evidence,
            )
        except LLMError as exc:
            error_text = str(exc)
            model_missing = "model" in error_text.lower() and "not found" in error_text.lower()
            timeout_like = any(keyword in error_text.lower() for keyword in ("timed out", "timeout", "超时"))
            missing_visual_evidence = ("图片校验未完成",) if model_missing else ("图片分析结果待补充",)
            summary = "图片暂时无法完成校验，先根据用户描述继续处理。" if model_missing else "图片分析暂时异常，先根据用户描述继续处理。"
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
        issue_hint: str | None,
        skill_name: str | None,
        skill_version: str | None,
        skill_instructions: str | None,
    ) -> ImageReviewItem:
        cache_key = self._cache_key(
            attachment.source or "",
            order_hint,
            issue_hint,
            skill_version,
        )
        cached = self._cache_get(cache_key)
        if cached is None:
            cached = self._disk_cache_get(cache_key)
        if cached is not None:
            logger.info("vision cache hit index=%s name=%s", index, attachment.name)
            return cached
        materialized_source = self._materialize_source(attachment.source or "")
        raw = self.client.chat_multimodal_json(
            system_prompt=self._single_pass_system_prompt(
                skill_name=skill_name,
                skill_version=skill_version,
                skill_instructions=skill_instructions,
            ),
            user_text=self._single_pass_user_text(order_hint, issue_hint),
            image_urls=[materialized_source],
            temperature=0.0,
            # Two independent confidence fields plus waybill metadata can exceed
            # 100 tokens; truncation produces invalid JSON on harder images.
            max_tokens=160,
        )
        logger.info(
            "vision raw result index=%s name=%s raw=%s",
            index,
            attachment.name,
            json.dumps(raw, ensure_ascii=False, default=str)[:1200],
        )
        item = self._parse_single_pass_item(raw, index)
        self._cache_put(cache_key, item)
        self._disk_cache_put(cache_key, item)
        return item

    @staticmethod
    def _materialize_source(source: str) -> str:
        normalized = str(source or "").strip()
        if not normalized or normalized.startswith("data:"):
            return normalized

        tool_base_url = os.getenv(
            "AFTERSALES_JAVA_TOOL_BASE_URL",
            "http://java:8080/api/internal/agent-tools",
        ).rstrip("/")
        api_base_url = tool_base_url.split("/internal/agent-tools", 1)[0].rstrip("/")
        internal_upload_prefix = f"{api_base_url}/uploads/"
        if not normalized.startswith(internal_upload_prefix):
            return normalized

        max_bytes = max(1, int(os.getenv("VISION_INTERNAL_IMAGE_MAX_BYTES", "10485760")))
        try:
            download_request = request.Request(
                normalized,
                headers={"Accept": "image/*"},
                method="GET",
            )
            with request.urlopen(download_request, timeout=10) as response:
                content_type = str(response.headers.get("Content-Type") or "image/jpeg")
                if not content_type.lower().startswith("image/"):
                    raise LLMError("internal evidence URL did not return an image")
                image_bytes = response.read(max_bytes + 1)
                if len(image_bytes) > max_bytes:
                    raise LLMError("internal evidence image exceeds size limit")
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"failed to load internal evidence image: {exc.__class__.__name__}"
            ) from exc
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{content_type.split(';', 1)[0]};base64,{encoded}"

    def _cache_key(
        self,
        source: str,
        order_hint: str | None,
        issue_hint: str | None = None,
        skill_version: str | None = None,
    ) -> str:
        order_numbers = "|".join(re.findall(r"(?:ORD)?\d{8,}", order_hint or ""))
        issue = re.sub(r"\s+", " ", str(issue_hint or "")).strip()[:500]
        digest = hashlib.sha256(
            f"{source}\n{issue}\n{skill_version or ''}".encode("utf-8")
        ).hexdigest()
        return f"{self.PROMPT_VERSION}:{self.client.config.model}:{digest}:{order_numbers}"

    @staticmethod
    def _disk_cache_path() -> Path | None:
        configured = os.getenv("VISION_DISK_CACHE_PATH", "").strip()
        if not configured:
            return None
        return Path(configured).expanduser().resolve()

    @classmethod
    def _disk_cache_get(cls, key: str) -> ImageReviewItem | None:
        path = cls._disk_cache_path()
        if path is None or not path.exists():
            return None
        ttl = max(1, int(os.getenv("VISION_CACHE_TTL_SECONDS", "300")))
        try:
            with sqlite3.connect(path, timeout=2) as connection:
                row = connection.execute(
                    "SELECT created_at, result_json FROM vision_cache WHERE cache_key = ?", (key,)
                ).fetchone()
                if row is None or time.time() - float(row[0]) > ttl:
                    if row is not None:
                        connection.execute("DELETE FROM vision_cache WHERE cache_key = ?", (key,))
                    return None
                payload = json.loads(str(row[1]))
                if isinstance(payload, dict):
                    payload["verification_limitations"] = tuple(
                        payload.get("verification_limitations") or ()
                    )
                item = ImageReviewItem(**payload)
                cls._cache_put(key, item)
                logger.info("vision disk cache hit")
                return item
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            logger.warning("vision disk cache read failed error=%s", exc.__class__.__name__)
            return None

    @classmethod
    def _disk_cache_put(cls, key: str, item: ImageReviewItem) -> None:
        path = cls._disk_cache_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path, timeout=2) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS vision_cache (cache_key TEXT PRIMARY KEY, created_at REAL NOT NULL, result_json TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT OR REPLACE INTO vision_cache(cache_key, created_at, result_json) VALUES (?, ?, ?)",
                    (key, time.time(), json.dumps(asdict(item), ensure_ascii=False)),
                )
        except (OSError, sqlite3.Error) as exc:
            logger.warning("vision disk cache write failed error=%s", exc.__class__.__name__)

    @classmethod
    def _cache_get(cls, key: str) -> ImageReviewItem | None:
        ttl = max(1, int(os.getenv("VISION_CACHE_TTL_SECONDS", "300")))
        with cls._cache_lock:
            entry = cls._cache.get(key)
            if entry is None:
                return None
            created_at, item = entry
            if time.monotonic() - created_at > ttl:
                cls._cache.pop(key, None)
                return None
            cls._cache.move_to_end(key)
            return item

    @classmethod
    def _cache_put(cls, key: str, item: ImageReviewItem) -> None:
        capacity = max(1, int(os.getenv("VISION_CACHE_MAX_ENTRIES", "128")))
        with cls._cache_lock:
            cls._cache[key] = (time.monotonic(), item)
            cls._cache.move_to_end(key)
            while len(cls._cache) > capacity:
                cls._cache.popitem(last=False)

    @staticmethod
    def _single_pass_system_prompt(
        *,
        skill_name: str | None = None,
        skill_version: str | None = None,
        skill_instructions: str | None = None,
    ) -> str:
        schema = {
            "image_type": "商品照片|外包装照片|物流面单照片|不确定",
            "is_clear": True,
            "has_damage": False,
            "has_outer_package": False,
            "has_logistics_label": False,
            "matches_order": False,
            "confidence": "0到1之间的小数，表示整个判断的可靠程度",
            "damage_confidence": "0到1之间的小数，表示存在肉眼可见破损的概率",
            "evidence_category": "physical_damage|functional_issue|wrong_item|missing_part|identity_mismatch|logistics|packaging|other|none",
            "observed_issue_type": "图片中直接可见的问题类型，无法判断则留空",
            "issue_visible": False,
            "issue_description": "只描述图片中直接可见的异常，不能推测原因",
            "product_identity_visible": False,
            "evidence_relevance": "0到1之间的小数，表示图片与用户问题描述的相关程度",
            "evidence_consistency": "consistent|contradictory|uncertain",
            "tampering_suspected": False,
            "verification_limitations": ["遮挡、模糊、缺少商品身份等视觉核验局限"],
            "courier_company": "",
            "tracking_number": "",
            "sender_name": "",
            "receiver_name": "",
            "notes": "20字以内简短说明",
        }
        base_prompt = (
            "你是售后图片审核器，只分析当前一张图，不参考文件名。"
            "将主体互斥分类为商品照片、外包装照片、物流面单照片或不确定；"
            "判断清晰度及肉眼可见的破损、裂纹、断裂、碎裂或明显变形。"
            "仅物流面单可提取快递和收寄信息；看不清就留空，不得猜测。"
            "只输出JSON，不输出解释或Markdown。字段严格为："
            "confidence 与 damage_confidence 必须根据当前图片独立评估，不得照抄示例或使用固定默认值；"
            "图片模糊、遮挡、反光、主体过小或破损不明显时，必须降低相应置信度。"
            "除肉眼破损外，还要识别图片中直接可见的功能报错、错发、缺件、型号或标签不符等通用售后凭证。"
            "issue_description 只能描述可见现象，不得推断故障根因；"
            "evidence_relevance 只衡量图片与用户问题的相关性，不代表退款、通过或责任认定；"
            "不得作出审核通过、退款、驳回、责任归属等业务决定。"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        instructions = str(skill_instructions or "").strip()
        if not instructions:
            return base_prompt
        identity = "@".join(
            value
            for value in (
                str(skill_name or "").strip(),
                str(skill_version or "").strip(),
            )
            if value
        )
        return (
            f"{base_prompt}\nActive project skill {identity}:\n"
            f"{instructions[:6000]}"
        )

    @staticmethod
    def _single_pass_user_text(
        order_hint: str | None,
        issue_hint: str | None = None,
    ) -> str:
        payload = {
            "task": "review_single_image_once",
            "focus": [
                "image_type",
                "is_clear",
                "has_damage",
                "confidence",
                "damage_confidence",
                "has_outer_package",
                "has_logistics_label",
                "matches_order",
                "evidence_category",
                "observed_issue_type",
                "issue_visible",
                "issue_description",
                "product_identity_visible",
                "evidence_relevance",
                "evidence_consistency",
                "tampering_suspected",
                "verification_limitations",
                "courier_company",
                "tracking_number",
                "sender_name",
                "receiver_name",
            ],
            "order_hint": order_hint,
            "user_issue_hint": issue_hint,
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
        contains_damage = bool(raw.get("has_damage"))
        evidence_category = str(raw.get("evidence_category") or "").strip()
        if evidence_category not in {
            "physical_damage",
            "functional_issue",
            "wrong_item",
            "missing_part",
            "identity_mismatch",
            "logistics",
            "packaging",
            "other",
            "none",
        }:
            evidence_category = ""
        if contains_damage and evidence_category in {"", "none"}:
            evidence_category = "physical_damage"
        consistency = str(
            raw.get("evidence_consistency") or "uncertain"
        ).strip().lower()
        if consistency not in {"consistent", "contradictory", "uncertain"}:
            consistency = "uncertain"
        relevance = VisionReviewService._parse_confidence(
            raw.get("evidence_relevance")
        )
        if contains_damage and relevance <= 0.0:
            relevance = VisionReviewService._parse_confidence(
                raw.get("damage_confidence") or raw.get("confidence")
            )
        limitations = tuple(
            text
            for text in (
                re.sub(r"\s+", " ", str(value or "")).strip()[:160]
                for value in (
                    raw.get("verification_limitations")
                    if isinstance(raw.get("verification_limitations"), list)
                    else []
                )[:5]
            )
            if text
        )
        item = ImageReviewItem(
            name=f"image_{index}",
            image_type=image_type,
            is_clear=bool(raw.get("is_clear")),
            contains_damage_area=contains_damage,
            contains_outer_package=bool(raw.get("has_outer_package")),
            contains_logistics_label=bool(raw.get("has_logistics_label")),
            logistics_matches_order=bool(raw.get("matches_order")),
            courier_company=str(raw.get("courier_company") or ""),
            tracking_number=str(raw.get("tracking_number") or ""),
            sender_name=str(raw.get("sender_name") or ""),
            receiver_name=str(raw.get("receiver_name") or ""),
            confidence=VisionReviewService._parse_confidence(raw.get("confidence")),
            damage_confidence=VisionReviewService._parse_confidence(raw.get("damage_confidence")),
            notes=str(raw.get("notes") or ""),
            evidence_category=evidence_category,
            observed_issue_type=str(raw.get("observed_issue_type") or "").strip()[:80],
            issue_visible=bool(raw.get("issue_visible")) or contains_damage,
            issue_description=str(raw.get("issue_description") or "").strip()[:200],
            product_identity_visible=bool(raw.get("product_identity_visible")),
            evidence_relevance=relevance,
            evidence_consistency=consistency,
            tampering_suspected=bool(raw.get("tampering_suspected")),
            verification_limitations=limitations,
        )
        return VisionReviewService._normalize_classification_item(item)

    @staticmethod
    def _parse_confidence(value: object) -> float:
        try:
            return max(0.0, min(1.0, float(value or 0.0)))
        except (TypeError, ValueError):
            return 0.0

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
            damage_confidence=item.damage_confidence,
            notes=item.notes,
            evidence_category=item.evidence_category,
            observed_issue_type=item.observed_issue_type,
            issue_visible=item.issue_visible,
            issue_description=item.issue_description,
            product_identity_visible=item.product_identity_visible,
            evidence_relevance=item.evidence_relevance,
            evidence_consistency=item.evidence_consistency,
            tampering_suspected=item.tampering_suspected,
            verification_limitations=item.verification_limitations,
        )

    @staticmethod
    def _aggregate_generic_evidence(
        items: tuple[ImageReviewItem, ...],
    ) -> dict[str, object]:
        visible_items = tuple(
            item
            for item in items
            if item.issue_visible or item.contains_damage_area
        )
        relevant_items = tuple(
            item
            for item in visible_items
            if item.is_clear
            and (
                item.contains_damage_area
                or item.evidence_relevance >= 0.6
            )
        )
        tampering_suspected = any(
            item.tampering_suspected for item in items
        )
        contradictory = any(
            item.evidence_consistency == "contradictory" for item in items
        )
        if tampering_suspected or contradictory:
            evidence_consistent: bool | None = False
        elif relevant_items:
            evidence_consistent = True
        else:
            evidence_consistent = None
        return {
            "has_visible_issue": bool(visible_items),
            "evidence_relevant": bool(relevant_items),
            "evidence_consistent": evidence_consistent,
            "tampering_suspected": tampering_suspected,
            "evidence_categories": tuple(
                dict.fromkeys(
                    item.evidence_category
                    for item in items
                    if item.evidence_category
                    and item.evidence_category != "none"
                )
            ),
            "observed_issue_types": tuple(
                dict.fromkeys(
                    item.observed_issue_type
                    for item in items
                    if item.observed_issue_type
                )
            ),
            "verification_limitations": tuple(
                dict.fromkeys(
                    limitation
                    for item in items
                    for limitation in item.verification_limitations
                    if limitation
                )
            ),
        }

    @staticmethod
    def _collect_missing(items: tuple[ImageReviewItem, ...]) -> tuple[str, ...]:
        missing: list[str] = []
        if not items or not all(item.is_clear for item in items):
            missing.append("清晰商品问题照片")
        has_relevant_visible_issue = any(
            item.is_clear
            and not item.tampering_suspected
            and (item.issue_visible or item.contains_damage_area)
            and (
                item.contains_damage_area
                or item.evidence_relevance >= 0.6
            )
            for item in items
        )
        if not has_relevant_visible_issue:
            missing.append("能够显示商品问题的照片")
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
        for item in items:
            if (
                item.issue_visible
                and item.evidence_relevance >= 0.6
                and not item.contains_damage_area
            ):
                label = (
                    item.observed_issue_type
                    or item.evidence_category
                    or "可见问题"
                )
                if label not in seen:
                    seen.append(label)
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
            "confidence": item.confidence,
            "damage_confidence": item.damage_confidence,
            "notes": item.notes,
            "evidence_category": item.evidence_category,
            "observed_issue_type": item.observed_issue_type,
            "issue_visible": item.issue_visible,
            "issue_description": item.issue_description,
            "product_identity_visible": item.product_identity_visible,
            "evidence_relevance": item.evidence_relevance,
            "evidence_consistency": item.evidence_consistency,
            "tampering_suspected": item.tampering_suspected,
            "verification_limitations": list(item.verification_limitations),
        }
