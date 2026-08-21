"""一次性回扫脚本：用 Jieba 填充所有存量 chunk 的 lexical_text 和 search_vector。

用法：
    python -m after_sales_agent.retrieval.search.backfill_lexical
    python -m after_sales_agent.retrieval.search.backfill_lexical --dsn "postgres://..."
    python -m after_sales_agent.retrieval.search.backfill_lexical --batch-size 200
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Iterable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

try:
    import jieba
except ImportError:  # pragma: no cover
    sys.exit("jieba is required: pip install jieba")

try:
    import psycopg
except ImportError:  # pragma: no cover
    sys.exit("psycopg is required: pip install 'psycopg[binary]'")


from after_sales_agent.retrieval.search.tokenize_ch import tokenize_chunk


def fetch_all_chunks(cur: psycopg.Cursor) -> list[tuple[int, str]]:
    """返回 [(chunk_id, chunk_text), ...]"""
    cur.execute("SELECT id, chunk_text FROM knowledge_chunk ORDER BY id")
    return cur.fetchall()


def update_batch(
    cur: psycopg.Cursor,
    batch: list[tuple[int, str, str]],
) -> int:
    """批量 UPDATE lexical_text 和 search_vector，返回更新行数。

    search_vector 通过 SQL to_tsvector('simple', %s) 生成，避免 Python 端
    构造 tsvector 字符串的注入风险。
    """
    if not batch:
        return 0
    sql = """
        UPDATE knowledge_chunk
        SET lexical_text = data.lexical_text,
            search_vector = to_tsvector('simple', data.lexical_text)
        FROM (VALUES %s) AS data(id, lexical_text)
        WHERE knowledge_chunk.id = data.id
    """
    # psycopg 的 execute_values 需要 sql.SQL 或直接用 executemany
    # 这里用简单的 executemany 兼容各版本
    updated = 0
    for chunk_id, chunk_text, lexical in batch:
        cur.execute(
            """
            UPDATE knowledge_chunk
            SET lexical_text = %s,
                search_vector = to_tsvector('simple', %s)
            WHERE id = %s
            """,
            (lexical, lexical, chunk_id),
        )
        if cur.rowcount:
            updated += 1
    return updated


def run(dsn: str, batch_size: int) -> None:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            chunks = fetch_all_chunks(cur)
            total = len(chunks)
            if total == 0:
                logger.info("No chunks found, nothing to backfill.")
                return

            logger.info("Found %d chunks to backfill.", total)

            # 预计算所有 lexical_text
            tokenized = [(cid, text, tokenize_chunk(text)) for cid, text in chunks]

            # 统计需要更新的（lexical_text 为空或 search_vector 为空的）
            to_update = [(cid, text, lex) for cid, text, lex in tokenized if not lex]
            already_done = total - len(to_update)
            logger.info(
                "Already filled: %d, need to update: %d", already_done, len(to_update)
            )

            if not to_update:
                logger.info("All chunks already have lexical_text. Skipping.")
                return

            updated_total = 0
            for i in range(0, len(to_update), batch_size):
                batch = to_update[i: i + batch_size]
                updated = update_batch(cur, batch)
                updated_total += updated
                logger.info(
                    "Batch %d-%d: updated %d rows",
                    i + 1,
                    min(i + batch_size, len(to_update)),
                    updated,
                )
            conn.commit()
            logger.info("Backfill complete. Total updated: %d / %d", updated_total, len(to_update))

            # 验证
            cur.execute("SELECT count(*) FROM knowledge_chunk WHERE search_vector = ''::tsvector")
            remaining = cur.fetchone()[0]
            logger.info("Remaining empty search_vector: %d / %d", remaining, total)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill lexical_text and search_vector for knowledge_chunk")
    parser.add_argument(
        "--dsn",
        default=os.getenv("PGVECTOR_DSN", ""),
        help="PostgreSQL DSN (default: PGVECTOR_DSN env var)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of chunks per UPDATE batch (default: 200)",
    )
    args = parser.parse_args()

    if not args.dsn:
        sys.exit("DSN is required. Set PGVECTOR_DSN or pass --dsn")

    run(args.dsn, args.batch_size)


if __name__ == "__main__":
    main()
