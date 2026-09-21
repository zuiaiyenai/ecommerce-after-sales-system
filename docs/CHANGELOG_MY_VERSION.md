# 个人接管版变更记录

> 基线：`origin/main` 的 `eac3754`
> 当前分支：`main`
> 发布状态：仅本地提交，未 push。

## Phase 1：源码审计

提交：`bdc915b docs: add source-backed project architecture audit`

- 扫描 Java、Vue、Python、SQL、Compose 和配置；
- 区分源码实现、自动化测试、实机运行和生产证据；
- 建立功能矩阵、架构图、风险和后续验收标准。

## Phase 2：本机配置隔离

提交：`d63633e chore: isolate local development configuration`

- 增加根 `.env` 与 Python `.env` 的分层加载；
- 启动 Java 前清理其他项目遗留的高优先级 Spring 环境变量；
- 增加 Agent、Backend 启动脚本；
- 固化 Windows MySQL 3307、Redis 6380 与 Java 21 的本地运行方法。

## Phase 3：pgvector 与 Kafka

提交：`4033433 infra: add verified pgvector and kafka runtime`

- 在 Ubuntu VMware 启动 PostgreSQL/pgvector 与 Kafka；
- 修复 pgvector schema/索引兼容问题；
- 增加 Review Consumer 启动脚本；
- 验证 PostgreSQL 扩展、索引、硬过滤和真实向量查询；
- 跑通 Java Outbox → Kafka → Python → Java → MySQL 审核链路。

## Phase 4：本地文本 AI / RAG 闭环

提交：`5cb0ac2 feat: complete local ai rag chat pipeline`

- Compose 增加 Ollama 与 TEI 本地 AI profile；
- 接入 `qwen2.5:3b`、`bge-m3` 和 `BAAI/bge-reranker-v2-m3`；
- 适配 TEI 数组响应和本地模型超时；
- 将知识重建脚本改为安全 reindex API；
- Java 按登录用户与订单从 MySQL 重建可信 `selected_order`；
- 修复通用知识 `NULL` 数组过滤；
- 修复放宽分类/场景后仍显示可信 Rerank 模式的问题；
- 增加可选聊天情绪前置开关；
- 跑通真实聊天、政策引用和消息落库回读。

验证结果：

```text
Python: 609 passed, 8 deselected
Java（Phase 4 快照）: 148 run, 0 failures, 0 errors, 28 skipped
E2E:    141.35 s, AI mode, 1 trusted citation, MySQL history readback
```

## 当前功能完成度

| 领域 | 状态 |
| --- | --- |
| Java / Vue 核心业务 | DONE |
| MySQL / Redis | DONE |
| PostgreSQL / pgvector | DONE |
| Kafka 正式审核主链 | DONE |
| 文本 LLM / Embedding / Reranker / RAG | DONE |
| Vision | NOT_DONE |
| Prometheus / Grafana 页面 | PARTIAL |
| Docker/Testcontainers 全量门禁 | DONE |
| 生产部署、高可用、压测 | NOT_DONE |

## Phase 5：一键本地运行编排

- 新增 `scripts/dev-start.ps1`，支持 Docker、VMware、现有基础设施三种模式；
- 新增 `scripts/dev-stop.ps1`，按受管 PID 和项目命令行安全停止进程树；
- 新增 Vue、Windows MySQL/Redis 的独立启动脚本；
- PID 和日志统一写入被 Git 忽略的 `.runtime/dev`；
- 实测完成应用全关 → 一键启动 → 应用停止 → VM 容器停止 → 一键恢复；
- 停止基础设施时只执行 `docker compose stop`，不删除数据卷。

## Phase 6：补齐真实集成门禁

- 新增 `scripts/run-vm-testcontainers.ps1` 与 VM 回环 Docker 代理，通过 SSH 安全运行远端 Testcontainers；
- 修正 `AfterSalesTicketMapperMySqlTest` 的精简测试表，使其包含当前 `evidence_revision`、`ai_review_status` 与 Java 签发的 `ai_review_request_id` 契约；
- Python pgvector 集成测试：`3 passed`；
- Python Redis Testcontainers：`1 passed`；
- Python Ollama OpenAI compatible 真实模型测试：`4 passed`；
- Java 全量测试：`148 run, 0 failures, 0 errors, 0 skipped`。

## 仍需维护的事项

1. 配置视觉模型后单独验收图片审核。
2. 为 SQL 引入统一迁移工具，避免依赖手工建库顺序。
3. 验证跨轮 LangGraph checkpoint 恢复与 WebSocket/SSE 浏览器场景。
4. 生产化前补 TLS、密钥管理、监控告警、备份恢复和容量压测。
