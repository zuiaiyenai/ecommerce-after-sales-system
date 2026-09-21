# 项目架构与第一阶段审计

> 审计日期：2026-09-21
>
> 审计基线：`main` / `eac3754`
>
> 证据范围：当前源码、配置、SQL、自动化测试与本机端口；历史 README 和旧设计文档只作线索。

> 运行状态更新（2026-09-21 16:30）：MySQL、Redis、Java、Python Agent 和 Vue 已在 Windows 运行；PostgreSQL/pgvector 与 Kafka 已在专用 Ubuntu VMware VM 运行。Java Actuator 为 `UP`，pgvector 真实集成测试 3/3 通过，Java Outbox → Kafka → Python → Java → MySQL 业务链路已验证。完整 Embedding、RAG 和 LLM 仍受模型服务未配置限制。后续证据见 `DATABASE_DESIGN.md` 与 `KAFKA_DESIGN.md`。

## 1. 审计结论

这是一个多进程的 Java 业务系统与 Python AI 应用，不是微服务集合。

- Java Spring Boot 保存业务事实、执行权限校验、事务写入和最终状态变更。
- Python Agent 负责 LLM、RAG、工具编排、图片审核建议和 Kafka 售后审核。
- MySQL 保存用户、商品、订单、工单、会话、消息和 Outbox。
- PostgreSQL + pgvector 保存知识文档、草稿、1024 维向量和 LangGraph checkpoint。
- Redis 用于限流、缓存和 Kafka Consumer 幂等状态。
- Kafka 承载售后审核请求，Java 通过 Transactional Outbox 发布，Python 消费。
- 管理/客服端是 Vue 3 + Vite；用户端是 Vue 3 + uni-app。

源码覆盖完整，但当前运行环境没有启动任何目标服务。本机未发现 Docker CLI，WSL 也未安装；本地 LLM、Embedding、Vision 密钥均未配置。因此 Java 核心可编译和通过单元测试，完整 AI/RAG 与 Kafka 链路当前不可用。

## 2. 真实目录结构

| 路径 | 责任 | 现场事实 |
| --- | --- | --- |
| `src/main/java/com/ecommerce/aftersales` | Java 业务内核、REST、WebSocket、SSE、鉴权、MyBatis、Outbox | Java 21 / Spring Boot 3.3.6，16 个 Controller |
| `src/main/resources` | Spring 配置、Mapper XML、内置知识数据 | 主配置导入可选 `application-local.yml` 和项目根 `agent.local.properties` |
| `frontend/staff-auth-test-ui` | 管理员与客服工作台 | Vue 3 + Vite，真实 API adapter 与显式 mock 模式并存 |
| `frontend/uniapp` | 用户 H5 / 微信小程序 | 登录、订单、售后、会话、AI 客服、评价等 15 个页面 |
| `python_agent/after_sales_agent` | Agent、Workflow、RAG、LLM、工具、HTTP 与 Kafka 入口 | Python HTTP 入口是 `interface/http_server.py`；Kafka 入口是 `interface/kafka_adapter.py` |
| `sql/schema.sql` | MySQL 业务模型 | 用户、客服、订单、工单、附件、Outbox、会话、消息、评价、通知等 |
| `sql/pgvector_schema.sql` | PostgreSQL RAG 模型 | `vector`、`pg_trgm`、1024 维向量、GIN、FTS、IVFFlat cosine |
| `sql/migrations` | 增量 SQL | 18 个迁移脚本；仓库没有 Flyway/Liquibase 自动执行器 |
| `compose.yml` | 完整容器编排 | MySQL、PostgreSQL、Redis、Kafka、Agent、Consumer、Java、Prometheus、Grafana |
| `observability` | Prometheus 告警和 Grafana dashboard | 配置已存在，当前未运行 |
| `.github/workflows` | CI 与定时 smoke | Java、Python、前端流水线；真实 LLM/RAG 依赖受保护变量 |
| `tools` | 评测、压测、知识覆盖工具 | 包含 RAG、视觉、情绪、安全与 Agent 负载工具 |

代码知识图谱当前索引 466 个文件、8,506 个节点、32,299 条关系：199 个 Java 文件、138 个 Python 文件、49 个 Vue 文件、224 个路由节点。

## 3. 真实架构

```mermaid
flowchart LR
    U[用户端 uni-app] -->|REST / WebSocket| J[Java Spring Boot :8080 /api]
    S[客服/管理端 Vue :5173] -->|REST / WebSocket| J
    J -->|业务事务| M[(MySQL :3307)]
    J -->|限流/缓存| R[(Redis :6380 目标)]
    J -->|知识管理 JDBC| P[(PostgreSQL 16 + pgvector :5432)]
    J -->|HTTP / SSE| A[Python Agent :8000]
    J -->|Transactional Outbox| K[Kafka :9092]
    K -->|after_sales.review.request| C[Python Review Consumer]
    A -->|Embedding / Vector Search| P
    C -->|LangGraph checkpoint / RAG| P
    A -->|Java Internal API + shared token| J
    C -->|Java Internal API + shared token| J
    A -->|LLM / Embedding / Vision| X[模型服务]
    J --> PR[Prometheus :9090]
    A --> PR
    C --> PR
    PR --> G[Grafana :3000]
```

### 边界原则

1. Python 不直接修改 MySQL 业务结果。
2. Python 通过 `/api/internal/agent-tools/**` 请求 Java 执行订单查询、工单审核、消息落库和转人工。
3. Java 内部工具接口使用共享 Token；用户与客服接口使用 JWT。
4. MySQL 是业务真相源，PostgreSQL 是知识与 Agent 运行态存储。

## 4. 核心调用链

### 4.1 登录与 RBAC

```text
Vue login
→ POST /api/merchant-cs/auth/login 或 /api/admin/auth/login
→ MerchantCsServiceImpl / AdminConsoleServiceImpl
→ PasswordEncoder 校验
→ JwtTokenUtil 签发 JWT
→ JwtAuthenticationFilter
→ SecurityConfig 的角色/路径规则
```

关键代码：

- `config/SecurityConfig.java:23`
- `config/JwtAuthenticationFilter.java:21`
- `service/impl/MerchantCsServiceImpl.java`
- `service/impl/AdminConsoleServiceImpl.java`

### 4.2 用户创建售后与异步审核

```text
POST /api/aftersales
→ AfterSalesController.create
→ Redis 提交限流
→ AfterSalesServiceImpl.create 的 MySQL 事务
→ 工单 + 日志 + 附件 + after_sales_event_outbox
→ AfterSalesReviewEventServiceImpl 定时 claim/publish
→ Kafka after_sales.review.request
→ AfterSalesReviewKafkaConsumer
→ FormalReviewWorkflow / RAG / Vision / LLM
→ Java InternalAgentToolsController
→ Java 再校验并写 MySQL
→ WebSocket 通知用户与客服
```

关键代码：

- `controller/AfterSalesController.java:66`
- `service/impl/AfterSalesServiceImpl.java`
- `service/impl/AfterSalesReviewEventServiceImpl.java:37`
- `python_agent/after_sales_agent/interface/kafka_adapter.py:419`
- `controller/InternalAgentToolsController.java:62`

### 4.3 AI 客服聊天

```text
用户问题
→ POST /api/agent/chat 或 /api/agent/chat/stream
→ AgentGatewayController（JWT + Redis 限流）
→ AgentGatewayServiceImpl（保存用户消息、补全可信业务上下文）
→ Python POST /api/chat 或 SSE
→ AfterSalesAgent
→ ConsultationWorkflow
→ Java 工具查询订单/工单/客户/商品
→ PgVectorKnowledgeRetriever
→ Embedding + vector/FTS/pg_trgm + RRF + 可选 reranker
→ LLM 生成回答或转人工
→ append_chat_message Java 工具落库
→ WebSocket / HTTP 响应回前端
```

关键代码：

- `controller/AgentGatewayController.java:25`
- `service/impl/AgentGatewayServiceImpl.java`
- `python_agent/after_sales_agent/interface/http_server.py:233`
- `python_agent/after_sales_agent/agent/agent.py:39`
- `python_agent/after_sales_agent/agent/workflows/consultation.py:31`
- `python_agent/after_sales_agent/retrieval/pgvector_retriever.py:146`

### 4.4 知识文档入库

```text
管理端文件/文本上传
→ /api/admin/knowledge/file-import 或 text-import
→ KnowledgeService 创建 knowledge_document 与草稿状态
→ KnowledgeIngestionAsyncService
→ Python /api/parse-document
→ 分块与元数据分类
→ knowledge_chunk_draft
→ 人工确认/发布
→ Python /api/embeddings
→ KnowledgePublishService 校验每条 1024 维
→ knowledge_chunk + published_revision
→ IVFFlat / FTS / pg_trgm 检索
```

关键代码：

- `controller/KnowledgeManagementController.java:36`
- `service/KnowledgeIngestionAsyncService.java:33`
- `service/KnowledgePublishService.java:26`
- `python_agent/after_sales_agent/infrastructure/embedding_service.py:12`
- `sql/pgvector_schema.sql:4`

## 5. 功能矩阵

状态含义：`IMPLEMENTED` 为源码与自动化契约存在；`PARTIAL` 为能力或入口不完整；`BROKEN` 为当前已知失败；`MOCK` 为仅模拟；`NOT_STARTED` 为无实现；`NOT_VERIFIED` 为尚无当前运行证据。

| 模块 | 前端 | Java | Python | DB/中间件 | 当前状态 | 是否真正可用 |
| --- | --- | --- | --- | --- | --- | --- |
| 用户登录 | uni-app 登录页 | 用户 JWT 登录/注册/重置 | 无 | MySQL | IMPLEMENTED | NOT_VERIFIED |
| 客服/管理员登录 | Vue 登录页 | JWT、角色与账号状态 | 无 | MySQL | IMPLEMENTED | NOT_VERIFIED |
| RBAC | 路由守卫 | Spring Security + JWT 角色规则 | 内部 Token | MySQL | IMPLEMENTED | NOT_VERIFIED |
| 客服工作台 | Dashboard | 概览、待办、绩效 | 无 | MySQL | IMPLEMENTED | NOT_VERIFIED |
| 客户 | 会话/订单内客户信息 | 无独立客户 CRUD | 工具上下文读取 | MySQL | PARTIAL | NOT_VERIFIED |
| 商品 | 列表、详情、编辑 | 商品查询与客服管理接口 | 商品查询工具 | MySQL | IMPLEMENTED | NOT_VERIFIED |
| 订单 | 用户与客服两套页面 | 查询、创建、发货、详情 | 订单查询工具 | MySQL | IMPLEMENTED | NOT_VERIFIED |
| 会话 | 列表、详情、用户咨询 | 会话生命周期 | 对话编排 | MySQL + WebSocket | IMPLEMENTED | NOT_VERIFIED |
| 消息 | 历史与实时展示 | 落库、广播、顺序查询 | append message 工具 | MySQL + WebSocket | IMPLEMENTED | NOT_VERIFIED |
| 工单/售后 | 用户申请、客服审核 | 事务、补证、状态机 | 正式审核 Workflow | MySQL + Kafka | IMPLEMENTED | NOT_VERIFIED |
| AI 客服 | 用户咨询页、客服建议 | HTTP/SSE 网关 | Agent + LLM + 工具 | MySQL/Redis/PostgreSQL | BROKEN | 否：Agent 停止且无 LLM Key |
| RAG | 管理端测试检索 | 检索代理接口 | 混合召回/RRF/rerank | pgvector/FTS/pg_trgm | BROKEN | 否：PostgreSQL 停止且测试失败 |
| 知识库 | 管理端列表、草稿、发布 | 完整管理 API | 解析、Embedding、检索 | PostgreSQL | IMPLEMENTED | NOT_VERIFIED |
| 文档上传 | 文件导入 UI | multipart 校验与异步任务 | PDF/文本解析 | PostgreSQL + 文件系统 | IMPLEMENTED | NOT_VERIFIED |
| 文档解析/Chunk | 状态展示 | 调用 Python 并保存草稿 | 解析、分块、分类 | PostgreSQL | IMPLEMENTED | NOT_VERIFIED |
| Embedding | 发布流程触发 | 维度与数量校验 | DashScope/OpenAI compatible | vector(1024) | BROKEN | 否：密钥为空 |
| Vector Search | 检索结果展示 | 网关 | cosine Top-K + 硬过滤 | IVFFlat | BROKEN | 否：数据库停止 |
| Agent Tool Calling | 会话 UI | Internal Agent Tools | Native function calling | MySQL | IMPLEMENTED | NOT_VERIFIED |
| Session/Memory | 会话 UI | 消息历史 | LangGraph checkpoint | MySQL + PostgreSQL | IMPLEMENTED | NOT_VERIFIED |
| Kafka | 无 | Outbox producer | Consumer、幂等、DLQ | Kafka + Redis | BROKEN | 否：broker 未安装/启动 |
| Redis | 无 | 限流与状态缓存 | Consumer 幂等 | Redis | BROKEN | 否：当前未监听 6380 |
| MySQL | 无 | 主业务库 | 只经 Java 工具访问 | MySQL | BROKEN | 否：当前未监听 3307 |
| PostgreSQL/pgvector | 管理 UI | 独立 JdbcTemplate | RAG/checkpoint | PostgreSQL | BROKEN | 否：当前未监听 5432 |
| WebSocket | 用户端、客服端 | `/api/ws/chat` + JWT handshake | 无 | 内存订阅表 | IMPLEMENTED | NOT_VERIFIED |
| SSE | 用户端可调用流式聊天 | `/api/agent/chat/stream` | SSE 流输出 | HTTP | IMPLEMENTED | NOT_VERIFIED |
| 监控 | 管理端 Agent 运行中心 | Actuator/Micrometer | Prometheus metrics | Prometheus/Grafana | IMPLEMENTED | NOT_VERIFIED |
| 日志/Trace ID | 无 | MDC Trace Filter | TraceRecorder/请求日志 | 日志文件 | IMPLEMENTED | NOT_VERIFIED |
| 全局异常处理 | 错误展示 | GlobalExceptionHandler | 结构化错误 | 无 | IMPLEMENTED | 自动化已覆盖一部分 |
| 自动化测试 | 14 个契约通过 | 147 总计，119 通过、28 跳过 | 579 通过、29 失败、4 跳过、4 deselected | Testcontainers 依赖 Docker | PARTIAL | 否：Python 非全绿且集成测试跳过 |
| CI/CD | 无 | GitHub Actions | GitHub Actions | 真实模型 smoke 可跳过 | PARTIAL | NOT_VERIFIED |

## 6. 当前运行状态

2026-09-21 本次检查：

| 服务 | 目标端口 | 现场状态 | 主要原因 |
| --- | ---: | --- | --- |
| MySQL | 3307 | STOPPED | 项目本地进程未启动 |
| Redis | 6380 | STOPPED | 项目本地进程未启动；Compose 默认仍映射 6379 |
| PostgreSQL/pgvector | 5432 | STOPPED | Docker/WSL 不可用 |
| Kafka | 9092 | STOPPED | Docker/WSL 不可用 |
| Java | 8080 | STOPPED | 未启动 |
| Python Agent | 8000 | STOPPED | 未启动；LLM/Embedding Key 缺失 |
| Vue 客服端 | 5173 | STOPPED | 未启动 |
| Prometheus | 9090 | STOPPED | Docker/WSL 不可用 |
| Grafana | 3000 | STOPPED | Docker/WSL 不可用 |

## 7. 自动化证据

| 检查 | 结果 | 解释 |
| --- | --- | --- |
| `mvn -DskipTests compile` | PASS | Java 21 编译通过 |
| `mvn test` | PARTIAL | 147 总计，119 通过，28 个 Docker/Testcontainers 集成测试跳过 |
| Python `pip check` | PASS | 当前虚拟环境依赖一致 |
| Python 全量测试 | FAIL | 579 passed，29 failed，4 skipped，4 deselected；集中在阈值、Embedding/Rerank 配置、检索契约和正式审核状态机 |
| 客服前端契约测试 | PASS | 14/14 |
| 客服前端生产构建 | PASS | 显式设置 `VITE_API_BASE_URL=http://127.0.0.1:8080/api` 后通过 |
| uni-app 微信小程序构建 | PASS | 构建完成 |

这些结果只能证明源码级能力。没有 PostgreSQL、Kafka、模型服务与浏览器 E2E，不能宣称完整系统可用。

## 8. 已确认的配置问题

1. 本机没有 Docker CLI，WSL 未安装，现有 Compose 不能执行。
2. Compose Redis 对外端口为 `6379`，用户目标和现有本地 Java 配置为 `6380`。
3. `application.yml` 的 Redis 默认端口为 `6379`；当前 IDEA 配置依赖进程变量覆盖。
4. `python_agent/setup_knowledge_base.ps1` 使用旧库名 `ecommerce_rag`、旧用户 `ecommerce` 和硬编码口令，与 Compose 的 `after_sales_rag/postgres` 不一致。
5. `application.yml` 的 Agent 自动启动模块引用旧入口 `after_sales_agent.api.http_server`，当前真实入口为 `after_sales_agent.interface.http_server`。
6. 本地 `.env`、`python_agent/.env`、`agent.local.properties` 已被 Git 忽略，共享内部 Token 一致；LLM、Embedding、Vision 可用密钥均为空。
7. 仓库有 SQL migration 文件，但没有 Flyway/Liquibase；已有数据库如何可靠升级尚无统一执行器。
8. CI 会运行 Python 全量测试，因此以当前源码推送会在 Python job 失败。
9. `merchantCs.mock.js` 仍保留显式开发模式；生产构建在缺少 `VITE_API_BASE_URL` 时会主动失败，不会静默回退 mock。

## 9. 下一阶段验收标准

1. 项目自身配置能在新 PowerShell 会话中稳定启动，不读取 `fctts-main5` 的全局数据库值。
2. `docker compose config` 可解析，Redis 明确映射到 6380。
3. PostgreSQL 实际执行 `CREATE EXTENSION vector`，并验证表、1024 维列、索引和一次 Top-K 查询。
4. Kafka 实际创建主题并完成一次 Java producer → Python consumer 事件。
5. Python Agent `/api/health` 可用，Java `/api/agent/health` 可透传。
6. `/api/actuator/health` 返回 200/UP。
