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

## Phase 4 完成时的功能快照

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

## Phase 7：核心业务与知识库真实 E2E

- 核心业务 API 覆盖登录、工作台、商品、订单、会话、消息、工单、评价、401 与 403 权限边界；
- 隔离 Edge 覆盖客服端 13 个页面/守卫检查，155 个资源/API 响应无失败；
- 修正管理端文本导入 URL，前端契约测试从 14 条增至 15 条；
- 将管理端测试检索从固定空列表接到现有 Java → Python Agent → pgvector 真实链路；
- 上传并发布唯一标记 TXT，确认草稿分类、1024 维 Embedding、revision 一致和 RAG 命中；
- 管理端知识库页面显示已发布文档，浏览器过程 27 个 API 响应无失败。

## Phase 8：认证实时聊天链路

- 修复 Spring Security 拒绝 SSE 完成后的 `ASYNC` 再分派问题，并保留初始请求的认证边界；
- SSE 实机返回 `start → token → finish → done`，无流错误；当前为整段回答的单个 `token` 事件；
- 同一 MySQL 会话完成跨轮追问，确认聊天记忆来自消息历史和摘要；
- WebSocket 完成 JWT 握手、订阅、客服消息广播与历史回读，无 Token 握手返回 401；
- 明确 PostgreSQL LangGraph checkpoint 只服务正式审核暂停、补证和恢复；
- 将 Java Agent 超时设为 300 秒，前端超时设为 330 秒，适配本地 CPU 模型约 188–244 秒的链路耗时。

## Phase 9：VM 监控闭环

- 增加 VM 混合拓扑专用 Prometheus 配置，通过 VMware NAT 地址抓取 Windows 应用；
- 增加 `start-vm-observability.ps1`，同步配置和忽略的共享 Token，只启动 Prometheus/Grafana；
- 接入 `dev-start.ps1` 与 `dev-stop.ps1`，并在启动成功前校验三个 target；
- 验证 Java、Python Agent、Review Consumer target 全部 `UP`；
- 验证 4 条告警规则健康，Grafana 数据库正常并自动加载 Agent Overview dashboard。

## Phase 10：本地 Vision 功能闭环

- 在现有 VM Ollama 增加 `qwen2.5vl:3b`，没有新增虚拟机或远程付费 Key；
- 将 Compose 的 Agent/Review Consumer Vision 配置接到本地 Ollama；
- 使用演示用户 JWT 跑通 Java → Python Vision → Ollama → Java；
- 破损图识别为裂纹，正常商品图未识别为破损，两张均返回 `success=true`；
- 单图耗时约 248–256 秒，只作为本地 CPU 功能证据；历史 54 张远程模型指标不归因于本地模型。

## Phase 11：项目归属与演示信息清理

- 移除用户端关于页中没有真实依据的客服电话、备案号、协议链接和版权声明；
- 微信小程序默认改用 `touristappid`，发布前需替换为项目所有者自己的 AppID；
- README 补充本地演示账号、当前本地 Vision 模型以及 Git 贡献和许可证边界；
- 保留现有 Java 包名、Maven 坐标和产品名称，避免没有业务收益的大规模重命名。

## Phase 12：最终运行与文档一致性验收

- 复核 Vue、Java、Agent、Review Consumer、MySQL、Redis、PostgreSQL、Kafka、Ollama、TEI、Prometheus 和 Grafana 当前均可用；
- PostgreSQL 当前有 51 条知识文档、43 个发布版本、43 个 1024 维 chunk 和 1 个草稿，文档已同步为当前实例数据；
- 明确现有数据库尚无迁移版本表；Flyway/Liquibase 需要分别建立 MySQL/PostgreSQL baseline 后再引入，不能在当前数据实例上直接执行全部历史脚本。

## 仍需维护的事项

1. 为 SQL 引入统一迁移工具，避免依赖手工建库顺序。
2. 生产化前补 TLS、密钥管理、备份恢复和容量压测。
