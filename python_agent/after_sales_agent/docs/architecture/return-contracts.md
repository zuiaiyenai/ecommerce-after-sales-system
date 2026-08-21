# 关键方法返回契约

> 生成时间: 2026-08-17

## 1. `PgVectorKnowledgeRetriever.retrieve()` 返回契约

**签名**:
```python
def retrieve(
    self,
    *,
    query: str,
    merchant_code: str | None = None,
    product_category: str | None = None,
    scene: str | None = None,
    intent: str | None = None,
    source_type: str | None = None,
    policy_version: str | None = None,
    as_of_time: datetime | None = None,
    top_k: int | None = None,
    retrieval_mode: str = "rerank",
    query_id: str | None = None,
) -> dict[str, Any]
```

**返回 dict 固定字段**:

| 字段 | 类型 | 存在条件 | 说明 |
|------|------|----------|------|
| `mode` | `str` | 始终 | 取值: `rerank`, `rrf`, `dense`, `keyword`, `lexical_fallback`, `skipped`, `multi_query_rerank` 等 |
| `query` | `str` | 始终 | 标准化后的查询文本 |
| `hits` | `list[dict]` | 始终 | 可能为空列表 |
| `trace` | `dict` | 始终 | 包含嵌套结构 |

**`trace` 嵌套字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `stage_latency_ms` | `dict[str, float]` | 各阶段耗时 (embedding/vector/keyword/rrf/reranker/multi_query/total) |
| `filter_level` | `str` | 过滤级别: `strict` / `category_relaxed` / `scene_relaxed` / ... |
| `reranker_succeeded` | `bool` | Reranker 是否成功 |
| `threshold` | `float` | 当前 source_type 的分数阈值 |
| `failure_reason` | `str\|None` | 失败原因 |
| `dense_candidate_count` | `int` | 向量搜索候选数 |
| `keyword_candidate_count` | `int` | 关键词搜索候选数 |
| `rrf_candidate_count` | `int` | RRF 融合候选数 |
| `rerank_candidate_count` | `int` | Reranker 输出候选数 |
| `retrieval_mode` | `str` | 实际使用的检索模式 |
| `fallback_reason` | `str\|None` | 降级原因 |
| `trusted_policy_eligible` | `bool` | 是否有可信政策命中 |
| `candidate_traces` | `list[dict]` | 多查询候选 trace (最多 3 条) |
| `fallback_level` | `str\|None` | 放宽过滤的级别 |
| `reranker_failure_reason` | `str\|None` | Reranker 失败原因 |

**每个 `hit` dict 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `str` | chunk_id |
| `chunk_id` | `str` | 同 id |
| `source_type` | `str` | 来源类型 (policy/refund/exchange/...) |
| `source_code` | `str` | 来源代码 |
| `title` | `str` | 标题 |
| `snippet` | `str` | 文本片段 |
| `score` | `float` | 最终分数 (round to 4 decimals) |
| `raw_score` | `float` | 原始分数 |
| `rank` | `int` | 最终排名 |
| `channel` | `str` | 来源通道 (`dense` / `keyword`) |
| `dense_rank` / `keyword_rank` | `int` | 各通道内排名 |
| `dense_score` / `keyword_score` | `float` | 各通道原始分 |
| `retrieval_channels` | `list[str]` | 参与融合的通道列表 |
| `citation` | `dict` | 引用信息 (chunk_id, document_id, source_type, title, merchant_code, heading_path, page_number, revision, policy_version, valid_from, valid_to) |
| `metadata` | `dict` | 完整 metadata (含 title, product_categories, scenes, intents, tags, 等) |
| `threshold` | `float` | 该 hit 来源类型的阈值 |
| `relaxation_level` | `str` | 放宽级别 |
| `trusted_policy_eligible` | `bool` | 是否可信政策 |

## 2. `chat_json()` 返回契约

**签名**:
```python
def chat_json(
    self,
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 600,
) -> dict[str, Any]
```

**返回**: `dict[str, Any]`，内容为 LLM 响应的 JSON 解析结果。

**处理逻辑**:
1. 调用 `chat()` 获取响应
2. 从 `response["choices"][0]["message"]["content"]` 或 `response["message"]["content"]` 提取 content
3. 如果 content 是 dict → 直接返回
4. 如果 content 是 str → `json.loads(content)` 返回
5. 解析失败 → 抛出 `LLMResponseParseError`

**注意**: 没有 Schema 校验，纯靠 LLM 输出符合预期格式。这是 Phase 2 需要改进的核心问题。

## 3. `OpenAICompatibleClient.chat()` 返回契约

**签名**:
```python
def chat(
    self,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]
```

**返回**: OpenAI 兼容格式的 response dict:
```python
{
    "id": str,
    "object": str,
    "created": int,
    "model": str,
    "choices": [
        {
            "index": int,
            "message": {
                "role": str,
                "content": str | None,
                "tool_calls": list[dict] | None,
            },
            "finish_reason": str,
        }
    ],
    "usage": dict,
}
```
