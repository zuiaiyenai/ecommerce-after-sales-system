import io

from pypdf import PdfWriter
import pytest
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from after_sales_agent.application.knowledge_ingestion.parsers.markdown import parse_markdown
from after_sales_agent.application.knowledge_ingestion.parsers.plain_text import (
    parse_plain_text,
)
from after_sales_agent.application.knowledge_ingestion.parsers import pdf as pdf_parser
from after_sales_agent.application.knowledge_ingestion.parsers.pdf import parse_pdf
from after_sales_agent.application.knowledge_ingestion.section_builder import (
    HeadingStack,
    numbered_heading,
)


def _pdf_bytes(*pages: tuple[str, ...]) -> bytes:
    writer = PdfWriter()
    for lines in pages:
        _add_text_page(writer, lines)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _add_text_page(writer: PdfWriter, lines: tuple[str, ...]) -> None:
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    commands = ["BT /F1 12 Tf"]
    for index, line in enumerate(lines):
        commands.append(f"72 {250 - index * 30} Td ({line}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def _mixed_pdf_bytes(*, middle: str) -> bytes:
    writer = PdfWriter()
    _add_text_page(writer, ("First text page",))
    page = writer.add_blank_page(width=300, height=300)
    if middle == "image":
        image = DecodedStreamObject()
        image.set_data(b"\x00")
        image.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        image_ref = writer._add_object(image)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"q 100 0 0 100 10 10 cm /Im0 Do Q")
        page[NameObject("/Contents")] = writer._add_object(stream)
    _add_text_page(writer, ("Third text page",))
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_rejects_mixed_text_and_image_only_pages() -> None:
    with pytest.raises(pdf_parser.KnowledgeParseError, match="PDF_TEXT_LAYER_MISSING"):
        parse_pdf(_mixed_pdf_bytes(middle="image"))


def test_pdf_allows_genuinely_blank_page_between_text_pages() -> None:
    pages, blocks = parse_pdf(_mixed_pdf_bytes(middle="blank"))

    assert [page_number for page_number, _ in pages] == [1, 2, 3]
    assert [block.page_start for block in blocks] == [1, 3]


def test_pdf_page_text_extraction_exception_is_not_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TextPage:
        def extract_text(self) -> str:
            return "body"

    class BrokenPage:
        def extract_text(self) -> str:
            raise RuntimeError("extract failed")

    class Reader:
        is_encrypted = False
        pages = [TextPage(), BrokenPage()]

    monkeypatch.setattr(pdf_parser, "PdfReader", lambda _content: Reader())

    with pytest.raises(pdf_parser.KnowledgeParseError, match="FILE_DECODE_FAILED"):
        pdf_parser.extract_pdf_pages(b"pdf")


def test_pdf_margin_cleanup_removes_only_edge_occurrence_when_text_repeats_in_body() -> None:
    _, blocks = parse_pdf(
        _pdf_bytes(
            ("Return policy", "Lead one", "Return policy", "Body one", "Tail one", "Page 1"),
            ("Return policy", "Lead two", "Return policy", "Body two", "Tail two", "Page 2"),
            ("Return policy", "Lead three", "Return policy", "Body three", "Tail three", "Page 3"),
        )
    )

    texts = "\n".join(block.text for block in blocks)
    assert texts.count("Return policy") == 3


def test_pdf_keeps_heading_across_pages_and_removes_stable_margins() -> None:
    pages, blocks = parse_pdf(
        _pdf_bytes(
            ("Return policy", "1.1 Refund rules", "First page body", "Page 1"),
            ("Return policy", "Second page body", "Page 2"),
            ("Return policy", "Third page body", "Page 3"),
        )
    )

    assert len(pages) == 3
    assert all("Return policy" not in block.text for block in blocks)
    assert [block.page_start for block in blocks] == [1, 2, 3]
    assert all(block.heading_path == ("Refund rules",) for block in blocks)


def test_pdf_does_not_remove_margin_lines_from_short_documents() -> None:
    _, blocks = parse_pdf(
        _pdf_bytes(
            ("Important notice", "First body"),
            ("Important notice", "Second body"),
        )
    )

    assert any("Important notice" in block.text for block in blocks)


def test_pdf_margin_cleanup_preserves_blank_lines_between_body_paragraphs() -> None:
    _, blocks = parse_pdf(
        _pdf_bytes(
            ("Return policy", "Page one first paragraph", " ", "Page one second paragraph", "Page 1"),
            ("Return policy", "Page two first paragraph", " ", "Page two second paragraph", "Page 2"),
            ("Return policy", "Page three first paragraph", " ", "Page three second paragraph", "Page 3"),
        )
    )

    assert [block.text for block in blocks] == [
        "Page one first paragraph",
        "Page one second paragraph",
        "Page two first paragraph",
        "Page two second paragraph",
        "Page three first paragraph",
        "Page three second paragraph",
    ]


def test_heading_stack_replaces_same_or_deeper_heading_levels() -> None:
    headings = HeadingStack()

    assert headings.enter(1, "退款规则") == ("退款规则",)
    assert headings.enter(2, "凭证要求") == ("退款规则", "凭证要求")
    assert headings.enter(2, "退款时效") == ("退款规则", "退款时效")
    assert headings.path == ("退款规则", "退款时效")


def test_markdown_preserves_heading_paths_and_atomic_block_types() -> None:
    blocks = parse_markdown(
        """# 退款规则
## 凭证要求

- 图片凭证
- 检测报告

| 类型 | 要求 |
| --- | --- |
| 图片 | 清晰 |

```text
# not a heading
```
"""
    )

    assert [block.block_type for block in blocks] == ["list", "table", "code"]
    assert all(block.heading_path == ("退款规则", "凭证要求") for block in blocks)
    assert all(block.page_start is None and block.page_end is None for block in blocks)


def test_markdown_supports_setext_headings() -> None:
    blocks = parse_markdown("退款规则\n====\n\n正文")

    assert blocks[0].heading_path == ("退款规则",)
    assert blocks[0].text == "正文"


def test_plain_text_uses_only_conservative_numbered_headings() -> None:
    blocks = parse_plain_text("第一章 退款规则\n\n正文。\n\n普通短句\n继续说明。")

    assert blocks[0].heading_path == ("退款规则",)
    assert [block.text for block in blocks] == ["正文。", "普通短句\n继续说明。"]


def test_numbered_heading_requires_an_explicit_numbering_marker() -> None:
    assert numbered_heading("第一章 退款规则") == (1, "退款规则")
    assert numbered_heading("二、凭证要求") == (1, "凭证要求")
    assert numbered_heading("1.2 图片要求") == (2, "图片要求")
    assert numbered_heading("普通短句") is None


def test_markdown_groups_quotes_and_consecutive_paragraph_lines() -> None:
    blocks = parse_markdown("> 第一行\n> 第二行\n\n正文第一行\n正文第二行")

    assert [block.block_type for block in blocks] == ["quote", "paragraph"]
    assert [block.text for block in blocks] == [
        "> 第一行\n> 第二行",
        "正文第一行\n正文第二行",
    ]


def test_markdown_recognizes_tables_without_outer_pipes() -> None:
    blocks = parse_markdown("类型 | 要求\n--- | ---\n图片 | 清晰")

    assert [block.block_type for block in blocks] == ["table"]


def test_markdown_keeps_invalid_closing_fence_inside_code_block() -> None:
    blocks = parse_markdown(
        """````text
# not a heading
````not-a-close
- still code
````
# 后续标题
正文
"""
    )

    assert [block.block_type for block in blocks] == ["code", "paragraph"]
    assert "````not-a-close\n- still code" in blocks[0].text
    assert blocks[1].heading_path == ("后续标题",)


def test_parsers_package_exports_public_parse_functions() -> None:
    from after_sales_agent.application.knowledge_ingestion.parsers import (
        parse_markdown as exported_markdown,
    )
    from after_sales_agent.application.knowledge_ingestion.parsers import (
        parse_plain_text as exported_plain_text,
    )

    assert exported_markdown is parse_markdown
    assert exported_plain_text is parse_plain_text


def test_plain_text_keeps_markdown_like_lines_in_a_paragraph() -> None:
    blocks = parse_plain_text("普通说明\n- 不是列表\n> 不是引用\n| 不是表格 |\n\n后续说明")

    assert [block.block_type for block in blocks] == ["paragraph", "paragraph"]
    assert [block.text for block in blocks] == [
        "普通说明\n- 不是列表\n> 不是引用\n| 不是表格 |",
        "后续说明",
    ]
