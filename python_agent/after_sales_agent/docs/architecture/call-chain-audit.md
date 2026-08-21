# 调用链审计

> 生成时间: 2026-08-17 | 审计范围: 全项目 Python 代码, 排除 `__pycache__`

## 1. `_retrieve_compatibility()` 调用链

**定义**: `retrieval/pgvector_retriever.py:1217`

**调用方**: 仅 `retrieve()` 方法 (line 196-197)

```python
if self.config.layered_retrieval_enabled is False:
    return self._retrieve_compatibility(...)
```

**生产状态**: `.env` 中 `RAG_LAYERED_RETRIEVAL_ENABLED=true`, 因此生产环境**不走此分支**。
该方法为历史 legacy 路径，仅在 `layered_retrieval_enabled=false` 时触发。

**结论**: 生产无调用，Phase 6 可安全删除（前提是确认无 staging/test 环境仍使用 false）。

---

## 2. `_finalize_ablation_result()` 调用链

**定义**: `retrieval/pgvector_retriever.py:1188`

**调用方**: 仅内部 4 处（均在 `pgvector_retriever.py` 中）:
- line 282: layered retrieve mode 无命中时
- line 412: multi-query retrieval 无命中时
- line 444: multi-query candidate 为空时
- line 945: relaxed retrieval 无命中时

**功能**: 与 `_finalize_result()` 功能重叠，额外传入 `dense_count`/`keyword_count`/`rrf_count` 到 trace。
实际是 `_finalize_result()` 的包装，trace 字段最终也会被合并到 `_finalize_result()` 的输出。

**结论**: 可 inline 到 `_finalize_result()`，Phase 6 删除。

---

## 3. Legacy tool-call fallback 退役结果

`legacy_tool_call_fallback_enabled`、`_legacy_decision()`、legacy Prompt、JSON 决策 Schema 和相关配置均已删除。

原生 Function Calling 失败时，工作流清理 pending tool call 后直接 fail-closed：有可信工单上下文则请求人工处理，否则返回安全失败提示，不执行模型提出的业务工具。

---

## 4. `chat_json()` 全量调用方

**定义**: `providers/llm_client.py:141`

**结论**: 8 个业务调用方均已迁移到 `generate_structured()`。当前生产 Provider 会本地校验 Schema，将脱敏后的错误原因和上次输出反馈给模型，最多修复重试 2 次；仍失败则抛错交由应用层安全降级。

---

## 5. `build_langgraph_entry_payload` 引用链

**定义**: `application/request_payload_adapter.py:58`
```python
build_langgraph_entry_payload = build_chat_entry_payload
```

**引用方**:
- `evaluation/offline_safety_evaluator.py:8` — import
- `evaluation/offline_safety_evaluator.py:82` — 实际调用

**结论**: 不是死代码。`evaluation/` 模块仍在使用。Phase 6 删除前需确认 evaluation 测试也迁移。

---

## 6. `_embed()` 调用链

**定义**: `retrieval/pgvector_retriever.py:1932` 附近（`embed_many` 方法）

**调用方**: 仅 `_get_query_embedding()` (line ~1910)

```python
def _get_query_embedding(self, text: str) -> tuple[list[float], bool]:
    ...
    embedding = self._embed(cache_key)  # 仅此一处
```

**结论**: `_embed()` 是多余的中间层，可 inline 到 `_get_query_embedding()`。Phase 1 处理。

---

## 7. `_finalize_result()` 调用方全量

**定义**: `retrieval/pgvector_retriever.py:1061`

**调用方**（共 18+ 处）:
- `retrieve()` 方法内部: lines 191, 231, 238, 252, 303, 350, 359, 364, 399, 628, 689, 847, 881, 911, 973
- `_retrieve_compatibility()`: lines 1245, 1276
- `_finalize_reranked_result()`: line ~1488
- `_finalize_ablation_result()`: lines 1208-1210

**返回契约**: `dict[str, Any]`，固定字段见 `return-contracts.md`。
