# Java + AI 应用后端简历素材

以下表述来自当前源码、测试与仓库内评测报告。提交简历前应把测试数量更新为最新 CI 结果，不把本地 CPU 性能写成生产指标。

## 项目简介

电商售后智能客服系统：以 Java 21、Spring Boot 和 MyBatis-Plus 实现订单、售后工单、客服会话、地址与反馈等业务内核，通过 MySQL、Redis、Kafka Transactional Outbox 保证状态一致性与异步审核可靠性；以 Python LangGraph Agent 接入 Ollama、pgvector 和 Reranker，实现带可信政策过滤、图片凭证分析、确定性 Gate 与人工降级的 AI 售后流程，并使用 Prometheus/Grafana 和 GitHub Actions完成可观测与质量门禁。

## 技术栈

Java 21、Spring Boot 3、Spring Security、MyBatis-Plus、Flyway、MySQL、Redis、Kafka、Transactional Outbox、Python、LangGraph、PostgreSQL/pgvector、pg_trgm、RRF、Ollama、TEI Reranker、SSE、WebSocket、Prometheus、Grafana、Vue 3、uni-app、Docker Compose、GitHub Actions。

## 3 条精简版

1. 基于 Spring Boot + MyBatis-Plus 构建订单、售后、客服、地址与反馈业务闭环，以 JWT 身份解析和资源 ID + 所有者 ID 联合查询实现用户数据隔离，并用 Flyway 与数据库唯一约束保证默认地址一致性。
2. 设计 MySQL Transactional Outbox + Kafka + Redis 幂等认领链路，将耗时 AI 审核从用户提交事务中解耦，结合有限重试、DLQ、版本校验与人工降级处理至少一次投递和模型故障。
3. 构建 Python LangGraph Agent + pgvector 混合检索链路，使用商家/版本/生效时间硬过滤、Dense + Keyword + RRF + Reranker 和确定性 Gate；60 条离线评测集中 Faithfulness 85.99%、Answer Relevancy 90.93%、True Hallucination Rate 5%。

## 5 条完整版

1. **业务内核：** 面向电商售后场景，用 Java 21、Spring Boot 3、MyBatis-Plus 和 MySQL 实现订单、售后工单、客服会话、评价、地址和反馈模块；将业务终态统一收口到 Java Service，避免 Agent 或前端直接修改业务事实。
2. **可靠消息：** 针对数据库提交与 Kafka 发布无法原子完成的问题，实现 Transactional Outbox 定时发布、事件状态流转和失败重试；Consumer 使用 Redis 对 `event_id` 认领、续期与过期接管，并由 Java 以审核请求 ID 和证据版本做最终幂等校验。
3. **受控 Agent：** 以单 AfterSalesAgent 调度 Skill、Workflow 和白名单 Tool，将政策检索、图片凭证分析与复杂案例综合拆成结构化步骤；用最大步数、重复工具检测、确定性 Gate 和 Java 状态机限制模型动作，故障或低置信度时转人工。
4. **知识检索：** 基于 PostgreSQL/pgvector、pg_trgm、RRF 与 TEI Reranker 实现混合检索，在查询前固定商家、类目、政策版本和生效时间过滤条件；知识覆盖不足时最多生成 3 条互补查询并进行一次有界融合，保留来源、Chunk 和降级原因用于审计。
5. **工程质量：** 使用 Prometheus/Grafana 观测 Java、Agent 和 Consumer 的延迟、错误、RAG 降级、Outbox、DLQ 和人工接管；用 GitHub Actions 分别执行 Java、Python、安全评测与前端契约/构建，并在微信开发者工具完成正式路由逐页回归。

## STAR 展开示例

### 异步审核可靠性

- **S：** 图片审核和本地模型推理耗时长，直接同步执行会阻塞售后提交，而且数据库与 Kafka 之间存在双写风险。
- **T：** 让用户提交快速完成，并保证审核事件不会因局部故障永久丢失或重复修改工单。
- **A：** 在同一 MySQL 事务写入工单和 Outbox，由 Publisher 异步发送 Kafka；Consumer 用 Redis 认领并有限重试，最终由 Java 按请求 ID、状态和证据版本落库。
- **R：** 形成可重放、可追踪、可人工接管的至少一次投递链路，相关状态、DLQ 和人工降级均有指标与测试覆盖。

### RAG 可信性

- **S：** 售后政策存在商家、版本和生效时间差异，纯相似度检索可能返回不适用政策。
- **T：** 提高检索覆盖的同时，防止低质量或过期知识触发自动审核。
- **A：** 增加结构化硬过滤、Dense/Keyword 双路召回、RRF、Reranker 与有界多查询；将可信引用、版本一致性、降级状态送入确定性 Gate。
- **R：** 在 60 条离线集上达到 Faithfulness 85.99%、Answer Relevancy 90.93%，True Hallucination Rate 降至 5%；降级结果不会被当成可信政策自动通过。

## 面试自我介绍版本

> 我在这个项目中主要负责 Java 业务内核与 AI 能力的工程化接入。Java 侧用 Spring Boot、MyBatis-Plus 和 MySQL 实现订单、售后工单、客服会话等核心流程，并通过 JWT 数据隔离、事务、Outbox、Kafka 和 Redis 解决权限、一致性和重复消费问题。AI 侧使用 Python LangGraph 接入本地 Ollama 与 pgvector，把政策检索和图片审核拆成受控 Workflow，模型只生成建议，最终结果必须经过确定性 Gate 和 Java 状态机。项目还接入了 Prometheus/Grafana、GitHub Actions 和微信小程序逐页验收，因此我既能解释业务代码，也能说明异步可靠性、RAG 质量和故障降级的完整链路。

## 表述边界

- 可以说“本地完整链路和 CI 已验证”，不要说“已生产落地”或“支撑高并发生产流量”。
- 评测指标仅对应仓库中的 60 条离线数据集，不代表所有业务分布。
- 本地 Ollama 的 CPU 延迟只用于功能闭环，不用于宣称线上 SLA。
- 微信 `touristappid` 下未完整验证的地图/平台能力，需要在正式 AppID 环境单独说明。
