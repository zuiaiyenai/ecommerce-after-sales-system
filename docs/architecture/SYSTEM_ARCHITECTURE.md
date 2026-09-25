# 系统架构说明

本文描述当前源码中的边界与调用链。业务事实以 Java 服务和 MySQL 为准；Python Agent 不直接修改业务库。

## 1. 系统总览

```mermaid
flowchart TB
    MINI[微信小程序\nuni-app] -->|JWT + REST / SSE| JAVA[Spring Boot 3 / Java 21]
    STAFF[客服与管理端\nVue 3] -->|JWT + REST / WebSocket| JAVA

    JAVA --> MYSQL[(MySQL\n订单、工单、会话、地址、反馈)]
    JAVA --> REDIS[(Redis\n限流、缓存、短期状态)]
    JAVA -->|Transactional Outbox| KAFKA[Kafka]
    JAVA -->|HTTP| AGENT[Python AfterSalesAgent]
    KAFKA --> CONSUMER[Python Review Consumer]
    CONSUMER --> AGENT

    AGENT --> PG[(PostgreSQL + pgvector\n知识与向量)]
    AGENT --> OLLAMA[Ollama\n文本、Embedding、Vision]
    AGENT --> RERANK[TEI Reranker]
    AGENT -->|受控工具调用| JAVA

    JAVA --> PROM[Prometheus]
    AGENT --> PROM
    CONSUMER --> PROM
    PROM --> GRAFANA[Grafana]
```

### 组件职责

| 组件 | 当前职责 | 数据边界 |
| --- | --- | --- |
| 微信小程序 | 登录、商品、订单、售后、客服、地址、资料与反馈 | 不把本地 Storage 当作业务事实 |
| Spring Boot | 鉴权、用户隔离、订单/工单状态机、消息持久化、Agent 网关 | 唯一业务写入口 |
| Python Agent | 对话编排、RAG、情绪与证据分析、工具规划 | 通过 Java 内部 API 读写业务状态 |
| MySQL | 业务记录、审计、Outbox、地址、反馈 | 长期业务事实 |
| pgvector | 已发布知识、切片、Embedding 与检索元数据 | 不保存订单和工单 |
| Redis | 限流、消费幂等、短期缓存 | 不承担长期业务持久化 |
| Kafka | 异步审核事件与失败隔离 | 不作为最终状态来源 |

## 2. 业务架构

```mermaid
flowchart LR
    ORDER[创建订单] --> RECEIVE[确认收货]
    RECEIVE --> APPLY[申请售后]
    APPLY --> TICKET[创建售后工单]
    TICKET --> OUTBOX[写入 Outbox]
    OUTBOX --> REVIEW[AI 正式审核]
    REVIEW --> DECISION{确定性 Gate}
    DECISION -->|证据充分| RESULT[Java 落库审核结果]
    DECISION -->|证据不足| EVIDENCE[请求补充凭证]
    DECISION -->|不确定或故障| HUMAN[转人工]
    EVIDENCE --> REVIEW
    RESULT --> CHAT[客服会话与通知]
    HUMAN --> CHAT
    CHAT --> EVALUATE[用户评价]
```

地址与反馈属于同一用户域：JWT 经 `@CurrentUserId` 解析身份，地址 SQL 使用 `id + user_id` 校验所有权；反馈提交写入 MySQL，管理员查询再次校验 `ADMIN` 身份。

## 3. 数据流

```mermaid
sequenceDiagram
    actor U as 小程序用户
    participant J as Spring Boot
    participant M as MySQL
    participant K as Kafka
    participant A as Python Agent
    participant P as pgvector / Model

    U->>J: JWT + 售后申请
    J->>J: 校验订单归属、状态、参数
    J->>M: 同一事务写工单、会话、Outbox
    J-->>U: 返回持久化结果
    J->>K: 定时发布 Outbox 事件
    K->>A: 至少一次投递审核事件
    A->>J: 获取最新可信工单上下文
    A->>P: 政策检索与凭证分析
    A->>A: Workflow + deterministic gate
    A->>J: 提交审核/补证/人工建议
    J->>M: 校验版本与幂等后落库
    J-->>U: WebSocket/历史重载展示结果
```

## 4. AI 调用链

```mermaid
flowchart TD
    INPUT[用户问题或审核事件] --> CONTEXT[Java 可信上下文]
    CONTEXT --> AGENT[AfterSalesAgent]
    AGENT --> INTENT{场景路由}
    INTENT -->|普通咨询| TOOLS[受控工具注册表]
    INTENT -->|正式审核| SKILL[Formal Review Skill]
    TOOLS --> JAVA[Java Internal API]
    SKILL --> POLICY[Policy Retrieval Workflow]
    SKILL --> EVIDENCE[Evidence Review Workflow]
    POLICY --> RAG[Dense + Keyword + RRF + Reranker]
    EVIDENCE --> VISION[Vision Provider]
    RAG --> GATE[Deterministic Gate]
    VISION --> GATE
    GATE --> JAVA
```

模型只生成建议或工具计划。Java 校验用户/商家归属、状态和幂等键后才能修改最终业务状态。

## 5. 故障降级链路

```mermaid
flowchart TD
    CALL[调用 Agent / Embedding / Reranker / Vision] --> OK{调用成功?}
    OK -->|是| VALID{政策、证据、版本与置信度满足 Gate?}
    VALID -->|是| APPLY[Java 应用结果]
    VALID -->|否，缺证据| MORE[请求补充凭证]
    VALID -->|否，其他原因| HUMAN[人工审核/人工客服]
    OK -->|否| CLASSIFY[分类超时、不可用或结果异常]
    CLASSIFY --> RETRY{在有限重试范围内?}
    RETRY -->|是| CALL
    RETRY -->|否| HUMAN
    HUMAN --> PERSIST[Java 持久化消息与会话状态]
    MORE --> PERSIST
    APPLY --> PERSIST
```

Kafka Consumer 使用 Redis 认领事件并支持过期接管；达到重试上限后进入 DLQ 或人工处理。模型不可用时，前端仍可读取已持久化消息和会话状态。

## 6. 一致性与安全

- 售后创建与 Outbox 写入同一 MySQL 事务，避免业务成功但事件丢失。
- 事件以 `event_id`、审核请求 ID 和业务版本做幂等与陈旧结果判断。
- 地址默认唯一由事务内先清除旧默认值，并由数据库生成列唯一索引兜底。
- 小程序用户 ID 来自服务端 JWT，不接收前端传入的 `userId` 作为权限依据。
- Agent 内部接口使用共享内部 Token；日志和指标避免记录密钥及自由文本敏感值。
- Prometheus 采集 Java、Agent 和 Consumer 指标，Grafana 展示延迟、错误、降级、Outbox、DLQ 与人工接管。

## 7. 相关源码

- Java API：`src/main/java/com/ecommerce/aftersales/controller/`
- 业务服务：`src/main/java/com/ecommerce/aftersales/service/`
- Agent：`python_agent/after_sales_agent/`
- 数据库迁移：`src/main/resources/db/migration/`
- 可观测性：`observability/`
- 小程序：`frontend/uniapp/`
