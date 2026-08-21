# 配置路径审计

> 生成时间: 2026-08-17 | 数据来源: `python_agent/.env`

## 1. 关键环境变量实际值

| 变量名 | .env 值 | 默认值 | 实际生效 |
|--------|---------|--------|----------|
| `RAG_LAYERED_RETRIEVAL_ENABLED` | `true` | `False` | **True** — 使用 layered retrieval |
| `LLM_NATIVE_FUNCTION_CALLING_ENABLED` | 未设置 | `True` | **True** — native 模式启用 |
| `PGVECTOR_DSN` | 已设置（脱敏） | `""` | **已配置** — PgVector 为主数据源 |
| `EMBEDDING_PROVIDER` | `dashscope` | `dashscope` | **DashScope** |
| `LLM_PROVIDER` | `remote` | `remote` | **DeepSeek (remote)** |
| `LLM_BASE_URL` | `https://api.deepseek.com` | — | DeepSeek API |
| `RERANK_PROVIDER` | `dashscope` | — | DashScope Reranker |
| `FORMAL_REVIEW_AUTO_APPROVE_ENABLED` | `true` | — | 正式审核自动通过 |

## 2. 环境差异

- **生产 vs 本地**: `.env` 为本地开发配置，生产环境的 `PGVECTOR_DSN`、API Key 等通过 K8s Secret 注入，值不同但结构相同
- **Fallback 链**: LLM 主链路 = DeepSeek → Ollama fallback；Embedding = DashScope (无 fallback)；Reranker = DashScope

## 3. 对重构的影响

1. **`_retrieve_compatibility()` 可标记为死代码**：`layered_retrieval_enabled=true` 意味着生产永远走新路径
2. **Legacy fallback 已退役**：严格模式全量测试和真实 native Function Calling 验证通过后，开关与第二套 JSON 决策协议均已删除
3. **`chat_json()` 迁移完成**：业务调用方已迁至 `generate_structured()`；结构错误使用带反馈的有限修复重试
4. **`build_langgraph_entry_payload` 不是死代码**：evaluation 模块仍在使用

## 4. 当前严格模式

Agent 只使用原生 Function Calling。协议错误不再切换第二套 JSON 决策，而是进入确定性 fail-closed/人工转接。`generate_structured()` 的错误反馈重试属于非工具结构化输出修复，不会绕过 ToolRegistry。
