# Python Agent 代码结构

## 目录

```text
python_agent/
├─ after_sales_agent/
│  ├─ api/                       # HTTP、JSON、SSE 传输层
│  │  └─ http_server.py
│  ├─ application/               # 用例编排，不依赖具体 Web Request/Response
│  │  ├─ chat/                   # 普通咨询 Agentic RAG
│  │  ├─ formal_review/          # Kafka 正式审核 LangGraph Multi-Agent
│  │  ├─ knowledge_admin_service.py # 知识库管理与诊断接口用例
│  │  ├─ tool_registry.py        # Agent 工具注册与执行门面
│  │  └─ streaming_chat_service.py # Agentic RAG 结果的 SSE 事件适配
│  ├─ agents/                    # 聚焦的决策组件
│  │  ├─ emotion_service.py
│  │  └─ llm_emotion_classifier.py
│  ├─ providers/                 # 外部模型 Provider 适配与可靠性装饰
│  │  ├─ llm_client.py           # 统一 LLMClient
│  │  ├─ model_prewarm_service.py # 本地 Ollama 模型预热
│  │  ├─ resilient_llm_runtime.py # 重试、熔断、Semaphore、Provider 切换
│  │  └─ vision_review_service.py # 多模态凭证审核
│  ├─ retrieval/                 # 知识检索
│  │  └─ pgvector_retriever.py
│  ├─ integrations/              # 其他业务系统适配器
│  │  └─ java_tool_client.py
│  ├─ config/                    # 环境和运行配置
│  ├─ infra/                     # Trace 等横切基础设施
│  ├─ utils/                     # 无状态序列化辅助函数
│  └─ domain_models.py           # 领域 DTO 与枚举
└─ tests/
```

## 依赖方向

```text
api → application → agents/providers/retrieval/integrations
                  → domain_models
providers/retrieval/integrations → config/infra/domain_models
```

约束：

1. `api` 只处理 HTTP/SSE，不承载售后决策。
2. `application` 不依赖 Web Request/Response。
3. 业务编排不得直接使用 httpx/urllib，必须经过 Provider 或 Integration。
4. `providers` 不拼接 SSE 文本，只返回普通结果或事件迭代器。
5. Java/MySQL 业务真相只能通过 `integrations/java_tool_client.py` 访问；Python 不直接写业务库。
6. 新模型通过 `providers` 接入，不用模型品牌命名业务类。
7. 新检索实现放入 `retrieval`，并保持统一结构化结果。

## 运行入口

```text
HTTP /api/chat        → application/chat/AgenticRagChatService
HTTP /api/chat/stream → application/chat/AgenticRagChatService → SSE events
Kafka review.request  → application/formal_review/FormalReviewGraph
```

普通咨询只允许进行可信政策检索、生成政策回答或调用 Java 转人工。
正式审核由一个 LangGraph 编排 Policy Agent、Evidence Agent、Review
Supervisor 和确定性 Gate。Python 只提交审核建议、补凭证请求或人工审核
建议，Java/MySQL 负责最终校验和业务状态。

正式审核不再使用 Runtime Router、Shadow 双跑或两套审核器结果对比。

## 常用命令

```powershell
cd python_agent
python -m pytest tests -q
python -m compileall -q after_sales_agent
python -m after_sales_agent.api.http_server
```
