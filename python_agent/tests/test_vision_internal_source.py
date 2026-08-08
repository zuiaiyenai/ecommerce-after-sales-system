from __future__ import annotations

from after_sales_agent.providers import vision_review_service
from after_sales_agent.providers.vision_review_service import VisionReviewService


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
