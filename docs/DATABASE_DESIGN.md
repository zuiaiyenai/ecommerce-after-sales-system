# 数据库设计

> 验证日期：2026-09-22
> 依据：当前 SQL、Java/Python 数据访问代码，以及本机 MySQL 与 VMware PostgreSQL 实例。

## 1. 数据职责

本项目使用两个关系数据库，职责不能互换：

| 数据库 | 真相范围 | 主要访问方 |
| --- | --- | --- |
| MySQL 8.x | 用户、客服、商品、订单、售后工单、会话、消息、评价、通知、Outbox | Java Spring Boot |
| PostgreSQL 16 + pgvector | 知识文档、草稿、发布版本、向量、全文检索列、LangGraph checkpoint | Java 知识管理、Python Agent/RAG |

Python Agent 不直接修改 MySQL 业务结果。它通过 `/api/internal/agent-tools/**` 调用 Java，由 Java 校验用户、商家、工单状态和审核实例后再写库。

## 2. MySQL 业务模型

当前本机实例有 15 张表：

| 领域 | 表 | 作用 |
| --- | --- | --- |
| 身份 | `user_info`、`sys_user` | 终端用户与客服/管理员 |
| 商品订单 | `product_info`、`order_info`、`order_item`、`shipping_address` | 商品、订单快照和收货信息 |
| 售后 | `after_sales_ticket`、`ticket_attachment`、`ticket_log` | 工单、证据和状态审计 |
| 异步事件 | `after_sales_event_outbox` | 与工单事务一起写入的 Kafka 待发布事件 |
| 会话 | `chat_session`、`chat_message`、`agent_tool_call` | 客服会话、消息和工具调用审计 |
| 反馈通知 | `review_info`、`message_notice` | 用户评价和站内通知 |

### 2.1 关键约束

- `order_no`、`ticket_no`、`event_id` 均有唯一索引。
- `after_sales_ticket.active_scope_key` 是生成列；同一用户与订单只能存在一张打开中的工单。
- `ai_review_request_id` 唯一，并同时作为一次正式审核的稳定实例 ID 和 LangGraph `thread_id`。
- `evidence_revision` 每次有效补证递增，用于拒绝旧审核结果。
- `ticket_log` 记录每次状态变化，不能用覆盖工单当前状态代替审计日志。

### 2.2 工单与 Outbox 原子边界

`AfterSalesServiceImpl.create` 在同一 MySQL 事务中写入：

```text
after_sales_ticket
+ ticket_attachment（可选）
+ ticket_log
+ after_sales_event_outbox
```

事务提交后，`AfterSalesReviewEventServiceImpl` 才能读取并发布 Outbox。Kafka 临时不可用不会造成“工单已创建但事件永久丢失”。

## 3. PostgreSQL / pgvector 模型

### 3.1 文档与发布

| 表 | 作用 |
| --- | --- |
| `knowledge_document` | 文档主记录、商家范围、来源、策略版本、有效期和当前发布版本 |
| `knowledge_chunk_draft` | 解析和人工确认阶段的草稿分块 |
| `knowledge_chunk` | 已发布且可检索的知识分块 |

发布时先写草稿，确认后再生成 Embedding 并写入 `knowledge_chunk`。`knowledge_document.published_revision` 指向当前有效版本，查询同时要求：

- 文档有效且没有逻辑删除；
- chunk 的 `revision` 等于 `published_revision`；
- 商家为当前商家或 `GLOBAL`；
- 当前时间落在 `valid_from` / `valid_to` 范围；
- 分类、场景和意图符合硬过滤条件。

### 3.2 检索列和索引

`knowledge_chunk` 的关键列：

| 列 | 类型 | 用途 |
| --- | --- | --- |
| `embedding` | `vector(1024)` | cosine 向量召回 |
| `search_vector` | `tsvector` | PostgreSQL FTS |
| `search_text` | `text` | `pg_trgm` 拼写补召回 |
| `product_categories` | `text[]` | 商品分类硬过滤 |
| `scenes` | `text[]` | 场景硬过滤 |
| `intents` | `text[]` | 意图硬过滤 |

索引包括：

- `embedding vector_cosine_ops` 的 IVFFlat；
- `search_vector` 的 GIN；
- `search_text gin_trgm_ops` 的 GIN；
- 分类、场景和意图数组的 GIN。

PostgreSQL 16 的 `tsvector` GIN 索引使用默认 operator class，写法为 `USING GIN (search_vector)`。

## 4. 当前实机验证

VM 地址为 `192.168.100.130`（NAT DHCP，重启后可能变化）。已验证：

- Windows MySQL `8.0.41`，业务库有 15 张表；Compose 新建环境使用 MySQL `8.4`；
- PostgreSQL `16.15`；
- pgvector `0.8.6`；
- `vector`、`pg_trgm` 扩展存在；
- `knowledge_chunk.embedding` 为 `vector(1024)`；
- IVFFlat、全文 GIN 和 trigram GIN 索引存在；
- 51 条 `knowledge_document` 已导入，其中 43 条有发布版本；
- 43 条发布文档已通过本地 `bge-m3` 生成 43 个真实 chunk，`published_revision` 为 43/43；
- 43 个 `knowledge_chunk.embedding` 均为 1024 维；
- 查询“七天无理由退货需要满足什么条件”时，商户 `MERCHANT_DEMO` 的 Top-1 为 `return_policy_001`，cosine 分数为 `0.8064`；
- 事务内写入 1024 维测试向量后，cosine 自相似度为 `1.000000`，随后已回滚；
- 真实 PostgreSQL 硬过滤集成测试 3/3 通过。

当前 `knowledge_chunk` 为 43，`knowledge_chunk_draft` 为 1。已发布批次使用安全 reindex 流程生成：先完成全部 Embedding，再锁定并校验源文档版本，最后替换对应 chunk 并更新 `published_revision`；草稿不会进入正式检索。

## 5. 变更规则

1. MySQL 业务表和 PostgreSQL 知识表分别迁移，不跨库做分布式事务。
2. 修改 `vector(1024)` 前必须同步模型维度、Java 发布校验、Python Retriever 与索引重建方案。
3. 修改工单状态机时同时检查 Java 写入条件、Python 回写契约、Outbox/DLQ 和前端状态文案。
4. 不通过清空数据库修复迁移问题；先备份、核对残留 DDL，再做数据保留式修复。

## 6. 迁移策略边界

- 新建 Compose 数据卷分别通过 `sql/schema.sql` 和 `sql/pgvector_schema.sql` 初始化 MySQL 与 PostgreSQL。
- 已有数据库目前按文件名日期顺序人工执行 `sql/migrations` 中的增量脚本；执行前必须备份并检查目标列、索引和约束是否已存在。
- 仓库当前没有 Flyway/Liquibase 版本表，无法自动证明某个已有实例已经执行了哪些历史脚本。这是生产化前仍需解决的维护风险。
- 后续引入迁移工具时，应为 MySQL 和 PostgreSQL 分别建立 baseline，登记既有脚本校验和，并同时验证“空库初始化”和“当前数据保留升级”两条路径；不能直接把现有 18 个脚本当作全新待执行版本。
