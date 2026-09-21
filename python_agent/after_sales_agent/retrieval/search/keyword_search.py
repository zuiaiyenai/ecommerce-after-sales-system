"""Chinese lexical (FTS) search strategy.

Migrated from ILIKE/pg_trgm string matching to Jieba-tokenised + PostgreSQL
tsvector GIN full-text search.  pg_trgm is kept as an optional typo
补召回 branch that only runs when FTS returns fewer than 5 hits.

Database schema requirements (see migration 20260819_add_lexical_fts_columns.sql):
    lexical_text   TEXT  NOT NULL DEFAULT ''
    search_vector  tsvector NOT NULL DEFAULT ''::tsvector
    GIN index:     idx_kc_search_vector_fts ON knowledge_chunk
                    USING GIN (search_vector)
"""
from __future__ import annotations

from typing import Any

from after_sales_agent.retrieval.retrieval_result import annotate_hits_with_filter_contract

# When FTS returns fewer than this many hits, fall back to pg_trgm for typo
# recovery.  Set to 0 to disable the pg_trgm branch entirely.
_TRGM_FALLBACK_THRESHOLD = 5
# Similarity threshold for pg_trgm typo补召回 (relaxed from the original 0.3)
_TRGM_SIMILARITY_THRESHOLD = 0.35
# Maximum rows to pull from pg_trgm supplemental branch
_TRGM_LIMIT = 20

# Colloquial → formal synonym expansion map for Chinese query matching
# Maps user-facing colloquial terms to formal policy vocabulary in the knowledge base
_COLLOQUIAL_SYNONYMS: dict[str, list[str]] = {
    # 破损/裂纹类
    "裂开": ["裂纹", "碎裂", "断裂", "破损", "裂缝", "开裂", "破裂"],
    "裂开了": ["裂纹", "碎裂", "断裂", "破损", "裂缝", "开裂", "破裂"],
    "破损": ["破损", "裂纹", "碎裂", "断裂", "裂缝"],
    "破裂": ["破裂", "裂纹", "碎裂", "破损"],
    # 拆箱/签收类
    "拆箱": ["签收", "开箱", "检查", "收到"],
    "刚拆箱": ["签收", "开箱"],
    "收到": ["签收", "收到", "收货"],
    # 手机/屏幕类
    "屏幕": ["屏幕", "显示屏", "显示"],
    "裂纹": ["裂纹", "裂缝", "碎裂", "破裂", "开裂"],
    # 充电类
    "充不进": ["充电", "充不进", "充不上", "无法充电", "充不上电"],
    "充不上": ["充电", "充不进", "充不上"],
    # 退货类
    "七天": ["七天", "7天", "天无", "理由"],
    "无理由": ["无理由", "7天", "七天"],
    # 食品类
    "胀袋": ["胀袋", "膨胀", "胀气", "漏气", "密封破损"],
    "异味": ["异味", "变质", "酸败", "异常气味"],
    # 鞋靴类
    "开胶": ["开胶", "脱胶", "断底", "脱线"],
    # 少发/错发类
    "少发": ["少发", "漏发", "缺件"],
    "漏发": ["少发", "漏发", "缺件"],
    "配件": ["配件", "组件", "零件", "赠品"],
    "发错": ["错发", "发错"],
    "错发": ["错发", "发错"],
    # 通用口语化
    "坏了": ["破损", "故障", "异常", "损坏", "质量问题"],
    "不好用": ["故障", "异常", "质量问题"],
    "不工作": ["故障", "异常", "质量问题"],
}

# Noise tokens to filter out (too common to be useful for matching)
_NOISE_TOKENS: set[str] = {
    "就", "了", "的", "吗", "呢", "怎么", "什么", "为什么", "怎么办",
    "如何", "需要", "可以", "能", "啊", "哦", "吧",
    "一个", "一下", "一些", "没有", "还是", "或者",
}


def _expand_query_tokens(query: str) -> list[str]:
    """Expand colloquial query into formal FTS tokens with synonym support."""
    import jieba
    import re

    raw_tokens = [
        w.lower() for w, _, _ in jieba.tokenize(query, mode="search")
        if len(w) >= 2 and re.fullmatch(r"(?:[一-鿿]+|[a-zA-Z0-9_]+)", w)
    ]

    expanded: set[str] = set()
    for t in raw_tokens:
        if t in _NOISE_TOKENS:
            continue
        if t in _COLLOQUIAL_SYNONYMS:
            expanded.update(_COLLOQUIAL_SYNONYMS[t])
        else:
            expanded.add(t)

    return sorted(expanded)


def _build_fts_tsquery(tokens: list[str]) -> str:
    """Build a PostgreSQL tsquery string from expanded tokens using OR logic.

    Tokens are wrapped in single quotes so PostgreSQL's to_tsquery() parser
    treats them as lexeme literals (not column references).  The resulting
    string is passed via %s to psycopg, which safely transmits the quoted
    content as a text value — PostgreSQL re-parses the quotes into tsquery
    operators.
    """
    if not tokens:
        return ""
    return " | ".join(f"'{t}'" for t in tokens)


def lexical_fallback(
    *,
    psycopg_module: Any,
    config: Any,
    query: str,
    merchant_code: str | None,
    product_category: str | None,
    scene: str | None,
    intent: str | None,
    source_type: str | None,
    policy_version: str | None,
    as_of_time: Any | None = None,
    filter_plan: Any = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """FTS-based lexical fallback for retrieval."""
    from after_sales_agent.retrieval.knowledge_filters import build_hard_filter_sql
    from after_sales_agent.retrieval.alias_mapping import (
        scene_aliases,
        product_category_aliases,
    )

    plan = filter_plan or _build_filter_plan(
        merchant_code=merchant_code,
        product_category=product_category,
        scene=scene,
        intent=intent,
        source_type=source_type,
        policy_version=policy_version,
        as_of_time=as_of_time,
        config=config,
    )
    safe_limit = max(1, min(int(limit), 10))

    # Try to import psycopg.sql for safe SQL composition; fall back to f-string
    # with %% escaping when psycopg is mocked in tests (no `sql` submodule).
    try:
        from psycopg import sql as _sql
        _USE_SQL_COMPOSITION = True
    except ImportError:
        _USE_SQL_COMPOSITION = False

    filter_sql, filter_params = build_hard_filter_sql(plan)
    normalized_query = str(query or "").strip()

    if not normalized_query:
        return []

    # Expand colloquial tokens for better matching
    expanded_tokens = _expand_query_tokens(normalized_query)
    fts_tsquery = _build_fts_tsquery(expanded_tokens)

    if not fts_tsquery:
        return []

    # Escape literal % in tsquery so psycopg doesn't confuse it with %s params
    safe_tsquery = fts_tsquery.replace("%", "%%")

    # FTS 主查询：ts_rank_cd 排序，LIMIT 50 扩宽候选池
    # NOTE: Use to_tsquery('simple'::regconfig, %s) with explicit regconfig cast
    # to disambiguate the function overload; psycopg passes the tsquery as text
    # and PostgreSQL parses the per-token single quotes into tsquery operators.
    fts_sql_template = (
        "SELECT kc.id, kc.document_type, kd.source_code, kc.chunk_text, kc.metadata,"
        " kd.title, kc.product_categories, kc.scenes, kc.intents, kd.policy_version,"
        " kd.tags, kd.merchant_code, kc.heading_path, kc.page_number, kc.revision,"
        " kd.valid_from, kd.valid_to, kc.document_id,"
        " ts_rank_cd(kc.search_vector, to_tsquery('simple'::regconfig, %s)) AS score"
        " FROM knowledge_chunk kc"
        " JOIN knowledge_document kd ON kd.id = kc.document_id"
        " WHERE {filter_sql}"
        "  AND kc.search_vector @@ to_tsquery('simple'::regconfig, %s)"
        " ORDER BY score DESC, kc.id"
        " LIMIT 50"
    )
    if _USE_SQL_COMPOSITION:
        fts_sql = _sql.SQL(fts_sql_template).format(filter_sql=_sql.SQL(filter_sql))
    else:
        fts_sql = fts_sql_template.format(filter_sql=filter_sql)
    fts_params = [safe_tsquery] + list(filter_params) + [safe_tsquery]

    with psycopg_module.connect(config.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(fts_sql, fts_params)
            fts_rows = cur.fetchall()

    fts_ids = {row[0] for row in fts_rows}

    # pg_trgm 补召：仅当 FTS 命中不足 _TRGM_FALLBACK_THRESHOLD 时触发
    trgm_rows: list[tuple] = []
    if len(fts_rows) < _TRGM_FALLBACK_THRESHOLD:
        trgm_sql_template = (
            "SELECT kc.id, kc.document_type, kd.source_code, kc.chunk_text, kc.metadata,"
            " kd.title, kc.product_categories, kc.scenes, kc.intents, kd.policy_version,"
            " kd.tags, kd.merchant_code, kc.heading_path, kc.page_number, kc.revision,"
            " kd.valid_from, kd.valid_to, kc.document_id,"
            " similarity(kc.search_text, %s) AS trgm_score"
            " FROM knowledge_chunk kc"
            " JOIN knowledge_document kd ON kd.id = kc.document_id"
            " WHERE {filter_sql}"
            " AND kc.search_text %% %s"
            " AND similarity(kc.search_text, %s) >= %s"
            " ORDER BY trgm_score DESC, kc.id"
            " LIMIT %s"
        )
        if _USE_SQL_COMPOSITION:
            trgm_sql = _sql.SQL(trgm_sql_template).format(filter_sql=_sql.SQL(filter_sql))
        else:
            trgm_sql = trgm_sql_template.format(filter_sql=filter_sql)
        trgm_params = (
            [normalized_query] + list(filter_params)
            + [normalized_query, normalized_query, str(_TRGM_SIMILARITY_THRESHOLD), str(_TRGM_LIMIT)]
        )
        with psycopg_module.connect(config.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(trgm_sql, trgm_params)
                trgm_rows = cur.fetchall()

    # 合并结果，FTS 结果优先，trgm 结果去重后追加，统一应用 heading 提升
    all_rows = list(fts_rows)
    for row in trgm_rows:
        if row[0] not in fts_ids:
            all_rows.append(row)

    hits = [
        row_to_hit(row, rank=rank, channel="keyword", is_trgm=(rank > len(fts_rows)), normalized_query=normalized_query)
        for rank, row in enumerate(all_rows, start=1)
    ]
    return annotate_hits_with_filter_contract(hits, plan)


def row_to_hit(
    row: Any,
    *,
    rank: int = 1,
    channel: str = "keyword",
    is_trgm: bool = False,
    normalized_query: str = "",
) -> dict[str, Any]:
    """Convert a keyword search DB row to a hit dict.

    FTS rows have ts_rank_cd score at index 18.
    pg_trgm rows have similarity score at index 18 (negative when absent).
    """
    import json

    metadata = row[4]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    metadata = {
        **(metadata or {}),
        "title": row[5],
        "product_categories": row[6] or [],
        "scenes": row[7] or [],
        "intents": row[8] or [],
        "product_category": (row[6] or [None])[0],
        "scene": (row[7] or [None])[0],
        "intent": (row[8] or [None])[0],
        "policy_version": row[9],
        "tags": row[10] or [],
        "merchant_code": row[11],
        "source_type": row[1],
        "source_code": str(row[2]),
        "heading_path": row[12] or [],
        "page_number": row[13],
        "revision": row[14],
        "valid_from": _serialize_time(row[15]),
        "valid_to": _serialize_time(row[16]),
        "document_id": row[17],
    }
    citation = {
        "chunk_id": row[0],
        "document_id": row[17],
        "source_type": row[1],
        "source_code": str(row[2]),
        "title": row[5],
        "merchant_code": row[11],
        "heading_path": row[12] or [],
        "page_number": row[13],
        "revision": row[14],
        "policy_version": row[9],
        "valid_from": _serialize_time(row[15]),
        "valid_to": _serialize_time(row[16]),
    }
    raw_score = float(row[18] or 0)
    # heading_path boost: +0.6 if any heading token appears in query (post-hoc)
    heading_boost = _heading_path_boost(row[12], normalized_query=normalized_query)
    raw_score += heading_boost
    return {
        "id": row[0],
        "chunk_id": row[0],
        "source_type": row[1],
        "source_code": str(row[2]),
        "title": metadata.get("title") or row[1],
        "snippet": row[3],
        "score": round(raw_score, 4),
        "raw_score": raw_score,
        "rank": rank,
        "channel": channel,
        f"{channel}_rank": rank,
        f"{channel}_score": raw_score,
        "retrieval_channels": [channel],
        "citation": citation,
        "metadata": metadata,
    }


def _heading_path_boost(
    heading_path: list[str] | tuple,
    normalized_query: str,
) -> float:
    """Return 0.6 if any heading segment matches the query as ILIKE substring."""
    if not heading_path:
        return 0.0
    heading_text = " ".join(str(h) for h in heading_path if h)
    if not heading_text or not normalized_query:
        return 0.0
    return 0.6 if heading_text.lower().find(normalized_query.lower()) != -1 else 0.0


def _keyword_search(
    *,
    query: str,
    merchant_code: str | None,
    product_category: str | None,
    scene: str | None,
    intent: str | None,
    source_type: str | None,
    policy_version: str | None,
    as_of_time: Any | None = None,
    filter_plan: Any = None,
    limit: int = 10,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Keyword search entry point that dispatches to lexical fallback."""
    return lexical_fallback(
        psycopg_module=kwargs.get("psycopg_module"),
        config=kwargs.get("config"),
        query=query,
        merchant_code=merchant_code,
        product_category=product_category,
        scene=scene,
        intent=intent,
        source_type=source_type,
        policy_version=policy_version,
        as_of_time=as_of_time,
        filter_plan=filter_plan,
        limit=limit,
    )


def _build_filter_plan(
    *,
    merchant_code: str | None,
    product_category: str | None,
    scene: str | None,
    intent: str | None,
    source_type: str | None,
    policy_version: str | None,
    as_of_time: Any | None,
    config: Any,
) -> Any:
    from datetime import datetime
    from after_sales_agent.retrieval.knowledge_filters import build_filter_plans, FilterContext

    def _normalized_merchant_code(mc: str | None) -> str:
        normalized = str(mc or "").strip()
        return normalized or "GLOBAL"

    return build_filter_plans(
        FilterContext(
            merchant_code=_normalized_merchant_code(merchant_code),
            source_type=source_type,
            policy_version=policy_version,
            as_of_time=as_of_time or datetime.utcnow(),
            product_category=product_category,
            scene=scene,
            intent=intent,
        )
    )[0]


def _serialize_time(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)
