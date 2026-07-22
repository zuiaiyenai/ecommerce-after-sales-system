from after_sales_agent.application.knowledge_ingestion.parsers.markdown import parse_markdown
from after_sales_agent.application.knowledge_ingestion.parsers.plain_text import (
    parse_plain_text,
)
from after_sales_agent.application.knowledge_ingestion.section_builder import (
    HeadingStack,
    numbered_heading,
)


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
    assert "普通短句" in [block.text for block in blocks]


def test_numbered_heading_requires_an_explicit_numbering_marker() -> None:
    assert numbered_heading("第一章 退款规则") == (1, "退款规则")
    assert numbered_heading("二、凭证要求") == (1, "凭证要求")
    assert numbered_heading("1.2 图片要求") == (2, "图片要求")
    assert numbered_heading("普通短句") is None
