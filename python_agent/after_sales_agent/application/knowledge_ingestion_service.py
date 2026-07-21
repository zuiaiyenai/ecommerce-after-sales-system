from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Protocol


class KnowledgeParseError(ValueError):
    """A stable error code for document parsing failures."""


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


@dataclass(frozen=True)
class ParseResult:
    content: str
    policy_version: str | None
    valid_from: str | None
    valid_to: str | None
    chunks: list[DraftChunk]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _Section:
    heading_path: list[str]
    page_number: int | None
    text: str


class KnowledgeIngestionService:
    """Parse knowledge drafts without changing Java-owned document lifecycle state."""

    def __init__(self, classifier: MetadataClassifier | None = None) -> None:
        self._classifier = classifier

    def parse(
        self,
        *,
        file_name: str,
        content: bytes,
        knowledge_type: str,
        allowed_metadata: dict[str, list[str]],
    ) -> ParseResult:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".pdf":
            pages = self._pdf_pages(content)
        elif suffix in {".md", ".txt"}:
            pages = [(1, self._decode_text(content))]
        else:
            raise KnowledgeParseError("UNSUPPORTED_FILE_TYPE")

        sections = self._sections(suffix, pages)
        parsed_content = "\n\n".join(text for _, text in pages if text.strip())
        chunks = self._chunk_sections(sections, max_chars=700, overlap_chars=120)
        classified = self._classify(chunks, knowledge_type, allowed_metadata)
        return ParseResult(
            content=parsed_content,
            policy_version=self._find_document_value(parsed_content, ("policy_version", "policy version", "版本")),
            valid_from=self._find_document_value(parsed_content, ("valid_from", "valid from", "生效日期", "生效时间")),
            valid_to=self._find_document_value(parsed_content, ("valid_to", "valid to", "截止日期", "失效日期")),
            chunks=classified,
        )

    @staticmethod
    def _decode_text(content: bytes) -> str:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise KnowledgeParseError("FILE_DECODE_FAILED") from exc

    @staticmethod
    def _pdf_pages(content: bytes) -> list[tuple[int, str]]:
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError

            reader = PdfReader(__import__("io").BytesIO(content))
            if reader.is_encrypted:
                raise KnowledgeParseError("PDF_ENCRYPTED")
            pages = [(index, (page.extract_text() or "").strip()) for index, page in enumerate(reader.pages, start=1)]
        except KnowledgeParseError:
            raise
        except (PdfReadError, OSError, ValueError) as exc:
            raise KnowledgeParseError("FILE_DECODE_FAILED") from exc
        except Exception as exc:
            raise KnowledgeParseError("FILE_DECODE_FAILED") from exc
        if not any(text for _, text in pages):
            raise KnowledgeParseError("PDF_TEXT_LAYER_MISSING")
        return pages

    @staticmethod
    def _sections(suffix: str, pages: list[tuple[int, str]]) -> list[_Section]:
        if suffix != ".md":
            return [_Section([], page_number, text.strip()) for page_number, text in pages if text.strip()]

        sections: list[_Section] = []
        heading_stack: list[tuple[int, str]] = []
        current_lines: list[str] = []
        current_path: list[str] = []

        def append_section() -> None:
            text = "\n".join(current_lines).strip()
            if text:
                sections.append(_Section(list(current_path), 1, text))

        for line in pages[0][1].splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
            if match is None:
                current_lines.append(line)
                continue
            append_section()
            current_lines = []
            level = len(match.group(1))
            heading = match.group(2).strip()
            heading_stack = [(item_level, item_heading) for item_level, item_heading in heading_stack if item_level < level]
            heading_stack.append((level, heading))
            current_path = [item_heading for _, item_heading in heading_stack]
        append_section()
        return sections

    @staticmethod
    def _chunk_sections(sections: list[_Section], *, max_chars: int, overlap_chars: int) -> list[_Section]:
        chunks: list[_Section] = []
        for section in sections:
            units = KnowledgeIngestionService._split_units(section.text, max_chars)
            buffer = ""
            for unit in units:
                if not buffer:
                    buffer = unit
                    continue
                candidate = f"{buffer}\n\n{unit}"
                if len(candidate) <= max_chars:
                    buffer = candidate
                    continue
                chunks.append(_Section(section.heading_path, section.page_number, buffer))
                overlap = buffer[-overlap_chars:].strip()
                buffer = f"{overlap}\n\n{unit}" if overlap else unit
                while len(buffer) > max_chars:
                    chunks.append(_Section(section.heading_path, section.page_number, buffer[:max_chars].strip()))
                    buffer = buffer[max_chars - overlap_chars :].strip()
            if buffer.strip():
                chunks.append(_Section(section.heading_path, section.page_number, buffer.strip()))
        return chunks

    @staticmethod
    def _split_units(text: str, max_chars: int) -> list[str]:
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
        units: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= max_chars:
                units.append(paragraph)
                continue
            sentences = [sentence.strip() for sentence in re.split(r"(?<=[。！？；.!?;])\s*", paragraph) if sentence.strip()]
            for sentence in sentences:
                while len(sentence) > max_chars:
                    units.append(sentence[:max_chars].strip())
                    sentence = sentence[max_chars:].strip()
                if sentence:
                    units.append(sentence)
        return units

    def _classify(
        self,
        sections: list[_Section],
        knowledge_type: str,
        allowed_metadata: dict[str, list[str]],
    ) -> list[DraftChunk]:
        allowed = self._allowed_metadata(allowed_metadata)
        result: list[DraftChunk] = []
        for index, section in enumerate(sections):
            rules = self._rule_suggestions(section, allowed)
            missing = [key for key in allowed if rules[key] is None]
            model: dict[str, object] = {}
            model_available = False
            if missing:
                try:
                    model = self._classify_with_model(
                        text=section.text,
                        heading_path=section.heading_path,
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

            source = self._classification_source(rules, model_available)
            confidence = self._confidence(model.get("confidence")) if model_available else None
            reason = self._reason(rules, model if model_available else {})
            review_required = unknown_value or any(values[key] is None for key in allowed)
            result.append(
                DraftChunk(
                    chunk_index=index,
                    heading_path=section.heading_path,
                    page_number=section.page_number,
                    text=section.text,
                    product_categories=values["product_categories"],
                    scenes=values["scenes"],
                    intents=values["intents"],
                    classification_source=source,
                    classification_confidence=confidence,
                    classification_reason=reason,
                    review_required=review_required,
                )
            )
        return result

    @staticmethod
    def _allowed_metadata(raw: dict[str, list[str]]) -> dict[str, list[str]]:
        keys = ("product_categories", "scenes", "intents")
        return {
            key: [str(value).strip() for value in raw.get(key, []) if str(value).strip()]
            for key in keys
        }

    @staticmethod
    def _rule_suggestions(section: _Section, allowed: dict[str, list[str]]) -> dict[str, list[str] | None]:
        """Use only exact Java-provided terms; Python never keeps an enum catalogue."""
        text = " ".join([*section.heading_path, section.text]).lower()
        return {
            key: [value for value in values if KnowledgeIngestionService._contains_term(text, value)] or None
            for key, values in allowed.items()
        }

    @staticmethod
    def _contains_term(text: str, value: str) -> bool:
        normalized_value = value.strip().casefold()
        normalized_text = text.casefold()
        if not normalized_value:
            return False
        if any("\u4e00" <= character <= "\u9fff" for character in normalized_value):
            compact_value = re.sub(r"[\s_-]+", "", normalized_value)
            compact_text = re.sub(r"[\s_-]+", "", normalized_text)
            return compact_value in compact_text

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
