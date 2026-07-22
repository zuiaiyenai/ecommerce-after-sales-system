from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
import re
from typing import Protocol
import unicodedata

from after_sales_agent.application.knowledge_ingestion.models import KnowledgeParseError, StructuredChunk
from after_sales_agent.application.knowledge_ingestion.parsers.markdown import parse_markdown
from after_sales_agent.application.knowledge_ingestion.parsers.pdf import parse_pdf
from after_sales_agent.application.knowledge_ingestion.parsers.plain_text import parse_plain_text
from after_sales_agent.application.knowledge_ingestion.structured_chunker import StructuredChunker


logger = logging.getLogger(__name__)


class MetadataClassifier(Protocol):
    def classify(self, **kwargs: object) -> dict[str, object]: ...


@dataclass(frozen=True)
class DraftChunk:
    chunk_index: int
    heading_path: list[str]
    page_number: int | None
    text: str
    product_categories: list[str] | None
    scenes: list[str] | None
    intents: list[str] | None
    classification_source: str
    classification_confidence: float | None
    classification_reason: str | None
    review_required: bool
    metadata: dict[str, object]


@dataclass(frozen=True)
class ParseResult:
    content: str
    policy_version: str | None
    valid_from: str | None
    valid_to: str | None
    chunks: list[DraftChunk]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class KnowledgeIngestionService:
    """Parse and classify knowledge drafts without changing Java-owned lifecycle state."""

    def __init__(
        self,
        classifier: MetadataClassifier | None = None,
        chunker: StructuredChunker | None = None,
    ) -> None:
        self._classifier = classifier
        self._chunker = chunker or StructuredChunker()

    def parse(
        self,
        *,
        file_name: str,
        content: bytes,
        knowledge_type: str,
        allowed_metadata: dict[str, list[str]],
    ) -> ParseResult:
        source_format, parsed_content, structured_chunks = self._parse_by_suffix(file_name, content)
        chunks = self._classify(structured_chunks, knowledge_type, allowed_metadata)
        self._log_summary(source_format, structured_chunks)
        return ParseResult(
            content=parsed_content,
            policy_version=self._find_document_value(parsed_content, ("policy_version", "policy version", "版本")),
            valid_from=self._find_document_value(parsed_content, ("valid_from", "valid from", "生效日期", "生效时间")),
            valid_to=self._find_document_value(parsed_content, ("valid_to", "valid to", "截止日期", "失效日期")),
            chunks=chunks,
        )

    def _parse_by_suffix(self, file_name: str, content: bytes) -> tuple[str, str, list[StructuredChunk]]:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".pdf":
            pages, blocks = parse_pdf(content)
            parsed_content = "\n\n".join(text.strip() for _, text in pages if text.strip())
        elif suffix == ".md":
            parsed_content = self._decode_text(content)
            blocks = parse_markdown(parsed_content)
        elif suffix == ".txt":
            parsed_content = self._decode_text(content)
            blocks = parse_plain_text(parsed_content)
        else:
            raise KnowledgeParseError("UNSUPPORTED_FILE_TYPE")
        return suffix[1:], parsed_content, self._chunker.chunk(blocks)

    @staticmethod
    def _decode_text(content: bytes) -> str:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise KnowledgeParseError("FILE_DECODE_FAILED") from exc

    def _classify(
        self,
        chunks: list[StructuredChunk],
        knowledge_type: str,
        allowed_metadata: dict[str, list[str]],
    ) -> list[DraftChunk]:
        allowed = self._allowed_metadata(allowed_metadata)
        result: list[DraftChunk] = []
        for index, chunk in enumerate(chunks):
            rules = self._rule_suggestions(chunk, allowed)
            missing = [key for key in allowed if rules[key] is None and allowed[key]]
            model: dict[str, object] = {}
            model_available = False
            if missing:
                try:
                    model = self._classify_with_model(
                        text=chunk.text,
                        heading_path=list(chunk.heading_path),
                        knowledge_type=knowledge_type,
                        allowed_metadata={key: allowed[key] for key in missing},
                    )
                    model_available = bool(model)
                except Exception:
                    model = {}

            values: dict[str, list[str] | None] = {}
            unknown_value = False
            for key in allowed:
                if rules[key] is not None:
                    values[key] = rules[key]
                    continue
                values[key], had_unknown = self._intersect_allowed(model.get(key), allowed[key])
                unknown_value = unknown_value or had_unknown

            result.append(
                DraftChunk(
                    chunk_index=index,
                    heading_path=list(chunk.heading_path),
                    page_number=chunk.page_start,
                    text=chunk.text,
                    product_categories=values["product_categories"],
                    scenes=values["scenes"],
                    intents=values["intents"],
                    classification_source=self._classification_source(rules, model_available),
                    classification_confidence=self._confidence(model.get("confidence")) if model_available else None,
                    classification_reason=self._reason(rules, model if model_available else {}),
                    review_required=unknown_value or any(values[key] is None for key in allowed),
                    metadata={
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "content_types": list(chunk.content_types),
                        "estimated_tokens": chunk.estimated_tokens,
                        "chunking_strategy": self._chunker.config.chunking_strategy,
                    },
                )
            )
        return result

    def _log_summary(self, source_format: str, chunks: list[StructuredChunk]) -> None:
        token_counts = [chunk.estimated_tokens for chunk in chunks]
        logger.info(
            "knowledge_ingestion_summary source_format=%s chunk_count=%d max_estimated_tokens=%d "
            "average_estimated_tokens=%.2f distinct_heading_paths=%d cross_page_chunk_count=%d strategy=%s",
            source_format,
            len(chunks),
            max(token_counts, default=0),
            sum(token_counts) / len(token_counts) if token_counts else 0.0,
            len({chunk.heading_path for chunk in chunks}),
            sum(
                chunk.page_start is not None
                and chunk.page_end is not None
                and chunk.page_start != chunk.page_end
                for chunk in chunks
            ),
            self._chunker.config.chunking_strategy,
        )

    @staticmethod
    def _allowed_metadata(raw: dict[str, list[str]]) -> dict[str, list[str]]:
        keys = ("product_categories", "scenes", "intents")
        return {
            key: [str(value).strip() for value in raw.get(key, []) if str(value).strip()]
            for key in keys
        }

    @staticmethod
    def _rule_suggestions(
        chunk: StructuredChunk,
        allowed: dict[str, list[str]],
    ) -> dict[str, list[str] | None]:
        """Use only exact Java-provided terms; Python never keeps an enum catalogue."""
        text = " ".join([*chunk.heading_path, chunk.text]).lower()
        return {
            key: [value for value in values if KnowledgeIngestionService._contains_term(text, value)] or None
            for key, values in allowed.items()
        }

    @staticmethod
    def _contains_term(text: str, value: str) -> bool:
        normalized_value = unicodedata.normalize("NFKC", value).strip().casefold()
        normalized_text = unicodedata.normalize("NFKC", text).casefold()
        if not normalized_value:
            return False
        if any("\u4e00" <= character <= "\u9fff" for character in normalized_value):
            phrase_parts = [re.escape(part) for part in normalized_value.split() if part]
            if not phrase_parts:
                return False
            pattern = r"(?<!\w)" + r"\s+".join(phrase_parts) + r"(?!\w)"
            return re.search(pattern, normalized_text) is not None

        terms = [re.escape(term) for term in re.split(r"[\s_-]+", normalized_value) if term]
        if not terms:
            return False
        pattern = r"(?<!\w)" + r"[\s_-]+".join(terms) + r"(?!\w)"
        return re.search(pattern, normalized_text) is not None

    def _classify_with_model(
        self,
        *,
        text: str,
        heading_path: list[str],
        knowledge_type: str,
        allowed_metadata: dict[str, list[str]],
    ) -> dict[str, object]:
        if self._classifier is not None:
            response = self._classifier.classify(
                text=text,
                heading_path=heading_path,
                knowledge_type=knowledge_type,
                allowed_metadata=allowed_metadata,
            )
            return response if isinstance(response, dict) else {}

        from after_sales_agent.providers.llm_client import get_llm_client

        return get_llm_client().chat_json(
            system_prompt=(
                "Classify one knowledge draft using only the allowed metadata values. "
                "Return JSON with product_categories, scenes, intents, confidence, and reason."
            ),
            user_prompt=json.dumps(
                {
                    "knowledge_type": knowledge_type,
                    "heading_path": heading_path,
                    "text": text,
                    "allowed_metadata": allowed_metadata,
                },
                ensure_ascii=False,
            ),
        )

    @staticmethod
    def _intersect_allowed(value: object, allowed: list[str]) -> tuple[list[str] | None, bool]:
        values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
        canonical = {item.lower(): item for item in allowed}
        matched: list[str] = []
        unknown = False
        for item in values:
            candidate = str(item).strip().lower()
            if not candidate:
                continue
            canonical_value = canonical.get(candidate)
            if canonical_value is None:
                unknown = True
            elif canonical_value not in matched:
                matched.append(canonical_value)
        return (matched or None, unknown)

    @staticmethod
    def _classification_source(rules: dict[str, list[str] | None], model_available: bool) -> str:
        rule_used = any(value is not None for value in rules.values())
        if rule_used and model_available:
            return "rule_and_model"
        if rule_used:
            return "rule"
        return "model" if model_available else "unclassified"

    @staticmethod
    def _confidence(value: object) -> float | None:
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _reason(rules: dict[str, list[str] | None], model: dict[str, object]) -> str | None:
        reason = str(model.get("reason") or "").strip()
        if reason:
            return reason
        used = [key for key, value in rules.items() if value]
        return f"matched allowed {', '.join(used)}" if used else None

    @staticmethod
    def _find_document_value(content: str, labels: tuple[str, ...]) -> str | None:
        for label in labels:
            match = re.search(rf"(?:^|\n)\s*{re.escape(label)}\s*[:：]\s*([^\n]+)", content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None
