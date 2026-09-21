# Java 后端 / Java + AI 应用面试指南

## 1. 一分钟项目介绍

这是一个智能电商售后系统。Java Spring Boot 负责用户、订单、工单、会话、权限、事务和最终状态；Python LangGraph Agent 负责咨询编排、RAG 和正式审核；MySQL 保存业务真相，PostgreSQL/pgvector 保存知识与向量，Redis 做限流和幂等，Kafka 通过 Transactional Outbox 驱动异步审核。文本 AI 已在本地 CPU 环境跑通 Ollama、Embedding、pgvector、RRF、TEI Reranker、LLM Tool Calling 和消息落库。

## 2. 我能真实描述的工作

- 审计 Java、Vue、Python、SQL 与 Compose 的真实调用关系；
- 隔离本机多项目环境变量，建立可重复启动脚本；
- 在 VMware 中部署 PostgreSQL/pgvector、Kafka、Ollama 和 TEI；
- 修复知识库通用维度的 `NULL` 过滤和放宽检索的可信契约；
- 让 Java 按登录用户从 MySQL 重建订单上下文，防止客户端伪造 RAG 过滤条件；
- 跑通 Java → Agent → Embedding → pgvector → Reranker → LLM → Java → MySQL；
- 用自动化测试、HTTP 回读、数据库记录和日志区分源码能力与实机证据。

不要声称生产高并发、云上高可用、Vision 已完成或所有 Testcontainers 用例已执行。

## 3. Transactional Outbox

**代码在哪里**：`AfterSalesServiceImpl`、`AfterSalesReviewEventServiceImpl`、`after_sales_event_outbox`。

**为什么这样设计**：创建工单和发送 Kafka 无法放进一个普通本地事务。先在同一 MySQL 事务写工单与 Outbox，再异步发布，可避免业务成功但事件永久丢失。

**涉及原理**：本地事务、至少一次投递、幂等、重试、退避、DLQ。

**缺点**：存在发布延迟、重复投递和 Outbox 表清理成本。

**替代方案**：CDC/Debezium、事务消息、业务允许时直接同步调用。

**面试回答**：项目选择“本地事务 + Outbox + 幂等消费”，保证不丢业务事件；它不是恰好一次，重复由 `event_id` 和业务条件更新吸收。

## 4. Kafka 消费幂等

**代码在哪里**：Python `kafka_adapter.py`，Java `AfterSalesReviewDlqConsumer`。

**为什么这样设计**：Kafka 可能重复投递，长时间 AI 审核也可能超过普通处理时长。

**涉及原理**：关闭自动提交、处理成功后提交 offset、幂等键、租约续期、DLQ。

**缺点**：Redis/文件幂等记录也要维护；单 partition 本地环境没有证明扩展能力。

**面试回答**：offset 提交只代表消息位置，不能代替业务幂等。项目同时校验 `event_id`、`review_request_id` 和 `evidence_revision`。

## 5. Java 与 Python 的职责边界

**代码在哪里**：`InternalAgentToolsController`、`AgentToolRegistry`、`AgentConversationContextService`。

**为什么这样设计**：模型输出不应直接成为订单或工单真相。Java 保留鉴权、事务、状态机和最终写入，Python 只编排与建议。

**涉及原理**：防腐层、最小权限、零信任输入、契约边界。

**缺点**：跨进程调用增加延迟和部署复杂度。

**替代方案**：同 JVM AI SDK、消息驱动命令、独立业务微服务。

**面试回答**：客户端和 LLM 都是不可信输入。Java 用登录用户重查 MySQL，并在每次工具写入前重做业务校验。

## 6. RAG 检索

**代码在哪里**：`PgVectorKnowledgeRetriever`、`knowledge_filters.py`、`reranker_client.py`。

**为什么这样设计**：向量召回适合语义，FTS/pg_trgm 适合关键词和拼写，RRF 融合后再精排可提高排序质量。

**涉及原理**：Embedding、cosine、Top-K、全文索引、RRF、Rerank、硬过滤。

**缺点**：CPU 本地模型慢；过滤、阈值和索引参数需要评测集校准。

**替代方案**：Elasticsearch/OpenSearch、托管向量库、仅 BM25、端到端长上下文。

**面试回答**：可信政策必须同时满足严格业务过滤、Reranker 成功、分数阈值和引用契约。召回放宽只用于提示，不能自动审批。

## 7. MySQL 与 PostgreSQL 为什么分开

**代码在哪里**：`application.yml`、`DATABASE_DESIGN.md`、pgvector schema。

**为什么这样设计**：MySQL 已承载业务事务；PostgreSQL 提供 pgvector、FTS、pg_trgm 和 LangGraph checkpoint。

**涉及原理**：多数据源、数据所有权、最终一致性、索引选择。

**缺点**：备份、迁移、监控和本地环境更复杂，不能跨库直接做 ACID 事务。

**面试回答**：两个库按事实职责拆分，不做跨库强事务。Python 不越过 Java 修改 MySQL。

## 8. 慢链路怎么优化

当前 4 vCPU VM 的真实聊天耗时 141.35 秒。主要成本来自本地文本生成，严格检索约 25 秒。

可解释的优化顺序：

1. 先用 trace 拆分 Embedding、向量查询、Rerank、LLM；
2. 缓存 query embedding，控制候选数与上下文长度；
3. 可选情绪分析与主回答并行或按场景关闭；
4. 使用更快模型、GPU 或远程推理；
5. 用 SSE 改善首字延迟；
6. 压测后再调整线程池、连接池和模型并发。

不能把一次功能验收延迟包装成生产吞吐指标。

## 9. 高频追问速答

**为什么不是微服务？** 业务规模适合模块化单体，Java 内部事务和维护成本更可控；Python 只因 AI 生态独立部署。

**如何避免模型幻觉自动改工单？** 严格政策过滤、可信引用、Java 守卫、状态机条件更新，任何一项不满足就补证或转人工。

**RRF 是什么？** 按不同召回列表中的名次累加 `1/(k+rank)`，不要求向量分数和关键词分数处于同一量纲。

**为什么 ID 用字符串？** Snowflake 类 64 位 ID 超过 JavaScript 安全整数范围，JSON 字符串可避免精度损失。

**为什么 Actuator 曾是 503？** 整体健康包含 PostgreSQL 等依赖；依赖未启动不等于 Java 核心 API 全部失效，证据要分层描述。

**是否实现恰好一次？** 没有。系统实现至少一次投递与幂等处理，这是更准确的工程表述。

## 10. 简历可写亮点

- 基于 Spring Boot、MySQL、Redis、Kafka 与 Transactional Outbox 实现售后工单异步审核，使用幂等键、手动提交、租约续期和 DLQ 保障可恢复性。
- 设计 Java 与 LangGraph Agent 的可信边界，由 Java 重建订单上下文并校验最终写入，防止客户端或模型伪造业务事实。
- 搭建 pgvector 混合检索链路，组合 1024 维 Embedding、FTS、pg_trgm、RRF 与 Reranker，并对放宽召回实施不可信降级。
- 在本地 VMware 完成 PostgreSQL、Kafka、Ollama、TEI 与 Windows 应用混合部署，跑通真实政策问答、引用和 MySQL 消息回读。
