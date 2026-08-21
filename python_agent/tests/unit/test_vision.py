from __future__ import annotations

from after_sales_agent.providers import vision_review_service
from after_sales_agent.providers.vision_review_service import VisionReviewService
from after_sales_agent.domain.models import Attachment, ImageReviewItem


def test_parse_keeps_overall_and_damage_confidence_separate() -> None:
    item = VisionReviewService._parse_single_pass_item(
        {
            "image_type": "商品照片",
            "is_clear": True,
            "has_damage": True,
            "confidence": 0.92,
            "damage_confidence": 0.73,
        },
        1,
    )

    assert item.confidence == 0.92
    assert item.damage_confidence == 0.73


def test_prompt_has_no_fixed_point_nine_confidence_anchor() -> None:
    prompt = VisionReviewService._single_pass_system_prompt()

    assert '"confidence": 0.9' not in prompt
    assert "damage_confidence" in prompt


def test_prompt_binds_versioned_formal_review_skill() -> None:
    prompt = VisionReviewService._single_pass_system_prompt(
        skill_name="formal-review",
        skill_version="version-1",
        skill_instructions="只评估直接可见的凭证。",
    )

    assert "formal-review@version-1" in prompt
    assert "只评估直接可见的凭证。" in prompt


def test_disk_cache_survives_memory_cache_clear(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VISION_DISK_CACHE_PATH", str(tmp_path / "vision.sqlite3"))
    monkeypatch.setenv("VISION_CACHE_TTL_SECONDS", "300")
    item = ImageReviewItem(
        name="image_1", image_type="商品照片", is_clear=True,
        contains_damage_area=True, contains_outer_package=False,
        contains_logistics_label=False, damage_confidence=0.93,
    )

    VisionReviewService._disk_cache_put("key", item)
    VisionReviewService._cache.clear()

    assert VisionReviewService._disk_cache_get("key") == item


def test_clear_damaged_product_photo_does_not_require_package_or_waybill() -> None:
    item = ImageReviewItem(
        name="image_1",
        image_type="商品照片",
        is_clear=True,
        contains_damage_area=True,
        contains_outer_package=False,
        contains_logistics_label=False,
        confidence=0.95,
        damage_confidence=0.92,
    )

    assert VisionReviewService._collect_missing((item,)) == ()


def test_parse_preserves_generic_functional_issue_evidence() -> None:
    item = VisionReviewService._parse_single_pass_item(
        {
            "image_type": "商品照片",
            "is_clear": True,
            "has_damage": False,
            "evidence_category": "functional_issue",
            "observed_issue_type": "screen_error",
            "issue_visible": True,
            "issue_description": "屏幕显示错误提示",
            "product_identity_visible": True,
            "evidence_relevance": 0.94,
            "evidence_consistency": "consistent",
            "tampering_suspected": False,
            "verification_limitations": [],
            "confidence": 0.91,
            "damage_confidence": 0.02,
        },
        1,
    )

    assert item.evidence_category == "functional_issue"
    assert item.observed_issue_type == "screen_error"
    assert item.issue_visible is True
    assert item.issue_description == "屏幕显示错误提示"
    assert item.product_identity_visible is True
    assert item.evidence_relevance == 0.94
    assert item.evidence_consistency == "consistent"
    assert item.tampering_suspected is False
    assert item.verification_limitations == ()


def test_clear_relevant_functional_screenshot_is_valid_visual_evidence() -> None:
    item = ImageReviewItem(
        name="image_1",
        image_type="商品照片",
        is_clear=True,
        contains_damage_area=False,
        contains_outer_package=False,
        contains_logistics_label=False,
        confidence=0.93,
        evidence_category="functional_issue",
        observed_issue_type="screen_error",
        issue_visible=True,
        issue_description="屏幕显示错误提示",
        evidence_relevance=0.92,
        evidence_consistency="consistent",
    )

    assert VisionReviewService._collect_missing((item,)) == ()


def test_review_attachments_aggregates_generic_visual_evidence(monkeypatch) -> None:
    service = object.__new__(VisionReviewService)
    service.client = type(
        "Client",
        (),
        {"config": type("Config", (), {"model": "test-vision"})()},
    )()
    item = ImageReviewItem(
        name="image_1",
        image_type="商品照片",
        is_clear=True,
        contains_damage_area=False,
        contains_outer_package=False,
        contains_logistics_label=False,
        confidence=0.93,
        evidence_category="functional_issue",
        observed_issue_type="screen_error",
        issue_visible=True,
        evidence_relevance=0.92,
        evidence_consistency="consistent",
    )
    monkeypatch.setattr(
        service,
        "_review_single_attachment",
        lambda *args, **kwargs: item,
    )

    result = service.review_attachments(
        (Attachment(kind="image", name="issue.png", source="data:image/png;base64,AA"),),
        order_hint="headphone",
        issue_hint="screen shows an error",
    )

    assert result.has_visible_issue is True
    assert result.evidence_relevant is True
    assert result.evidence_consistent is True
    assert result.evidence_categories == ("functional_issue",)
    assert result.observed_issue_types == ("screen_error",)
    assert "screen_error" in result.summary


def test_single_image_prompt_receives_issue_without_asking_for_business_decision() -> None:
    prompt = VisionReviewService._single_pass_user_text(
        "headphone",
        "screen shows an error",
    )

    assert "screen shows an error" in prompt
    assert "approve" not in prompt.lower()
    assert "refund" not in prompt.lower()


def test_internal_java_image_is_materialized_as_data_url(monkeypatch) -> None:
    class Response:
        headers = {"Content-Type": "image/png"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size=-1):
            return b"clear-image-bytes"

    monkeypatch.setattr(
        vision_review_service.request,
        "urlopen",
        lambda *_args, **_kwargs: Response(),
    )

    source = VisionReviewService._materialize_source(
        "http://java:8080/api/uploads/2026/07/30/damage.png"
    )

    assert source.startswith("data:image/png;base64,")
