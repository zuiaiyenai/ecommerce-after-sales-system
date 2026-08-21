# Python Agent

> 当前目录结构、依赖方向和唯一运行链路以 [代码结构.md](代码结构.md) 为准。Python Agent 通过 Java 内部工具访问业务数据，不直接写 MySQL 业务表。

## Remote LLM (default) and Ollama fallback

Copy `.env.example` values into the environment used to start this process.
Normal production/development startup uses a real OpenAI-compatible endpoint:

```text
LLM_PROVIDER=remote
LLM_BASE_URL=https://your-provider.example/compatible-mode
LLM_API_KEY=your-api-key
LLM_MODEL=your-model
LLM_FALLBACK_ENABLED=true
LLM_FALLBACK_PROVIDER=ollama
LLM_NATIVE_FUNCTION_CALLING_ENABLED=true
```

To run Ollama directly, set `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL`, and
`OLLAMA_MODEL`. Remote authentication/validation errors are deliberately not
eligible for fallback. Timeouts, 429, transient 5xx, network failures and an
open circuit are eligible. Remote and Ollama calls use separate concurrency
limits, so an upstream outage cannot create an unlimited Ollama fallback storm.

The Agent uses provider-native Function Calling. Invalid or unavailable native tool calls fail
closed instead of switching to a second decision protocol. Structured non-tool outputs still use
bounded, feedback-driven schema repair inside `generate_structured()`.

The shared clients are created once with the Agent services and closed at
shutdown. Pool sizes, queue wait, connect/read/write/pool/overall timeouts,
retry backoff and circuit breaker thresholds are all listed in `.env.example`.

Tests and real-API smoke test:

```powershell
pip install -r python_agent\requirements-test.txt
$env:PYTHONPATH='python_agent'; python -m pytest python_agent\tests -m "not real_llm"
$env:PYTHONPATH='python_agent'; python -m pytest python_agent\tests\test_real_llm.py -m real_llm
```

The real test is skipped unless `LLM_API_KEY` is present. Protocol mocks live
only under `python_agent/tests`; production code never imports them. Therefore
switching to a real model is configuration-only and never requires deleting a
mock.

## Consultation and streaming chat

Both `POST /api/chat` and `POST /api/chat/stream` use the same Agentic RAG
consultation service. It performs trusted policy retrieval, one bounded
multi-query rewrite when needed, and then either persists a grounded answer
through Java or asks Java to hand the session to a human.

The streaming endpoint emits `start`, `token`, `finish`, `error`, and `done`.
The answer is generated and persisted before the token event, so SSE cannot
bypass RAG trust checks or Java persistence.

DeepSeek V4 enables thinking mode by default. This application sets
`LLM_THINKING_ENABLED=false` because user-visible streaming and the current
tool protocol require ordinary content chunks. Enable it only after preserving
`reasoning_content` across every tool-call turn.

The cost-bounded real concurrency test requires an explicit acknowledgement:

```powershell
python tools\load_test_llm.py --real --levels 1,3,5,10,20 --max-requests 40 --max-tokens 24
```

## Runtime limits

The built-in server is bounded so slow LLM calls cannot create unbounded request
threads. Configure these values before starting the service when load testing or
deploying it behind the Spring Boot gateway:

```text
AGENT_HOST=127.0.0.1
AGENT_PORT=8000
AGENT_MAX_CONCURRENT_REQUESTS=2
PGVECTOR_IVFFLAT_PROBES=10
EMBEDDING_CACHE_TTL_SECONDS=300
EMBEDDING_CACHE_MAX_ENTRIES=256
OLLAMA_KEEP_ALIVE=30m
AGENT_PREWARM_MODELS=true
AGENT_PREWARM_VISION=false
```

When all execution slots are busy, the service returns HTTP `429` with
`Retry-After: 1`; callers should retry with backoff instead of opening more
connections.

`PGVECTOR_IVFFLAT_PROBES` controls vector recall versus latency. Start at `10`,
then tune it against the retrieval test set rather than changing the index type
blindly.

Query embeddings are cached for 5 minutes by default. The cache stores only
query vectors, not retrieved documents, so policy/document updates remain live.

## LLM Multi-Query Agentic RAG retrieval

After the first successful structured `retrieve_knowledge` call, the Agentic
RAG consultation service may make one structured LLM call to evaluate whether the returned
knowledge covers the current task. If coverage is insufficient, the LLM may
produce 1-3 complementary query candidates. It cannot select the internal
multi-query tool or change merchant, category, scene, intent, source type,
policy version, business time, or `top_k` filters.

The internal batch retriever runs candidates in parallel, fuses their rankings
with cross-query RRF, reranks each validated candidate independently, and keeps
each document's best relevance score. `RAG_MULTI_QUERY_MAX_CANDIDATES=3` is
clamped to the range 1-3. Duplicate or malformed queries are rejected.

The model then evaluates the multi-query result once more. A result is
sufficient only when it covers every explicit issue aspect and the applicable
conditions, exclusions, evidence requirements, and Agent authority boundary
needed by the question. Ticket decisions additionally require a trusted
policy result. `RAG_SUFFICIENCY_MIN_CONFIDENCE=0.70` is the default acceptance
floor. The structured assessment separates `knowledge_missing_aspects` from
`case_fact_gaps` and `out_of_scope_aspects`. Only missing knowledge can trigger
another retrieval or a knowledge-insufficiency handoff; missing order/user
facts are handled by tools or follow-up questions, while technical or medical
diagnosis remains outside the RAG sufficiency gate. If the second evaluation
still has a real knowledge gap or fails, the workflow does not launch a third
retrieval round and instead routes to human review. This bounds the flow to one
rewrite batch and two semantic evaluations.

Infrastructure failures such as embedding errors or unavailable pgvector do
not invoke query rewriting. If the rewrite model fails or returns an invalid
schema, the workflow closes the rewrite branch and continues through the
existing safe path; it does not generate a fixed fallback query.

## 本地 Ollama 模型配置

默认模型职责如下，可通过环境变量替换：

```text
QWEN_MODEL=qwen2.5:7b
EMOTION_MODEL=qwen2.5:1.5b
# 视觉模型当前由 VisionReviewService 固定为 qwen2.5vl:7b
QWEN_BASE_URL=http://127.0.0.1:11434
```

服务间认证只需在项目根目录创建一次未提交的 `agent.local.properties`：

```properties
app.agent.internal-token=replace-with-a-long-random-local-secret
```

Spring Boot 与 Python Agent 会自动读取它；部署环境仍可用
`AGENT_INTERNAL_TOKEN` 覆盖。

在当前本机基线中，`qwen2.5:7b` 的吞吐量在 2 并发后已基本饱和；建议
先保持 `AGENT_MAX_CONCURRENT_REQUESTS=2`，只有在重新压测确认 GPU 余量后再提高。

Agent 启动后会异步预热文本和情绪模型，并用 `OLLAMA_KEEP_ALIVE` 保持热态。
视觉模型默认不预热；若 GPU 显存充足且确认不会挤出文本模型，可设置
`AGENT_PREWARM_VISION=true`。

这个目录是当前 Spring Boot 项目内置的售后 AI Agent。

## 目录作用

- `web_demo.py`
  - 已移动到 `demos/web_demo.py`，仅用于本地可视化测试
- `after_sales_agent/interface/http_server.py`
  - Spring Boot 调用的 Python Agent HTTP 入口，默认监听 `127.0.0.1:8000`
- `after_sales_agent/`
  - 售后 Agent 核心包
  - `domain/`
    - 零框架依赖的领域模型与枚举
  - `agent/`
    - 唯一 `AfterSalesAgent`、确定性 Router、运行上下文和复杂 Workflow
  - `skills/`
    - 仅保存 `SKILL.md`、引用资料和展示元数据
  - `tools/`
    - 查询、审核和提交等受控确定性动作的公共入口
  - `application/`
    - 对话、情感分析和知识入库用例编排
  - `retrieval/`
    - pgvector/pg_trgm 检索、RRF 融合与排序
  - `providers/`
    - LLM、Vision、Embedding 与 Reranker 适配
  - `integrations/`
    - Java 内部 Agent API 网关
  - `infrastructure/`
    - Trace、指标、checkpoint、仓储与可靠性机制
  - `interface/`
    - HTTP 与 Kafka 入口
  - `utils/`
    - 图片审核结果转换、序列化等共享工具
- `.env`
  - Python Agent 的本地模型、RAG、pgvector 和工具调用配置
- `sample_images/`
  - 图片审核联调样例图，仅用于 `/api/review-images` 售后凭证审核，不作为商品图片入库
- `demos/`
  - 本地测试页面，不参与 Spring Boot 主调用链路

复杂 Skill 的执行代码位于 `after_sales_agent/agent/workflows/`；`after_sales_agent/skills/` 不放 Python 业务实现。

## 启动方式

在当前仓库根目录执行：

```powershell
pip install -r python_agent\requirements.txt
powershell -ExecutionPolicy Bypass -File python_agent\run_agent.ps1
```

也可以进入 `python_agent` 目录后直接启动 API 服务：

```powershell
python -m after_sales_agent.interface.http_server
```

如果只想打开旧的可视化测试页，可以执行：

```powershell
python demos\web_demo.py
```

## 联调关系

- 小程序/H5 只请求 Spring Boot：`/api/agent/*`
- Spring Boot 再代理到 Python Agent：`http://127.0.0.1:8000/api`

## 数据存储说明

Python Agent 会优先加载 `python_agent/.env`。RAG/pgvector、LLM、视觉模型和工具调用配置都应放在这个文件中。

- PostgreSQL/pgvector 是 Python Agent 的知识检索来源，本机连接应指向 `after_sales_rag`。
- MySQL 是 Java 管理的业务事实来源；Python Agent 不配置 MySQL 业务仓储，也不直接写业务表。
- 会话、消息、工单与审核结果统一通过 `integrations/java_tool_client.py` 交给 Java 校验和持久化。
