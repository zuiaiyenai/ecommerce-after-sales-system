"""Audit RAG knowledge coverage without hard-coding category/scene combinations.

The report distinguishes a direct category+scene document from safe fallbacks
(same-scene general knowledge, same-category default knowledge, and global
knowledge), and also checks whether each active document has been chunked.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENES = (
    "product_damage",
    "package_damage",
    "quality_issue",
    "wrong_or_missing_items",
    "logistics_issue",
    "progress_query",
)
GENERAL_VALUES = {"", "general", "通用", "all", "*"}
SCENE_CANONICAL_ALIASES = {
    "damage": "product_damage",
    "product_damage": "product_damage",
    "logistics_damage": "logistics_issue",
    "logistics_issue": "logistics_issue",
    "wrong_item": "wrong_or_missing_items",
    "missing_item": "wrong_or_missing_items",
    "wrong_or_missing_items": "wrong_or_missing_items",
}


def load_local_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (REPO_ROOT / "python_agent" / ".env", REPO_ROOT / ".env"):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        break
    return values


def normalized(value: Any) -> str:
    return str(value or "").strip()


def is_general(value: Any) -> bool:
    return normalized(value).lower() in GENERAL_VALUES


def canonical_scene(value: Any) -> str:
    raw = normalized(value).lower()
    if raw in GENERAL_VALUES:
        return "general"
    return SCENE_CANONICAL_ALIASES.get(raw, raw)


def coverage_level(
    records: dict[tuple[str, str], dict[str, int]], category: str, scene: str
) -> tuple[str, dict[str, int]]:
    """Return the best available knowledge scope for one category/scene pair."""
    direct = records.get((category, scene), {})
    scene_default = records.get(("general", scene), {})
    category_default = records.get((category, "general"), {})
    global_default = records.get(("general", "general"), {})
    candidates = (
        ("direct", direct),
        ("scene_default", scene_default),
        ("category_default", category_default),
        ("global_default", global_default),
    )
    for level, item in candidates:
        if item.get("documents", 0) > 0:
            return level, item
    return "missing", {"documents": 0, "indexed_documents": 0, "chunks": 0}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 知识库覆盖审计报告",
        "",
        "该报告由 `tools/audit_knowledge_coverage.py` 生成。`direct` 表示品类与场景都有专属知识；其余层级表示检索会依赖分层回退。",
        "",
        "## 汇总",
        "",
        f"- 活跃知识文档：{report['summary']['active_documents']}",
        f"- 已向量化文档：{report['summary']['indexed_documents']}",
        f"- 知识块：{report['summary']['chunks']}",
        f"- 审计组合：{report['summary']['combination_count']}",
        "",
        "| 覆盖层级 | 组合数 | 含义 |",
        "|---|---:|---|",
        f"| direct | {report['summary']['levels'].get('direct', 0)} | 品类和场景专属知识 |",
        f"| scene_default | {report['summary']['levels'].get('scene_default', 0)} | 保留场景的通用知识 |",
        f"| category_default | {report['summary']['levels'].get('category_default', 0)} | 保留品类的默认知识 |",
        f"| global_default | {report['summary']['levels'].get('global_default', 0)} | 全局通用知识 |",
        f"| missing | {report['summary']['levels'].get('missing', 0)} | 无可用知识 |",
        "",
        "## 待补齐清单",
        "",
        "优先补齐 `missing`，其次补齐仅依赖 `global_default` 的高频业务组合。文档写入后执行知识入库/重建，确保 `indexed_documents` 同步增长。",
        "",
        "| 品类 | 场景 | 当前覆盖 | 文档数 | 已向量化文档 |",
        "|---|---|---|---:|---:|",
    ]
    for item in report["coverage"]:
        if item["level"] != "direct":
            lines.append(
                f"| {item['category']} | {item['scene']} | {item['level']} | {item['documents']} | {item['indexed_documents']} |"
            )
    if report["unindexed_documents"]:
        lines.extend(
            [
                "",
                "## 未向量化文档",
                "",
                "这些文档已启用但没有可检索的知识块。应先执行增量入库或重建，避免把知识缺口误判为内容缺失。",
                "",
                "| ID | 标题 | 品类 | 场景 |",
                "|---:|---|---|---|",
            ]
        )
        for item in report["unindexed_documents"]:
            lines.append(f"| {item['id']} | {item['title']} | {item['category']} | {item['scene']} |")
    return "\n".join(lines) + "\n"


def fetch_records(dsn: str) -> list[dict[str, Any]]:
    import psycopg  # type: ignore

    sql = """
        SELECT
            COALESCE(NULLIF(TRIM(d.product_category), ''), 'general') AS product_category,
            COALESCE(NULLIF(TRIM(d.scene), ''), 'general') AS scene,
            COUNT(DISTINCT d.id) AS documents,
            COUNT(DISTINCT d.id) FILTER (WHERE c.id IS NOT NULL AND c.embedding IS NOT NULL) AS indexed_documents,
            COUNT(c.id) AS chunks
        FROM knowledge_document d
        LEFT JOIN knowledge_chunk c ON c.document_id = d.id
        WHERE d.status = 1
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [
                {
                    "category": normalized(row[0]),
                    "scene": normalized(row[1]),
                    "documents": int(row[2]),
                    "indexed_documents": int(row[3]),
                    "chunks": int(row[4]),
                }
                for row in cur.fetchall()
            ]


def fetch_unindexed_documents(dsn: str) -> list[dict[str, Any]]:
    import psycopg  # type: ignore

    sql = """
        SELECT d.id, d.title,
               COALESCE(NULLIF(TRIM(d.product_category), ''), 'general') AS product_category,
               COALESCE(NULLIF(TRIM(d.scene), ''), 'general') AS scene
        FROM knowledge_document d
        LEFT JOIN knowledge_chunk c ON c.document_id = d.id
        WHERE d.status = 1
        GROUP BY d.id, d.title, d.product_category, d.scene
        HAVING COUNT(c.id) = 0
        ORDER BY d.id
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [
                {
                    "id": int(row[0]),
                    "title": normalized(row[1]),
                    "category": normalized(row[2]),
                    "scene": canonical_scene(row[3]),
                }
                for row in cur.fetchall()
            ]


def build_report(
    records: list[dict[str, Any]], categories: list[str], scenes: list[str], unindexed_documents: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    scopes: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"documents": 0, "indexed_documents": 0, "chunks": 0})
    discovered_categories: set[str] = set()
    for record in records:
        category = "general" if is_general(record["category"]) else normalized(record["category"])
        scene = canonical_scene(record["scene"])
        discovered_categories.add(category)
        target = scopes[(category, scene)]
        for key in ("documents", "indexed_documents", "chunks"):
            target[key] += int(record[key])

    audit_categories = categories or sorted(category for category in discovered_categories if category != "general")
    coverage: list[dict[str, Any]] = []
    levels: dict[str, int] = defaultdict(int)
    for category in audit_categories:
        for scene in scenes:
            level, stats = coverage_level(scopes, category, scene)
            levels[level] += 1
            coverage.append({"category": category, "scene": scene, "level": level, **stats})
    summary = {
        "active_documents": sum(item["documents"] for item in records),
        "indexed_documents": sum(item["indexed_documents"] for item in records),
        "chunks": sum(item["chunks"] for item in records),
        "combination_count": len(coverage),
        "levels": dict(levels),
    }
    return {
        "summary": summary,
        "coverage": coverage,
        "source_scopes": records,
        "unindexed_documents": unindexed_documents or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit PostgreSQL RAG knowledge coverage")
    parser.add_argument("--dsn", default="", help="PostgreSQL DSN; defaults to PGVECTOR_DSN/local config")
    parser.add_argument("--categories", default="", help="Comma-separated categories; defaults to categories found in knowledge_document")
    parser.add_argument("--scenes", default=",".join(DEFAULT_SCENES), help="Comma-separated after-sales scenes")
    parser.add_argument("--markdown-output", help="Optional Markdown report path")
    parser.add_argument("--json-output", help="Optional JSON report path")
    args = parser.parse_args()

    local_values = load_local_values()
    dsn = args.dsn or os.getenv("PGVECTOR_DSN") or local_values.get("PGVECTOR_DSN", "")
    if not dsn:
        parser.error("PGVECTOR_DSN is required")
    categories = [item.strip() for item in args.categories.split(",") if item.strip()]
    scenes = [item.strip() for item in args.scenes.split(",") if item.strip()]
    report = build_report(fetch_records(dsn), categories, scenes, fetch_unindexed_documents(dsn))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.markdown_output:
        output = Path(args.markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(report), encoding="utf-8")
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
