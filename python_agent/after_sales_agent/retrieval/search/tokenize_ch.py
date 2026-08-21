"""Jieba tokenization helpers for Chinese lexical retrieval.

Extracted from backfill_lexical.py so it can be imported in tests
without triggering the psycopg import requirement.
"""
from __future__ import annotations


def tokenize_chunk(text: str) -> str:
    """用 Jieba search 模式分词，空格 join 得到 lexical_text。"""
    import jieba
    if not text:
        return ""
    return " ".join(word for word, _, _ in jieba.tokenize(text, mode="search"))
