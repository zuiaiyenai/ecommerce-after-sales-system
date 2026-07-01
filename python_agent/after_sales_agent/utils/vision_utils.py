from __future__ import annotations

from typing import Any

from ..models import Attachment, ImageReviewItem, ImageReviewResult


def image_review_to_visual_evidence(image_review: ImageReviewResult | None) -> tuple[str, ...]:
    """Map model-facing image review flags back to business evidence names."""
    if image_review is None or not image_review.success:
        return ()

    evidence: list[str] = []
    if image_review.has_damage_area:
        evidence.append("破损照片")
    if image_review.has_outer_package:
        evidence.append("外包装照片")
    if image_review.has_logistics_label:
        evidence.append("物流面单照片")
    return tuple(evidence)


def is_visual_review_failed(
    attachments: tuple[Attachment, ...],
    image_review: ImageReviewResult | None,
) -> bool:
    """Treat uploaded images without a usable review result as pending visual verification."""
    if not attachments and image_review is None:
        return False
    if image_review is None:
        return True
    if not image_review.success:
        return True
    if not image_review.has_damage_area and not image_review.has_outer_package and not image_review.has_logistics_label:
        return True
    failure_markers = {"视觉模型不可用", "图片分析结果待补充"}
    return any(item in failure_markers for item in image_review.missing_visual_evidence)


def serialize_image_review(image_review: ImageReviewResult | None, *, include_items: bool = True) -> dict[str, Any] | None:
    """Keep API responses and LLM prompts on one shared image-review payload shape."""
    if image_review is None:
        return None

    payload: dict[str, Any] = {
        "success": image_review.success,
        "all_clear": image_review.all_clear,
        "has_damage_area": image_review.has_damage_area,
        "has_outer_package": image_review.has_outer_package,
        "has_logistics_label": image_review.has_logistics_label,
        "logistics_matches_order": image_review.logistics_matches_order,
        "courier_company": image_review.courier_company,
        "tracking_number": image_review.tracking_number,
        "sender_name": image_review.sender_name,
        "receiver_name": image_review.receiver_name,
        "missing_visual_evidence": list(image_review.missing_visual_evidence),
        "summary": image_review.summary,
    }
    if include_items:
        payload["items"] = [
            {
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
                "notes": item.notes,
            }
            for item in image_review.items
        ]
        payload["raw"] = image_review.raw
    return payload


def parse_image_review_payload(data: dict[str, Any] | None) -> ImageReviewResult | None:
    """Rehydrate cached frontend image-review payloads into the domain model."""
    if not isinstance(data, dict):
        return None

    items = tuple(
        ImageReviewItem(
            name=str(item.get("name") or ""),
            image_type=str(item.get("image_type") or ""),
            is_clear=bool(item.get("is_clear")),
            contains_damage_area=bool(item.get("contains_damage_area")),
            contains_outer_package=bool(item.get("contains_outer_package")),
            contains_logistics_label=bool(item.get("contains_logistics_label")),
            logistics_matches_order=bool(item.get("logistics_matches_order")),
            courier_company=str(item.get("courier_company") or ""),
            tracking_number=str(item.get("tracking_number") or ""),
            sender_name=str(item.get("sender_name") or ""),
            receiver_name=str(item.get("receiver_name") or ""),
            confidence=float(item.get("confidence") or 0.0),
            notes=str(item.get("notes") or ""),
        )
        for item in data.get("items") or []
        if isinstance(item, dict)
    )
    return ImageReviewResult(
        success=bool(data.get("success")),
        items=items,
        all_clear=bool(data.get("all_clear")),
        has_damage_area=bool(data.get("has_damage_area")),
        has_outer_package=bool(data.get("has_outer_package")),
        has_logistics_label=bool(data.get("has_logistics_label")),
        logistics_matches_order=bool(data.get("logistics_matches_order")),
        courier_company=str(data.get("courier_company") or ""),
        tracking_number=str(data.get("tracking_number") or ""),
        sender_name=str(data.get("sender_name") or ""),
        receiver_name=str(data.get("receiver_name") or ""),
        missing_visual_evidence=tuple(data.get("missing_visual_evidence") or ()),
        summary=str(data.get("summary") or ""),
        raw=data.get("raw") or {},
    )
