# Tools

这里仅放可重复执行的审计、评测和压测入口，不参与生产服务启动。

| 文件 | 用途 | 外部依赖 |
| --- | --- | --- |
| `audit_knowledge_coverage.py` | 审计知识文档、分块和品类/场景覆盖 | 本地 PostgreSQL |
| `evaluate_rag_recall.py` | 运行 RAG Recall@5 基线 | pgvector + 真实 Embedding API |
| `evaluate_vision_baseline.py` | 运行图片 Precision/Recall/F1 基线 | 真实视觉 API |
| `evaluate_emotion_baseline.py` | 运行独立情绪/人工优先级挑战集 | 真实文本 API |
| `emotion_priority_holdout.json` | 50 条零 Prompt 原句重合的规则化挑战样本 | 无 |
| `load_test_agent.py` | HTTP Gateway/Agent 并发压测 | 已启动的本地服务 |
| `load_test_llm.py` | LLM 客户端并发测试 | 真实或本地模型 |
| `agent_chat_load_request.json` | 单场景、无订单聊天压测请求 | 测试用户 JWT |
| `agent_chat_load_scenarios.json` | 6 类售后场景轮询压测请求 | 测试用户 JWT |

从仓库根目录运行：

```powershell
python tools/audit_knowledge_coverage.py --help
python tools/evaluate_rag_recall.py
python tools/evaluate_vision_baseline.py
python tools/evaluate_emotion_baseline.py --real --concurrency 2 --max-requests 50
python tools/load_test_agent.py --help
python tools/load_test_llm.py --help
```

完整 Agent 压测会产生真实模型调用费用。脚本会分别统计 HTTP 成功、业务成功、工具失败和人工兜底；Java Gateway 返回的 HTTP 200 兜底或 `tool_trace[].ok=false` 都不会再被误算为完整 Agent 成功。`--body-file` 可传单个 JSON 对象或对象数组：

```powershell
python tools/load_test_agent.py `
  --endpoint /api/agent/chat `
  --body-file tools/agent_chat_load_scenarios.json `
  --token $env:LOAD_TEST_TOKEN `
  --requests 20 `
  --concurrency 2 `
  --timeout 95
```

压测结果与口径说明见 [压测与性能分析.md](../docs/压测与性能分析.md)。

## Phase 3 回归与受控测试入口

默认 Python 回归会通过 `pytest.ini` 排除 `real_llm`，不需要模型密钥：

```powershell
cd python_agent
python -m pytest tests -q
python -m pytest tests -m smoke -q
```

真实模型测试只允许在手动触发的受控 smoke 中执行：

```powershell
$env:LLM_API_KEY = '<protected secret>'
$env:LLM_BASE_URL = 'https://configured-provider/v1'
$env:LLM_MODEL = '<configured-model>'
python -m pytest tests -m real_llm -q
```

Java 的 MySQL、Kafka、Redis 集成测试使用 Testcontainers；Docker 不可用时由 JUnit 明确跳过，不连接本地业务数据库。CI 定义在 `.github/workflows/ci.yml`，夜间/手动 smoke 定义在 `.github/workflows/nightly-smoke.yml`。

真实 API 评测会产生调用费用，不应加入默认 CI。

如果 IDE 仍然显示 `after_sales_agent` 导入爆红，请把 `python_agent` 标记为 Sources Root；仓库根目录的 `pyrightconfig.json` 已经包含该搜索路径。
