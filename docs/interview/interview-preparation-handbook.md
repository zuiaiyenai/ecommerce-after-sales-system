# 智能电商售后 Agent：面试前必看手册

> 适用方向：Java 后端开发实习生、AI Agent 应用开发实习生。
> 阅读依据：当前仓库中的 Java/Python 源码、SQL、配置、Compose、README、测试与离线评测。
> 使用原则：只讲代码中真实存在的设计；无法从仓库证明的个人职责、线上规模和生产效果，不主动夸大。

---

## 0. 面试前先记住这五句话

1. 这不是“接一个大模型 API 的聊天机器人”，而是把概率性的 AI 能力接入确定性的售后业务系统。
2. Java 拥有业务，Python 辅助业务：订单、工单、权限、事务、状态流转和最终落库都在 Java；LangGraph、LLM、RAG、图片审核和工具规划在 Python。
3. MySQL 是业务事实来源；PostgreSQL pgvector 是知识来源；Redis 是短期控制状态；Kafka 是异步事件通道。
4. 系统接受 Kafka 至少一次投递，通过 `event_id → reviewRequestId`、Redis claim、MySQL 唯一约束和 SQL CAS，让重复执行不重复改变业务结果。
5. AI 不确定、模型失败、政策证据不足、图片置信度不足或业务风险过高时，系统优先转人工，而不是让模型“猜一个答案”。

如果面试中思路混乱，就回到这五句话。

---

## 1. 两分钟项目介绍模板

我做的是一个智能电商售后 Agent 项目，目标是缩短售后初审等待时间，同时降低客服处理重复材料核验和政策查询的压力。它不是让模型直接决定退款，而是把传统 Java 售后系统与 Python Agent 结合起来。

架构上，Spring Boot 负责确定性的业务能力，包括 JWT 鉴权、订单和工单查询、工单创建、附件与日志持久化、状态流转、内部 Agent 接口和最终审核结果落库；Python 负责 LangGraph 工作流、LLM 规划、RAG 政策检索、图片凭证分析、情绪识别和工具调用。MySQL 是业务事实来源，PostgreSQL pgvector 保存知识文档和向量，Redis 用于限流、短期审核状态和 Kafka 消费幂等，Kafka 用于把工单创建与耗时的 AI 初审解耦。

核心链路是：Java 在一个 MySQL 事务中创建工单、附件、操作日志和 Outbox 事件；Publisher 定时将事件发送到 Kafka；Python Consumer 基于 `event_id` 做幂等 claim，再执行 LangGraph。Agent 查询 Java 中的订单和工单，结合 RAG、图片审核、情绪和风险规则形成初审结果，然后通过 Java 内部接口提交。Java 使用 `reviewRequestId` 和带状态条件的 SQL 更新，防止重复回调以及迟到的 AI 结果覆盖人工处理结果。

项目的重点不是模型本身，而是如何把不稳定、可能超时的模型调用放进一个有权限边界、限流、审计、追踪、幂等、重试、熔断、人工兜底和可测试性的业务系统。我会把仓库中的离线指标描述为小规模评测结果，不会说成线上生产效果。

### 个人职责怎么说

只有你确实做过的内容才能替换进下面模板：

> 我投入最多的 Java 模块是______，对应类/方法是______，解决的问题是______；我投入最多的 Python 模块是______，对应文件/节点是______。我通过______测试验证了______。团队协作中，______由其他成员负责，我主要负责______。

不要只说“我负责全部后端”或“几乎全链路”。面试官会立刻追问类名、方法名、故障和测试。

---

## 2. 项目的核心设计思想

### 2.1 概率系统不能拥有确定性业务

LLM、RAG 和视觉模型都可能超时、限流、输出格式错误、产生幻觉或在人工已经处理后才返回结果。因此项目把“推理”和“业务生效”分开：

```text
Python：理解、检索、分析、提出初审结果
Java：校验身份与归属、检查状态、执行条件更新、持久化和通知
MySQL：保存最终业务事实
```

AI 可以建议和编排，但不能绕过 Java 直接修改 MySQL。

### 2.2 快路径和慢路径分离

用户创建售后工单是快路径，模型初审是慢路径：

```text
快路径：校验 → MySQL 事务写工单与 Outbox → 返回用户
慢路径：Outbox → Kafka → Python Agent → Java 回写
```

模型、RAG 或视觉服务不可用，不应该让用户一直卡在提交接口。

### 2.3 至少一次投递 + 应用层幂等

项目没有宣称端到端 Exactly Once。Outbox 可能重复发布，Kafka 可能重复消费，Python 也可能重试 Java。系统用分层幂等处理重复，而不是假设重复不会发生。

### 2.4 失败优先可见、可恢复、可人工接管

- 可恢复的基础设施错误只做有限重试；
- 政策、图片或证据不确定时转人工；
- Outbox 重试耗尽时先持久化人工接管，再标记事件终态；
- Python 失败时优先调用 Java 写人工审核；
- 最终失败进入 DLQ，保留排查信息。

---

## 3. 系统边界和数据所有权

| 组件 | 真实职责 | 不应该承担的职责 |
|---|---|---|
| Java Spring Boot | 鉴权、权限、订单、工单、会话、消息、事务、状态机、审核落库、通知 | 不在提交接口同步等待长时间模型推理 |
| Python Agent | LangGraph、LLM、RAG、视觉审核、情绪分析、工具编排 | 不直接写 MySQL，不拥有工单最终状态 |
| MySQL | 订单、工单、会话、消息、日志、Outbox 等业务事实 | 不保存向量知识 |
| PostgreSQL pgvector | 知识文档、Chunk、Embedding、元数据检索 | 不保存售后业务状态 |
| Redis | 限流、消费 claim、短期状态缓存 | 不作为长期业务事实来源 |
| Kafka | 异步事件投递和解耦 | 不作为工单最终状态来源 |
| 前端 | 交互、展示、重新加载服务端历史 | 不自行决定业务状态 |

Java 适合业务事务、类型约束和权限；Python 生态适合 LangGraph、模型 SDK、向量检索和多模态。拆分会增加网络失败、一致性和部署成本，所以项目还需要内部鉴权、稳定 DTO、Trace、幂等号、超时和重试。

---

## 4. 售后工单与 AI 初审完整链路

```text
用户提交售后
  ↓
AfterSalesController.create
  ├─ 获取当前用户
  └─ Redis 限流
  ↓
AfterSalesServiceImpl.create  [MySQL 事务]
  ├─ 查询订单
  ├─ 检查/复用活动工单
  ├─ 插入 after_sales_ticket
  ├─ 插入 ticket_log
  ├─ 插入附件
  └─ 插入 after_sales_event_outbox
  ↓
事务提交后缓存 AI_REVIEWING
  ↓
AfterSalesReviewEventServiceImpl.publishPending
  ↓
Kafka: after_sales.review.request
  ↓
AfterSalesReviewKafkaConsumer
  ├─ Redis event_id claim
  ├─ LangGraph Agent
  ├─ Java 内部工具查询
  ├─ RAG / Vision / Emotion / 风险规则
  └─ submit_ai_review
  ↓
InternalAgentToolsController.submitAiReview
  ├─ 内部 Token
  ├─ 用户/订单/工单上下文校验
  ├─ reviewRequestId 幂等判断
  ├─ SQL CAS
  ├─ 日志与系统消息
  └─ 事务提交后缓存与 WebSocket 通知
```

### 4.1 工单创建事务

`AfterSalesServiceImpl#create` 在同一个 MySQL 事务中写工单、日志、附件和 Outbox，保证：

```text
工单存在 ⇒ 至少有一条待发布的初审事件记录
事务失败 ⇒ 工单、附件、日志和 Outbox 一起回滚
```

### 4.2 重复创建工单

代码先查询同一用户、同一订单是否已有 `PENDING`、`PENDING_REVIEW`、`PROCESSING` 工单。但预查询存在并发窗口，所以数据库还有生成列：

```sql
active_scope_key =
  CASE
    WHEN deleted = 0
     AND status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING')
    THEN CONCAT(user_id, ':', order_id)
    ELSE NULL
  END
```

`uk_after_sales_ticket_active_scope` 唯一索引保证两个并发请求不能同时插入活动工单。失败请求捕获 `DuplicateKeyException` 后重新查询并返回已有工单。

### 4.3 当前必须承认的权限缺口

`AfterSalesServiceImpl#create` 当前检查订单是否存在，但代码中暂未发现 `order.userId == 当前登录用户 userId` 的归属比较。用户若提交他人的 `orderId`，存在越权创建售后工单的风险。

修复方向：

- Service 查询订单时同时带 `id + userId` 条件，或查询后显式比较；
- Controller 校验不能代替 Service 校验；
- 内部 Agent 接口仍独立校验 user/ticket/order 绑定；
- 增加“用户 A 使用用户 B 订单 ID”测试。

---

## 5. 权限、安全与接口边界

### 5.1 用户和商家接口

- Spring Security 使用无状态 JWT；
- `JwtAuthenticationFilter` 解析 Token；
- Controller 使用当前用户 ID，不信任请求体中的用户 ID；
- 商家客服操作还需要校验人员与商家关系。

### 5.2 Java 内部 Agent 接口

Python 调 Java 时携带 `X-Agent-Internal-Token`。`InternalAgentAuthenticationFilter` 和 Controller 校验保护内部工具、知识及监控接口。内部 Token 只证明调用方是受信任服务，不能证明业务对象一定合法，所以 `InternalAgentToolsController` 还要验证：

```text
userId ↔ ticketId ↔ orderId
```

是否属于同一个上下文。

### 5.3 Python HTTP 信任边界

Python 除健康检查外也要求内部 Token。HTTP `/agent/chat` 会覆盖客户端伪造的 `client_context.source=kafka`，重置为 `java_gateway`。只有 Kafka Consumer 构造的来源才允许正式调用 `submit_ai_review`，防止普通聊天请求冒充后台审核。

### 5.4 WebSocket

- 地址：`/ws/chat`；
- 握手阶段校验 JWT；
- 订阅前校验用户拥有会话，或客服属于对应商家；
- 断连时从订阅映射中移除连接。

风险：JWT 放在 WebSocket URL 查询参数中可能进入日志或浏览器记录。生产环境更适合短期票据、Cookie 或受控子协议认证。

### 5.5 Gateway 的准确说法

仓库中有应用内 `AgentGatewayController/AgentGatewayServiceImpl`。代码中暂未发现独立 Spring Cloud Gateway 服务，不能说项目已经实现“Spring Cloud Gateway 统一鉴权”。

---

## 6. 限流和并发隔离

### 6.1 Java Redis 限流

售后创建使用：

```text
rate:user:{userId}:after_sales
```

AI 聊天使用：

```text
rate:user:{userId}:ai_chat
```

`RedisRateLimiterServiceImpl` 使用 Lua 原子完成计数和 TTL 设置，属于固定窗口限流。Redis 异常时选择 fail-open：提高核心业务可用性，但缓存故障期间保护能力下降。

### 6.2 Java Gateway Semaphore

`AgentGatewayServiceImpl` 根据模型副本数和单实例容量建立公平 `Semaphore`，只等待有限队列时间；拿不到许可时返回繁忙或进入人工兜底，避免请求压垮 Python。

### 6.3 Python 模型并发

`resilient_llm_runtime.py` 使用 `BoundedSemaphore` 控制模型并发。等待超过 `LLM_MAX_QUEUE_WAIT_SECONDS` 后快速失败。`.env.example` 中的并发数只是配置默认值，不代表线上容量验证。

### 6.4 注意 SSE

普通 Java Agent 请求会使用 Gateway Semaphore，但当前 `streamChat` 路径没有看到相同的许可获取逻辑，不能说所有 Agent 请求都经过统一并发隔离。

---

## 7. 审计、日志和追踪

### 7.1 业务审计

工单关键变化写入 `ticket_log`，记录原状态、新状态、操作类型和原因。AI 初审保存请求 ID、结果、置信度和审计 Payload；RAG 查询、检索模式、命中与证据引用也进入执行结果或审计数据。当前 citation 不只含来源和分数，还可追到 `chunk_id/document_id`、标题、商家、标题路径、页码、发布 revision、政策版本和有效期。

### 7.2 Trace

Outbox Payload 携带 `trace_id`，Python 使用请求上下文和 `TraceRecorder` 串联：

- `event_id`、`ticket_id`；
- LangGraph 节点和工具；
- 模型和检索信息；
- 失败分类。

指标使用固定低基数 Label，不把 `event_id/ticket_id` 直接作为 Prometheus Label，避免基数爆炸。

### 7.3 四类可观测数据

| 类型 | 回答的问题 |
|---|---|
| 业务审计 | 谁在什么时候把工单从什么状态改成什么状态 |
| 应用日志 | 某次运行为什么异常 |
| Trace | Java、Kafka、Python、工具和模型调用如何串联 |
| Metrics | 成功率、延迟、重试和失败类型的趋势 |

---

## 8. Transactional Outbox

### 8.1 为什么需要

MySQL 提交后再发 Kafka，可能在两者之间宕机而丢事件；先发 Kafka 再提交 MySQL，又可能处理一个最终未提交的工单。Outbox 将业务数据和待发送事件放在同一个 MySQL 事务，再异步发布。

### 8.2 Publisher 的真实语义

`AfterSalesReviewEventServiceImpl#publishPending` 定时扫描 `NEW/FAILED`。`publishOne`：

1. `KafkaTemplate.send(...).get()` 等待 Broker 确认；
2. 将 Outbox 更新为 `PUBLISHED`；
3. 失败时增加重试次数和下次时间；
4. 重试耗尽后先写人工接管，再标记 `DEAD`。

### 8.3 Kafka 成功但 Outbox 状态没更新

```text
Kafka 已收到 E1
  ↓
更新 Outbox=PUBLISHED 前宕机
  ↓
重启后再次扫描 E1
  ↓
Kafka 收到重复 E1
```

所以 Outbox 是至少一次投递，不是 Exactly Once。

### 8.4 当前局限

- 扫描时暂未发现行锁、`SKIP LOCKED` 或发布抢占，多实例可能重复发布；
- `publishOne` 是同类内部调用的 `protected @Transactional`，存在 Spring 自调用绕过代理的风险；
- 下游必须以同一个 `event_id` 幂等。

可优化为状态抢占、租约、条件更新、独立 Spring Bean，或 `FOR UPDATE SKIP LOCKED`。

---

## 9. Kafka Consumer、ACK、offset、重试和 DLQ

### 9.1 基本配置

```python
enable_auto_commit=False
auto_offset_reset="earliest"
group_id="python-after-sales-agent-review"
```

消息被拉取不代表业务已完成，必须等 Java/MySQL 得到可确认结果后才能推进 offset。

### 9.2 正常流程

```text
收到并校验消息
  ↓
Redis claim event_id
  ↓
运行 Agent
  ↓
Java 写入 AI 结果或人工接管
  ↓
Redis 写终态
  ↓
consumer.commit()
```

### 9.3 Redis claim

Key：

```text
agent:event:{event_id}
```

Value 包含：

```json
{
  "status": "PROCESSING",
  "consumer_id": "hostname:pid:uuid",
  "attempt": 1,
  "updated_at_epoch": 0
}
```

第一次用 `SET NX EX` 抢占，运行中默认每 10 秒刷新心跳和 TTL。

状态语义：

- `COMPLETED/MANUAL_REQUIRED/FAILED`：终态，可以 ACK；
- 新鲜 `PROCESSING`：不能 ACK；
- 超过 stale 的 `PROCESSING`：通过 Redis `WATCH/MULTI/EXEC` CAS 接管。

当前代码对新鲜 `PROCESSING`：

```text
pause 当前分区
  → seek 回当前 offset
  → 短暂等待
  → resume
  → 重新检查状态
```

这修复了单 Consumer 快速重启后误 ACK 的窗口。

### 9.4 MySQL 成功但 ACK 前宕机

Kafka 会重投：

- Redis 终态仍在：直接识别重复；
- Redis 丢失：可能重新执行并回调 Java；
- Java 通过相同 `reviewRequestId` 返回幂等结果；
- SQL CAS 防止二次改变工单。

Redis 是协调层，MySQL 是最终防线。

### 9.5 非法消息与 DLQ

- JSON 错误或缺字段：先同步确认 DLQ 发送成功，再提交原 offset；
- Agent 失败：优先调用 Java 写人工接管；
- 人工接管也失败：发 DLQ、记录失败，再提交 offset；
- Java DLQ Consumer 再将持久失败转换成可见人工状态。

### 9.6 为什么 `@Transactional` 不能保证 MySQL 与 offset 原子

数据库事务与 Kafka offset 属于不同资源，Consumer 还在 Python 进程。项目不假装两者原子，而是允许重投，再用 `event_id`、Redis、Java 幂等和 SQL CAS恢复。

### 9.7 部署缺口

仓库有 `kafka_review_consumer.py`，但 Python Dockerfile、`run_agent.ps1` 和 `compose.yml` 主要启动 HTTP Server。代码中暂未发现 Compose 自动启动独立 Kafka Consumer，异步初审 Consumer 需要另行启动。

---

## 10. 幂等和 CAS：必须完整讲清

### 10.1 四层幂等

| 重复来源 | 手段 |
|---|---|
| 用户重复创建 | 活动工单预查询 + `active_scope_key` 唯一索引 + 重复键后返回旧工单 |
| Outbox 重复发布 | 同一 Outbox 行保持相同 `event_id` |
| Kafka 重复消费 | Redis claim、状态、TTL、心跳、stale CAS |
| Python 重复回调 | `event_id → reviewRequestId`、唯一索引、幂等响应、SQL CAS |

### 10.2 Java 回写幂等

`InternalAgentToolsController#submitAiReview` 检查请求 ID 是否等于工单现有 `aiReviewRequestId`。相同则返回已有结果和 `idempotentReplay=true`，不重复写状态、日志和通知。数据库还对 `ai_review_request_id` 建唯一索引。

### 10.3 SQL CAS

AI 通过类似：

```sql
UPDATE after_sales_ticket
SET ai_review_request_id = ?,
    ai_review_result = 'APPROVE',
    status = 'PROCESSING'
WHERE id = ?
  AND deleted = 0
  AND status IN ('PENDING', 'PENDING_REVIEW')
  AND ai_review_request_id IS NULL
```

查询与更新之间可能被人工线程修改。条件 UPDATE 将检查与写入合成一个数据库原子操作；影响 0 行就拒绝重复或迟到结果。

### 10.4 人工处理后迟到 AI

人工处理后的状态不再满足 CAS 条件，迟到 AI 只能被记录为 stale，不能覆盖人工结果。

### 10.5 当前人工审核并发局限

商家人工审核主要是“先查再 `updateById`”，暂未发现与 AI 回写同等强度的 SQL CAS。两个客服同时审核可能后写覆盖前写，可增加状态条件或版本号。

---

## 11. Redis 的四类用途

| 用途 | Key/方式 | 一致性策略 |
|---|---|---|
| 售后/聊天限流 | `rate:user:{id}:...` | Lua 固定窗口，异常 fail-open |
| Kafka 消费幂等 | `agent:event:{event_id}` | NX、TTL、心跳、stale CAS |
| AI 审核状态缓存 | `review:status:{ticketId}` | 短 TTL，未命中回源 MySQL |
| Redis 故障降级 | 本地 JSONL store | 仅单实例有限去重，不是最终事实 |

面试总结：

> Redis 减少重复工作、保护下游并提供短期协调；所有会影响工单最终状态的正确性必须由 MySQL 兜底。

---

## 12. LangGraph Agent

### 12.1 工作流

当前主流程在 `application/after_sales_workflow.py`：

```text
receive_message
  ↓
classify_or_plan
  ↓
tool_call
  ↓
observe_tool_result
  ↓
decide_next
  ├─ 再调用工具
  ├─ human_handoff
  └─ final_reply
```

### 12.2 Agent State

State 保存本轮 user/session/ticket/order、消息、附件、历史、来源、工具参数/结果、错误、observation、人工标记、RAG、图片证据和最终回复。它是本轮内存上下文，不是持久化状态或长期会话存储。

### 12.3 工具边界

工具包含订单、工单、商家政策查询，RAG，图片审核，提交 AI 初审，转人工，追加消息和请求证据。Python 不提供创建售后工单工具，避免模型绕过 Java 正常入口。

### 12.4 防失控

默认：

```text
MAX_AGENT_STEPS = 8
MAX_TOOL_CALLS = 10
MAX_DUPLICATE_TOOL_CALLS = 2
```

工具错误按权限、参数、未找到、超时、服务不可用分类；可恢复错误有限重试，持续失败转人工。关键规则写在代码 Guard 中，不只依赖 Prompt。

### 12.5 人工接管

接管通过 Java 内部工具持久化工单人工标记、优先级、审计和通知。AI 只发出接管请求，Java 决定状态是否生效。

---

## 13. RAG

### 13.1 文档处理

当前是“解析草稿 -> 人工审阅 -> 发布”的闭环，不是上传后直接替换线上 Chunk：

```text
Java 上传并创建 PROCESSING(revision=N)
  -> 事务提交后按 documentId + revision 调 Python /api/knowledge/parse
  -> Python 解析、结构化切片并给出分类建议
  -> Java 原子写 knowledge_chunk_draft，状态变为 REVIEW_REQUIRED
  -> 人工按 expectedRevision 修改文档/Chunk 分类
  -> 发布 CAS 到 PUBLISHING(revision=N+1)
  -> 事务提交后 Worker 对该明确 revision 生成 Embedding
  -> PostgreSQL 事务写正式 Chunk 并切换 published_revision，状态变为 PUBLISHED
```

- 支持文本层 PDF、Markdown、UTF-8/UTF-8-BOM TXT；不支持 OCR、扫描件、DOCX、HTML；
- 混合 PDF 中，某页有内容流或图片却没有文本层时 fail closed，返回 `PDF_TEXT_LAYER_MISSING`；真正空白页可保留；
- 解析还有 `PDF_ENCRYPTED`、`FILE_DECODE_FAILED`、`DOCUMENT_CONTENT_EMPTY`、`DOCUMENT_CHUNKING_FAILED` 等稳定错误码；
- 默认 `structured_recursive_v1`：target 500 tokens、hard max 800、min merge 150、hard chars 6400；
- 先识别标题/结构块，再组合段落；超限时按句子、列表项、代码行或表格行拆分，最后才递归按 Token 兜底；表格拆分会重复表头；
- 相邻小块只在标题路径和页范围兼容时合并，没有固定 overlap；
- Chunk 原文保持不变，结构字段包含 `heading_path`、`page_start/page_end`、`content_types`、`estimated_tokens` 和切片策略。

生命周期归 Java 所有。Python 只返回解析和分类建议，晚到解析/发布 Worker 必须同时匹配状态与 revision，否则以 `STALE_DRAFT_TARGET` / `STALE_PUBLISH_TARGET` 拒绝覆盖。解析失败为 `PARSE_FAILED`，发布 Embedding 失败为 `EMBEDDING_FAILED`；旧 `published_revision` 在新版本成功切换前仍是读侧事实。

上传链路有两个必须同步的限制：Java 接收原文件默认 10 MiB（`KNOWLEDGE_MAX_FILE_BYTES=10485760`）；Agent 的 `/api/knowledge/parse` 接收 Base64 JSON，专用 `KNOWLEDGE_PARSE_MAX_REQUEST_BYTES` 默认 `15029592`，即 Base64 后的 10 MiB 文件再留 1 MiB envelope。其他 Agent 端点仍受 `AGENT_MAX_REQUEST_BYTES=2097152` 限制。解析请求超限返回 `FILE_TOO_LARGE`，调整原文件上限时必须同步调整 parse envelope。

### 13.2 Embedding 与 pgvector

- DashScope `text-embedding-v3`；
- 1024 维；
- `knowledge_document` 保存 `review_status/revision/published_revision`，`knowledge_chunk_draft` 保存审阅草稿，`knowledge_chunk` 保存发布 revision；
- IVFFlat 余弦索引；
- 默认 `ivfflat.probes=10`。

发布时不会修改 `chunk_text`：它和 citation 中的正文仍是解析后的原文。Embedding 输入会确定性添加文档标题、标题路径、页码、可信文件名/`source_code` 和内容类型；keyword 的 `search_text` 还会添加已确认分类。这样提高召回上下文，又不会把装饰性上下文伪装成引用原文。

`source_type` 表示 `after_sales_policy/faq/evidence_requirement` 等业务语义，文件格式使用独立的 `source_format=pdf/markdown/text`。只有 `ingestionSourceType=FILE` 时才从 Java 保留字段读取 file name；`fileName/file_name` 等内部 metadata key 不允许由用户自定义 metadata 伪造。

### 13.3 元数据过滤

Dense 和 keyword 共用同一个 hard filter：只读 `published_revision`，排除禁用和软删，限制当前商家或 `GLOBAL`、`source_type`、`policy_version`、有效期，以及 Chunk 的分类/场景/意图标签。严格命中为空时才按计划放宽 category/scene；非政策知识还可放宽 intent。商家、来源类型、政策版本和有效期不是为了“有结果”就能丢掉的条件。

### 13.4 检索和降级

```text
Query Embedding
  -> pgvector Dense Top20 + pg_trgm Keyword Top20
  -> RRF(k=60) 融合 Top20
  -> 托管 Reranker
  -> 最终 TopK 默认 5，最大 10
```

keyword 使用 `pg_trgm similarity`、`ILIKE` 和标题路径加分，不是 BM25/Elasticsearch；Reranker 是托管服务，不是本地 Cross-Encoder。成功模式为 `hybrid_reranked`、`degraded=false`；未配置、配置错误、队列超时、熔断、网络/超时或非法响应会显式返回 `hybrid_rrf_degraded`、`degraded=true` 并保留 RRF 候选。

Embedding Key 缺失时常见 `lexical_fallback_after_embedding_error`，它说明 PostgreSQL 关键词兜底仍可能有结果，不等于标准链路可用。标准本地链路应加载 `DASHSCOPE_API_KEY`（兼容 `BAILIAN_API_KEY`）、`PGVECTOR_DSN`、`RAG_LAYERED_RETRIEVAL_ENABLED` 和 `RERANK_*`，得到 `hybrid_reranked`。本地 JSON 只用于非政策知识；政策检索在 DSN/Embedding 异常时不能靠 JSON 获得可信资格。

### 13.5 降级结果为什么不能自动批准

可信政策命中要求：

- strict hard filters，且 Dense 与 keyword 双通道都命中同一 Chunk；
- `source_type` 是政策类型，商家、版本和业务发生时间落在有效期内；
- 托管 Reranker 成功，结果达到来源阈值；政策类默认 0.75、凭证类 0.65、FAQ 0.60；
- Hit 有可追踪 citation，至少包含 `source_code` 与 `chunk_id/document_id`；
- 工作流仍会叠加 `RAG_AUTO_APPROVE_MIN_SCORE` 下限、图片一致性、金额、情绪和风险 Guard。

`hybrid_rrf_degraded`、仅 lexical、放宽过滤和本地 JSON 可以辅助回复或转人工，但都不能授权自动批准。可用性降级不能同时降低安全标准。

### 13.6 RAG 评测

仓库保留过一份 18 条历史场景基线，覆盖 3 类商品、6 类售后场景；它按“Top5 至少有一条 scene 匹配”计数，更准确地说是历史 HitRate@5，而不是有完整相关集合的 Recall@5。

局限：

- 样本很小；
- 主要检查元数据和场景覆盖；
- 运行于结构化切片、发布 revision 和托管 Reranker 完成之前，不能证明当前新链路效果；
- 不等于答案正确率；
- 不等于线上真实分布；
- 不能描述为生产召回率。

新链路应重新构建 Gold document/chunk 与无答案、跨商家、过期政策难例，并报告 Recall/MRR/NDCG、两通道候选数、Reranker 降级率、filter violation、citation page/path 覆盖率和发布 revision。

---

## 14. Qwen3-VL 图片审核

`VisionReviewService` 默认使用 `qwen3-vl-plus`，逐张分析类型、清晰度、破损、包装、运单、订单匹配和置信度。

准确说法是“Prompt 要求 JSON，代码手动解析和规范化”，不是正式 JSON Schema/Pydantic 强校验，错误类型输出仍有解析风险。

缓存键结合 Prompt 版本、模型、图片来源哈希和订单上下文；有内存 LRU 和可选 SQLite 缓存，默认 TTL 约 300 秒，不保存图片原始字节。

运行时默认自动批准阈值：

```text
VISION_AUTO_APPROVE_MIN_CONFIDENCE = 0.90
AGENT_AUTO_REFUND_LIMIT = 50
```

同时还要求 Vision 成功、图片和申诉一致、存在可信政策、没有重复证据、高风险或情绪人工优先。模型异常返回不确定并转人工，不能把调用失败理解成“图片没问题”。

当前约 54 张示例图片，35 正、19 负：

- 阈值 0.85：Precision 约 96.88%、Recall 约 88.57%、F1 约 92.54%；
- 运行阈值 0.90：Precision 100%、Recall 约 74.29%、F1 约 85.25%。

它是小规模演示数据，缺少独立多标注者，不是线上图片审核效果。

---

## 15. 情绪识别和会话优先级

情绪输出包括：

```text
emotion_score
confidence
need_human_priority
reason
```

`ChatEmotionAnalysisServiceImpl` 将结果写回消息和会话。客服队列优先级大致包含未回复基础值、情绪分 × 2 和等待时长。风险约为 `HIGH >= 80`、`MEDIUM >= 50`，上升约 20 可作为趋势上升。

只有人工客服 `SERVICE` 消息算人工回复，`ASSISTANT/SYSTEM` 不应掩盖用户仍未得到人工响应。

边界：

- LangGraph 将情绪优先纳入 Guard，高风险时阻止自动批准并转人工；
- `UserChatController` 直接聊天入口仍有“人工、客服、投诉”等关键词逻辑；
- 不能说所有会话都由情绪模型自动转人工。

独立挑战集约 50 条，严格准确率约 94%、Macro-F1 约 94.14%、优先级判断 100%。它仍是小样本、单套规则标注、无双人一致性，不代表生产分布。

---

## 16. 模型可靠性

### 16.1 超时

模型客户端区分连接、读取、写入、连接池和总超时。Kafka Consumer 对整次 Agent 有默认约 20 秒业务超时。

`future.cancel()` 不能强制停止已运行线程。人工兜底和迟到 Agent 可能竞争，所以最终仍靠 Java `reviewRequestId + SQL CAS`。

### 16.2 重试

网络、超时、429、5xx 等可恢复错误做有限重试；认证、参数和非法请求不盲目重试。默认最大约 2 次，指数退避并带抖动。

### 16.3 熔断

`CircuitBreaker` 默认连续失败阈值约 5、恢复窗口约 30 秒。打开后快速失败，恢复期只允许探测请求。熔断保护系统，不提高模型准确率。

### 16.4 Semaphore

Java Gateway 和 Python 模型客户端都有并发限制，分别保护 Java 请求线程、Python 连接和模型配额。

### 16.5 主备模型

远程主模型只在可恢复基础设施错误时降级到 Ollama；认证和参数错误不降级。流式链路中 `OllamaHTTPClient.stream_chat` 当前明确不支持，因此代码中暂未发现可用的流式备用模型降级。

---

## 17. HTTP、SSE、WebSocket 和断连

### 17.1 普通 HTTP

`/agent/chat` 执行情绪、LangGraph、工具、RAG 和消息持久化的完整同步流程。

### 17.2 SSE

`/agent/chat/stream` 是 `StreamingChatService` 直接流式调用模型，输出 start、token、usage、finish、done 等。它不是完整 LangGraph/RAG/工具链，也没有看到与普通接口相同的完整消息持久化，不能说两者完全等价。

Java 用 `SseEmitter` 转发 Python 流。发送失败会退出读取并关闭上游流；Python 处理 BrokenPipe/连接重置。

当前局限：

- Java 侧暂未发现完整的 `onCompletion/onTimeout/onError` 主动取消回调；
- 缺少明确的上游取消句柄；
- 流式链路没有复用普通 Gateway Semaphore。

可优化为显式取消 Token、连接注册表、生命周期回调和资源清理指标。

### 17.3 WebSocket

数据库持久化先完成，事务提交后再广播。广播失败不回滚业务事务。客户端重连后应重新拉取历史，因为数据库消息是事实，WebSocket 只是实时提示。

---

## 18. 测试、离线评测和 CI

### 18.1 Python

当前完整测试结果：

```text
107 passed, 1 skipped, 4 deselected
```

跳过的是需要 Docker/Testcontainers 的 Redis 集成用例，不能说已经通过真实 Redis 验证。

覆盖 LangGraph、Kafka ACK/DLQ/幂等、HTTP 信任边界、RAG、Vision、情绪、LLM 可靠性、Trace 和安全规则。

### 18.2 Java

本地 Maven 构建成功，共发现 65 个测试，其中 17 个因 Docker/Testcontainers 不可用而跳过。不要说“65 个全部通过”。

重要测试方向：

- MySQL 条件更新并发；
- 同一 reviewRequestId 只生效一次；
- 人工处理后迟到 AI 更新 0 行；
- Long ID 对外序列化成字符串；
- DTO 和内部接口契约；
- Kafka/Redis Testcontainers。

### 18.3 前端和 CI

前端当前有少量契约测试，不代表完整 E2E。GitHub Actions 包括 Python、Java、前端构建与契约、uni-app、Nightly smoke；真实 LLM 测试只在有 Secret 时运行。

### 18.4 指标回答模板

> 这是仓库内离线评测，不是线上生产数据。测试集有 X 个样本，正负/分类分布是______；阈值为 X，指标为 X。它主要验证______，局限是规模小、分布不等同线上、标注方式______，所以我把它作为回归基线，不作为生产效果承诺。

---

## 19. Docker、部署和日志排查

Compose 包含 MySQL 8.4、PostgreSQL 16 + pgvector、Redis 7 AOF、Kafka KRaft 单 Broker、Python HTTP、Java、Prometheus 和 Grafana。

它是开发/演示形态。代码中暂未发现：

- Kubernetes/Helm；
- Ingress/TLS；
- 多可用区；
- 正式生产发布编排；
- 独立 Spring Cloud Gateway；
- Compose 自动启动 Kafka Review Consumer。

### 一次 AI 初审失败怎么排查

使用 `trace_id/event_id/ticket_id`：

1. MySQL 是否有工单和 Outbox；
2. Outbox 的状态、retry_count、last_error；
3. Kafka 是否收到相同 event_id；
4. Redis claim 是什么状态；
5. Agent 是否超时、熔断或并发受限；
6. RAG 是否读取当前 `published_revision`，并检查 `mode/degraded/filter_level/fallback_reason`、Dense/Keyword/RRF/Rerank 候选数、Reranker 失败原因；若是 `lexical_fallback_after_embedding_error`，先确认运行进程是否加载 `DASHSCOPE_API_KEY`（或兼容 `BAILIAN_API_KEY`）与 `PGVECTOR_DSN`；
7. Vision 是否成功和置信度多少；
8. Java 回调是否被鉴权或归属校验拒绝；
9. SQL CAS 影响 1 行还是 0 行；
10. offset 是否提交、是否进 DLQ；
11. 人工接管和用户通知是否持久化。

---

## 20. 高频面试问题与回答要点

### 1. 项目最核心的亮点是什么

> 不是技术栈数量，而是把概率性 AI 放在确定性边界内。Java 保持业务所有权，模型只通过受控工具提交结果；异步链路允许重复，再通过 Redis 和 MySQL 幂等；不确定或失败时可人工接管。

### 2. 为什么拆 Java 和 Python

> Java 适合事务、权限和长期业务维护，Python 适合模型生态。拆分增加了网络、一致性和部署成本，所以用内部 Token、DTO、Trace、event_id、超时、Outbox 和幂等治理。

### 3. MySQL 成功但 Kafka 未发送时宕机

> 工单和 Outbox 已在同一事务提交。重启后 Publisher 会重新扫描 `NEW/FAILED`，事件仍可发送。

### 4. Kafka 已成功但 Outbox 状态未更新

> 会再次发送相同 event_id，形成重复。Python Redis claim 减少重复计算，Java reviewRequestId 和 CAS保证业务只生效一次。

### 5. `@Transactional` 为什么不能保证 MySQL 与 offset 原子

> 它们是不同资源，Consumer 还在 Python 进程。项目接受故障窗口，通过至少一次投递和幂等恢复。

### 6. 只有一个 Consumer 为什么还需要 consumer_id

> 单实例也会重启。新旧进程 ID 不同，但使用同一 Group。新进程会收到旧进程未提交的消息，consumer_id、心跳和 stale 用于等待或接管。

### 7. 新鲜 PROCESSING 为什么不能 ACK

> PROCESSING 只证明旧实例 claim 过，不证明 Java 已落库。当前代码 pause 分区、seek 回 offset并等待；进入终态才 ACK，超过 stale 后 CAS 接管。

### 8. 为什么 Java 先查询状态还需要 SQL CAS

> 查询和更新之间可能被人工或另一个回调修改。条件 UPDATE 将检查和写入原子化，影响 0 行就拒绝迟到或重复结果。

### 9. Redis 挂了会不会破坏业务

> 限流 fail-open，状态缓存回源 MySQL；消费幂等降级本地文件但多实例能力下降。最终正确性仍由 Java reviewRequestId、唯一约束和 CAS 保证。

### 10. RAG 命中为什么不能直接批准

> RAG 只是政策证据。自动批准要求已发布 revision、strict hard filters、Dense/Keyword 双通道、托管 Reranker 成功、政策来源阈值和可追踪 citation；工作流还复核商家、版本、有效期、图片一致性以及金额/情绪风险，最终由 Java 生效。任何降级模式都不能自动批准。

### 11. 视觉模型返回 JSON 就可靠吗

> 不可靠。当前是 Prompt JSON加手动解析，不是强 Schema。仍需要类型规范化、阈值、业务 Guard 和人工兜底。

### 12. 模型超时后线程会立即停止吗

> 不一定，`future.cancel()` 不能强杀运行中的线程。业务正确性不能依赖线程取消，要靠 Java 幂等和 CAS。

### 13. SSE 客户端断连怎么释放资源

> 当前发送失败会关闭上游流，Python 也处理 BrokenPipe；但 Java 缺少完整 emitter 回调和取消句柄，这是可优化点。

### 14. 是否实现统一 Gateway

> 有应用内 Agent Gateway，但代码中暂未发现独立 Spring Cloud Gateway。

### 15. 项目有哪些不足

至少说三个：

1. 工单创建缺订单用户归属校验；
2. Compose 未自动启动 Kafka Consumer；
3. Outbox 多实例没有抢占/行锁；
4. `publishOne` 自调用事务风险；
5. 商家人工审核缺强 CAS；
6. SSE 生命周期和统一并发隔离不完整；
7. 流式 Ollama 备用不可用；
8. 离线评测集较小；
9. 单 Broker Compose 不是生产高可用。

---

## 21. 故障题统一分析方法

```text
1. 故障发生在哪两个持久化动作之间
2. 哪个已成功，哪个尚未成功
3. 重启/重试后看到什么状态
4. 会丢、重复、乱序还是覆盖
5. 当前代码如何恢复
6. 还有什么窗口，如何优化和测试
```

### 示例：Java 成功但 ACK 前宕机

> 故障点在 MySQL 提交后、offset 提交前。Kafka 会重投，因此不会直接丢但会重复。Redis 终态在时可以跳过；Redis 不在时可能重跑并回调 Java。因为 event_id 继续作为 reviewRequestId，Java 返回幂等结果，SQL CAS防止二次更新。局限是存在重复计算成本，但不能只靠 Redis 保证正确性。

---

## 22. 答题模板

### 设计题

```text
业务背景：
必须保证的约束：
当前设计：
为什么这样设计：
失败场景：
恢复与幂等：
测试方式：
局限和下一步：
```

### 源码题

```text
入口类/方法：
Service 或工作流：
关键 DB/Redis/Kafka 操作：
事务或状态边界：
异常路径：
测试类和断言：
```

### 指标题

```text
样本数和分布：
评测环境：
阈值：
指标：
指标能说明什么：
指标不能说明什么：
```

### 团队职责

```text
我亲自负责：
对应代码：
关键决策：
解决的具体故障：
其他成员负责：
协作接口：
验收方式：
```

---

## 23. 容易说错的话

| 不建议说 | 更准确的说法 |
|---|---|
| Kafka 保证 Exactly Once | 至少一次投递，通过应用层幂等保证业务结果不重复 |
| Redis 保证最终一致性 | Redis 做短期控制，MySQL 是最终业务事实 |
| `@Transactional` 保证 MySQL/Kafka 原子 | 本地事务只覆盖 DB，Outbox 和幂等负责跨系统恢复 |
| LangGraph State 保存长期状态 | State 是本轮上下文，长期事实在 Java/MySQL |
| RAG 决定退款 | RAG 提供证据，Guard 和 Java 状态机决定能否生效 |
| RAG 是固定 700 字符、20% overlap | 当前是 `structured_recursive_v1`，默认 500/800/150 tokens、6400 字符硬上限，无固定 overlap |
| RRF/Reranker 还没实现 | 当前是 Dense + pg_trgm -> RRF(k=60) -> 托管 Reranker；BM25/ES 和本地 Cross-Encoder 未实现 |
| Qwen3-VL 结构化输出完全可靠 | Prompt JSON + 手动解析，仍需校验和人工兜底 |
| 情绪高就一定自动转人工 | LangGraph 纳入人工优先，直接入口仍有关键词逻辑 |
| 65 个 Java 测试全部通过 | 发现 65 个，17 个在当前环境因 Docker 不可用跳过 |
| 已经是生产高可用部署 | 当前 Compose 是开发/演示形态 |
| 我负责所有模块 | 指出真实负责的类、方法、问题和测试 |

---

## 24. 面试前 30 分钟复习顺序

### 前 5 分钟

- 两分钟项目介绍；
- Java/Python/MySQL/Redis/Kafka/pgvector 边界；
- “AI 辅助业务，不拥有业务”。

### 第 5～12 分钟

画出：

```text
创建工单 → Outbox → Kafka → Redis claim → LangGraph → Java CAS → 通知
```

### 第 12～18 分钟

讲清三个故障：

1. MySQL 成功，Kafka 未发；
2. Kafka 已发，Outbox 未更新；
3. Java 已成功，offset 未提交。

### 第 18～23 分钟

- `event_id/reviewRequestId`；
- 新鲜 PROCESSING 不 ACK；
- stale CAS；
- Java SQL CAS；
- 人工处理后迟到 AI 不覆盖。

### 第 23～27 分钟

- LangGraph 节点和 State；
- RAG 的 Draft/Publish、结构化切片、`hybrid_reranked`/`hybrid_rrf_degraded` 与可信政策门禁；
- Vision 0.90 阈值；
- 情绪人工优先；
- 超时、重试、熔断和 Semaphore。

### 最后 3 分钟

- 指标带样本数和局限；
- 不把 Compose 说成生产高可用；
- 不把未实现的 Gateway、自动 Consumer、订单归属校验说成已完成；
- 被指出问题时先承认代码事实，再给修复和测试。

---

## 25. 推荐继续阅读源码

Java：

- `AfterSalesController`
- `AfterSalesServiceImpl#create`
- `AfterSalesReviewEventServiceImpl`
- `InternalAgentToolsController#submitAiReview`
- `AfterSalesTicketMapper`
- `AiReviewManualHandoffServiceImpl`
- `RedisRateLimiterServiceImpl`
- `AgentGatewayServiceImpl`
- `InternalAgentAuthenticationFilter`
- `ChatWebSocketHandler`

Python：

- `api/kafka_review_consumer.py`
- `api/http_server.py`
- `application/after_sales_workflow.py`
- `application/tool_registry.py`
- `retrieval/pgvector_retriever.py`
- `providers/vision_review_service.py`
- `providers/resilient_llm_runtime.py`
- `agents/emotion_service.py`

数据库与配置：

- `sql/schema.sql`
- `sql/pgvector_schema.sql`
- `src/main/resources/application.yml`
- `python_agent/.env.example`
- `compose.yml`
- `.github/workflows/`

配合阅读：

- [项目全景架构](project-overview.md)
- [源码深挖手册](source-code-deep-dive.md)

---

## 结尾：面试官真正想听什么

面试官通常不关心你能背出多少中间件名词，而是想确认：

1. 你知道业务事实由谁拥有；
2. 你能指出事务边界和失败窗口；
3. 你理解重复投递不可避免，并能设计幂等；
4. 你知道查询后更新为什么仍有并发问题；
5. 你不会把模型输出直接当业务事实；
6. 你能用权限、限流、审计、Trace、超时、重试、熔断和人工接管控制风险；
7. 你能诚实描述测试范围、离线指标和项目不足；
8. 你能从具体类、方法、SQL 和测试解释设计，而不是只背概念。

最好的项目表达不是“这个项目用了很多技术”，而是：

> 我知道每个组件在解决什么故障，也知道它没有解决什么问题。
