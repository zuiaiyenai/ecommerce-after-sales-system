# Ecommerce After-Sales System

面向电商售后场景的智能客服与工单协同系统。项目覆盖用户咨询、售后申请、凭证审核、知识检索、AI 辅助决策、人工接管、商家运营和链路监控，并通过 Java 业务内核、Python LangGraph Agent、事件驱动架构与分层 RAG 保证业务状态可控、AI 结论可解释、分布式失败可恢复。

## 一、总体架构

```mermaid
flowchart TB
    subgraph Client["交互层"]
        U["用户端<br/>uni-app / 微信小程序"]
        S["商家客服端<br/>Vue 3"]
        O["管理员端<br/>Vue 3"]
    end

    subgraph Java["业务层：Java Spring Boot"]
        API["REST API / WebSocket"]
        AUTH["认证、权限、商家隔离"]
        BIZ["订单、售后、会话、知识管理"]
        FSM["业务状态机与事务"]
        IAPI["Agent Internal APIs"]
        OUTBOX["Transactional Outbox"]
    end

    subgraph Agent["智能层：Python LangGraph"]
        CHAT["会话 ReAct Agent"]
        REVIEW["正式审核 Multi-Agent"]
        POLICY["Policy Sub-Agent"]
        EVIDENCE["Evidence Sub-Agent"]
        GATE["Deterministic Gate"]
        TOOL["受控工具注册表"]
    end

    subgraph Data["数据与基础设施"]
        MYSQL[("MySQL<br/>业务事实来源")]
        PG[("PostgreSQL + pgvector<br/>知识检索来源")]
        REDIS[("Redis<br/>幂等、缓存、限流")]
        KAFKA["Kafka<br/>异步审核事件"]
        MODEL["LLM / Embedding / Reranker / Vision"]
    end

    subgraph Observe["可观测性"]
        METRICS["Prometheus"]
        DASH["Grafana"]
        TRACE["Trace ID / 结构化日志"]
    end

    U --> API
    S --> API
    O --> API
    API --> AUTH --> BIZ --> FSM
    FSM --> MYSQL
    FSM --> OUTBOX --> KAFKA
    API --> CHAT
    KAFKA --> REVIEW
    REVIEW --> POLICY
    REVIEW --> EVIDENCE
    POLICY --> PG
    POLICY --> MODEL
    EVIDENCE --> MODEL
    CHAT --> TOOL
    REVIEW --> TOOL
    TOOL --> IAPI --> BIZ
    Java --> REDIS
    Agent --> REDIS
    Java --> METRICS
    Agent --> METRICS
    METRICS --> DASH
    Java --> TRACE
    Agent --> TRACE
```

### 核心职责边界

| 模块 | 拥有的职责 | 明确不做 |
| --- | --- | --- |
| Java 业务服务 | 鉴权、权限、订单、售后工单、会话消息、事务、状态机、最终审核结果 | 不把业务状态交给模型直接修改 |
| Python Agent | LangGraph 编排、意图理解、工具规划、RAG、视觉审核、风险分析、回复生成 | 不直写 MySQL，不拥有最终业务状态 |
| 前端 | 用户交互、消息渲染、状态展示和失败时的短期交互兜底 | 不把本地状态当作会话或工单事实 |
| MySQL | 业务事实与审计记录 | 不保存向量检索运行状态 |
| PostgreSQL + pgvector | 已发布知识、Chunk、Embedding 和检索元数据 | 不保存订单、工单或聊天业务状态 |
| Redis | 消费幂等、短期状态、缓存和限流 | 不承担长期业务持久化 |
| Kafka | 事件投递、异步解耦和故障隔离 | 不作为业务最终状态来源 |

## 二、完整业务链路

```mermaid
flowchart LR
    START["用户进入商品、订单或售后入口"] --> RESOLVE["Java 解析用户、商家、订单、工单与 sessionId"]

    RESOLVE --> TYPE{"请求类型"}

    TYPE -->|普通咨询| MSG["Java 持久化用户消息"]
    MSG --> CHAT["会话 ReAct Agent"]
    CHAT --> CTX["读取订单、工单、会话与知识"]
    CTX --> REPLY["生成建议或触发人工接管"]
    REPLY --> SAVE["Java 持久化 AI / 系统消息"]
    SAVE --> SYNC["用户端与商家端按 sessionId 重载历史"]

    TYPE -->|提交售后| APPLY["Java 校验订单归属、申请条件与幂等"]
    APPLY --> TX["同一事务创建工单、会话快照与 Outbox"]
    TX --> MYSQL[("MySQL")]
    TX --> PUB["Outbox Publisher"]
    PUB --> KAFKA["Kafka Review Request"]
    KAFKA --> CLAIM["Redis event_id 幂等认领"]
    CLAIM --> MULTI["正式审核 Multi-Agent"]
    MULTI --> GATE{"确定性 Gate"}
    GATE -->|满足可信政策、凭证和置信度| APPROVE["提交 APPROVE 建议"]
    GATE -->|缺少必要凭证| MORE["请求补充凭证"]
    GATE -->|风险、不确定或服务失败| HUMAN["提交 MANUAL_REVIEW_REQUIRED"]
    APPROVE --> JAVA_APPLY["Java 校验状态与 review_request_id"]
    MORE --> JAVA_APPLY
    HUMAN --> JAVA_APPLY
    JAVA_APPLY --> RESULT["MySQL 保存最终结果并更新会话快照"]
    RESULT --> NOTICE["WebSocket / 历史消息通知两端"]

    TYPE -->|商家处理| STAFF["Java 校验商家权限"]
    STAFF --> ACTION["回复会话、审核工单、管理订单商品"]
    ACTION --> RESULT
```

这条链路有两个关键约束：

1. 所有写操作最终回到 Java，由 Java 校验用户归属、商家权限、当前状态和幂等键。
2. 前端展示以 Java 持久化后的结果为准；发送消息后优先重新加载会话历史，而不是只在本地追加。

## 三、Agent 体系

系统包含两类相互隔离的运行时：

| Agent | 触发方式 | 目标 | 是否可直接形成业务结果 |
| --- | --- | --- | --- |
| 会话 ReAct Agent | 用户实时咨询 | 理解问题、选择工具、查询事实、生成回复或转人工 | 否，消息与接管结果必须经 Java 持久化 |
| 正式审核 Supervisor | Kafka 售后审核事件 | 编排政策与凭证专家，综合结构化结论 | 否，只生成提案 |
| Policy Sub-Agent | Supervisor 派发 | 检索可信售后政策，判断政策覆盖与适用性 | 否，输出 PolicyAssessment |
| Evidence Sub-Agent | Supervisor 派发 | 审核图片凭证，识别一致性、缺失项和风险 | 否，输出 EvidenceAssessment |
| Deterministic Gate | 专家结果汇合后执行 | 用确定性规则决定自动通过、补证或人工审核 | 只选择提交动作，最终仍由 Java 落库 |

### 3.1 会话 ReAct Agent 子图

```mermaid
flowchart TD
    A0["receive_message<br/>标准化用户、会话、订单与工单上下文"] --> A1["classify_or_plan<br/>LLM Function Calling + 规则护栏"]
    A1 --> ROUTE{"route_after_plan"}

    ROUTE -->|调用工具| A2["tool_call<br/>校验工具名、参数、权限与重复调用"]
    ROUTE -->|需要人工| A6["human_handoff"]
    ROUTE -->|无需工具| A7["final_reply"]

    A2 --> A3["observe_tool_result<br/>统一 success / error_category / observation"]
    A3 --> A4["decide_next<br/>结合工具结果与最大步数判断下一步"]
    A4 --> NEXT{"route_after_decision"}

    NEXT -->|继续查询或执行| A2
    NEXT -->|失败、风险或不确定| A6
    NEXT -->|信息充分| A7

    A6 --> A7
    A7 --> END["END<br/>通过 Java append_chat_message 持久化"]
```

会话 Agent 的工具边界包括：

- 查询用户订单、订单详情、物流和已有售后工单
- 查询会话历史和售后知识
- 获取工单可信上下文
- 提交受保护的 AI 审核结果
- 请求人工接管
- 通过 Java 追加聊天消息

工具执行被拆分为“调用—观察—决策”，便于统一处理超时、参数错误、权限拒绝、空结果和可恢复故障。循环受最大步数、重复工具调用检测和终态动作校验约束。

### 3.2 正式审核 Multi-Agent 总图

```mermaid
flowchart TD
    F0["load_trusted_context<br/>通过 Java 查询最新工单"] --> C0{"上下文可用且状态仍可审核？"}
    C0 -->|否| FM["submit_manual_review"]
    C0 -->|是| F1["validate_review_inputs<br/>检查问题描述与图片凭证"]

    F1 --> C1{"输入是否完整？"}
    C1 -->|否| FE["request_missing_evidence"]
    C1 -->|是| F2["supervisor_plan<br/>生成专家任务与 policy_query"]

    F2 --> P0
    F2 --> E0

    subgraph PolicyGraph["Policy Sub-Agent Graph"]
        P0["receive_task"] --> P1["retrieve_policy"]
        P1 --> P2["observe_policy_result"]
        P2 --> P3{"可信政策是否充分？"}
        P3 -->|是| P7["finalize_policy_assessment"]
        P3 -->|否且允许改写| P4["rewrite_policy_query"]
        P4 --> P5{"产生有效候选查询？"}
        P5 -->|是| P6["retrieve_policy_multi"]
        P6 --> P8["observe_rewritten_policy_result"]
        P8 --> P7
        P5 -->|否| P7
        P3 -->|基础设施失败或已达上限| P7
    end

    subgraph EvidenceGraph["Evidence Sub-Agent Graph"]
        E0["receive_task"] --> E1{"附件与任务是否合法？"}
        E1 -->|否| E3["assess_evidence<br/>输出缺失项或失败类别"]
        E1 -->|是| E2["review_evidence<br/>视觉模型审核"]
        E2 --> E3
    end

    P7 --> S0["review_supervisor<br/>校验 context_version 并综合专家输出"]
    E3 --> S0
    S0 --> CONF["deterministic confidence<br/>模型置信度 + 政策 + 凭证校准"]
    CONF --> G0["deterministic_gate"]
    G0 --> DECISION{"Gate Action"}
    DECISION -->|SUBMIT_REVIEW| FS["submit_review"]
    DECISION -->|REQUEST_EVIDENCE| FE
    DECISION -->|MANUAL_REVIEW| FM

    FS --> END1["END"]
    FE --> END1
    FM --> END1
```

Supervisor 不把完整业务上下文随意交给子 Agent，而是构造最小化任务：

- Policy Agent 只接收政策检索需要的商品、类目、售后类型、商家、政策版本和业务时间。
- Evidence Agent 只接收图片审核需要的问题、商品、订单、工单与附件。
- 两个子 Agent 都携带相同的 `context_version`。汇合时版本不一致会直接转人工，防止使用不同时间点的事实合成结论。
- `task_id` 由 `review_request_id + specialist + context_version` 计算，便于追踪与幂等分析。

### 3.3 Supervisor 决策子图

```mermaid
flowchart TD
    S1["Supervisor Plan<br/>至少派发 POLICY；有附件时派发 EVIDENCE"] --> S2["并行等待结构化专家结果"]
    S2 --> S3{"context_version 一致？"}
    S3 -->|否| M1["MANUAL_REVIEW<br/>上下文版本冲突"]
    S3 -->|是| S4["综合 PolicyAssessment + EvidenceAssessment"]
    S4 --> S5["apply_deterministic_confidence"]
    S5 --> G1{"确定性 Gate"}

    G1 -->|凭证服务失败或发现风险| M2["MANUAL_REVIEW"]
    G1 -->|缺少必要凭证| E1["REQUEST_EVIDENCE"]
    G1 -->|政策不可信或版本不匹配| M3["MANUAL_REVIEW"]
    G1 -->|置信度低于阈值| M4["MANUAL_REVIEW"]
    G1 -->|自动审核关闭| M5["MANUAL_REVIEW"]
    G1 -->|APPROVE + 可视觉核验 + 凭证一致| A1["SUBMIT_REVIEW"]
    G1 -->|其他条件未满足| M6["MANUAL_REVIEW"]

    A1 --> J["Java Internal API"]
    E1 --> J
    M1 --> J
    M2 --> J
    M3 --> J
    M4 --> J
    M5 --> J
    M6 --> J
    J --> DB[("MySQL 最终状态")]
```

这里的 LLM 只生成 `ReviewProposal`，真正的 Gate 是代码规则。即使模型提出自动通过，只要政策、凭证、版本、置信度或功能开关任一条件不满足，系统就不会自动通过。

### 3.4 Policy Sub-Agent 与 Agentic RAG

```mermaid
flowchart TD
    Q0["原始问题 + TrustedCaseContext"] --> Q1["构建自然语言 policy_query"]
    Q1 --> F0["构建结构化过滤计划<br/>merchant / category / scene / intent / source / policy_version / as_of_time"]

    F0 --> E0["DashScope text-embedding-v3"]
    F0 --> K0["PostgreSQL pg_trgm / 关键词召回"]
    E0 --> V0["pgvector Dense Recall"]
    V0 --> R0["RRF 融合候选"]
    K0 --> R0
    R0 --> RR0["qwen3-rerank 精排"]
    RR0 --> T0["阈值过滤、引用整理与可信政策判定"]

    T0 --> O0["observe_policy_result"]
    O0 --> C0{"可信、未降级且覆盖充分？"}
    C0 -->|是| A0["生成 PolicyAssessment"]
    C0 -->|基础设施失败| A1["标记不可信 / 失败<br/>交由 Gate 转人工"]
    C0 -->|知识缺口且首次检索| W0["LLM 仅评估覆盖并改写查询"]

    W0 --> W1["最多 3 个互补自然语言查询<br/>禁止修改结构化过滤条件"]
    W1 --> MQ0["并行多查询检索"]
    MQ0 --> MQ1["每个查询：Dense + Keyword + RRF"]
    MQ1 --> MQ2["跨查询 RRF 融合"]
    MQ2 --> MQ3["按候选查询分别 Rerank"]
    MQ3 --> MQ4["去重并取最高 rerank_score"]
    MQ4 --> T1["再次执行阈值、引用和可信政策判定"]
    T1 --> A0

    E0 -. Embedding 失败 .-> D0["lexical / local fallback"]
    RR0 -. Reranker 失败 .-> D1["hybrid_rrf_degraded"]
    D0 --> D2["返回降级模式与 failure_reason"]
    D1 --> D2
    D2 --> A1
```

Agentic RAG 不是让模型自由搜索，而是“模型判断知识覆盖、代码控制检索边界”：

1. 首次检索使用结构化硬过滤，避免跨商家、跨政策版本或跨生效时间召回。
2. Dense 与 Keyword 召回通过 RRF 融合，再由 Reranker 精排。
3. 模型只能判断覆盖是否充分，并生成最多 3 个互补查询；不能更改商家、政策版本、时间等过滤条件。
4. 多查询结果再次融合和精排，并保留文档、Chunk 与来源引用。
5. `trusted_policy_eligible`、`filter_level`、`reranker_succeeded`、`no_answer` 和 `failure_reason` 会进入结构化评估。
6. 降级召回可以用于提示和诊断，但正式审核不会把降级结果当成可信政策自动通过。

### 3.5 Evidence Sub-Agent 子图

```mermaid
flowchart TD
    E0["EvidenceTask"] --> E1["校验 task_id、ticket_id、order_id、context_version"]
    E1 --> C0{"是否存在有效附件？"}
    C0 -->|否| E5["生成缺失凭证列表"]
    C0 -->|是| E2["调用 Vision Review Tool"]
    E2 --> E3["统一图片来源与序列化"]
    E3 --> E4["识别可视问题、证据类别、风险信号与核验限制"]
    E4 --> C1{"结果是否可靠？"}
    C1 -->|视觉服务失败| E6["success=false<br/>交由 Gate 转人工"]
    C1 -->|证据不足| E5
    C1 -->|完成| E7["EvidenceAssessment"]

    E5 --> E7
    E7 --> OUT["输出：visual_verifiable、evidence_consistent、visual_confidence、satisfied_evidence、missing_evidence、risk_signals"]
```

Evidence Agent 不针对单个商品或某张截图写死规则，而是输出通用的证据类别、可观察问题、缺失项、风险信号和视觉能力边界。功能异常无法仅凭静态图片验证时，会要求补充更合适的凭证或转人工。

## 四、异步审核、幂等与故障恢复

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant Java as Java 业务服务
    participant MySQL as MySQL
    participant Outbox as Outbox Publisher
    participant Kafka as Kafka
    participant Redis as Redis
    participant Agent as Python Multi-Agent
    participant Pg as pgvector
    participant Model as LLM / Vision
    participant Staff as 商家客服端

    User->>Java: 提交售后申请
    Java->>Java: 校验订单归属、状态与重复请求
    Java->>MySQL: 同一事务写入工单、消息、会话快照、Outbox
    Java-->>User: 立即返回工单已创建

    loop 定时发布 NEW / FAILED
        Outbox->>MySQL: 查询待发布事件
        Outbox->>Kafka: 以 event_id 为 Key 发布
        Kafka-->>Outbox: 发布确认
        Outbox->>MySQL: 标记 PUBLISHED
    end

    Kafka->>Agent: after_sales.review.request
    Agent->>Redis: SET NX 认领 event_id
    alt 已完成的重复事件
        Redis-->>Agent: terminal + should_ack
        Agent->>Kafka: 提交 Offset
    else 正在处理
        Redis-->>Agent: PROCESSING
        Agent->>Kafka: 暂停分区并保留 Offset
    else 首次认领或过期接管
        Redis-->>Agent: claimed + attempt
        Agent->>Java: 查询最新可信工单上下文
        Java->>MySQL: 读取工单、订单、附件与版本
        Java-->>Agent: TrustedCaseContext
        par Policy Sub-Agent
            Agent->>Pg: 混合检索与过滤
            Agent->>Model: 查询覆盖评估 / Rerank
        and Evidence Sub-Agent
            Agent->>Model: 视觉凭证审核
        end
        Agent->>Agent: Supervisor 汇总 + Deterministic Gate
        Agent->>Java: 提交审核、补证或人工审核动作
        Java->>MySQL: 幂等校验并持久化最终状态与通知消息
        Java-->>Agent: APPLIED / STALE / IDEMPOTENT
        Agent->>Redis: 标记 COMPLETED / EVIDENCE_REQUIRED / MANUAL_REQUIRED
        Agent->>Kafka: 提交 Offset
        Java-->>Staff: WebSocket / 会话刷新
    end
```

### 失败状态流

```mermaid
stateDiagram-v2
    [*] --> NEW: 事务写入 Outbox
    NEW --> PUBLISHED: Kafka 发布成功
    NEW --> FAILED: 发布失败
    FAILED --> PUBLISHED: 有限重试成功
    FAILED --> DEAD: 超过最大重试
    DEAD --> MANUAL_REQUIRED: Java 持久化人工审核兜底

    PUBLISHED --> PROCESSING: Redis 幂等认领
    PROCESSING --> COMPLETED: 审核结果成功落库
    PROCESSING --> EVIDENCE_REQUIRED: 已持久化补证请求
    PROCESSING --> MANUAL_REQUIRED: Agent 失败但人工兜底成功
    PROCESSING --> FAILED_CONSUME: Agent 与人工兜底均失败
    FAILED_CONSUME --> DLQ: 发布死信并提交 Offset
    DLQ --> MANUAL_REQUIRED: Java DLQ Consumer 幂等重放人工接管
```

可靠性策略：

- `event_id` 同时作为 Kafka Key、Redis 消费幂等键和 Java `review_request_id`。
- Redis 使用带 TTL 的 `PROCESSING` 状态和心跳续期；崩溃后允许过期接管。
- 终态重复事件直接 ACK；仍在处理的重复事件不推进 Offset。
- Agent 异常先尝试通过 Java 持久化人工审核；只有人工兜底也失败才进入 DLQ。
- Outbox 发布耗尽重试时不能假装成功，必须把工单转入可见的人工处理状态。
- Trace ID 从 Java、Outbox、Kafka、Agent 工具调用一直贯穿到最终落库。

## 五、核心功能

### 用户侧

- 用户注册、登录、商品浏览、下单与订单查询
- 退款、退货等售后申请与处理进度跟踪
- 图片或文件形式的售后凭证上传与补充
- AI 与人工客服共享同一会话历史
- 售后状态、补证请求和人工接入通知同步展示

### 商家与管理员侧

- 按 `merchantCode` 隔离订单、商品、售后工单和会话
- 根据未回复状态、情绪风险、等待时间和最近活动生成队列优先级
- 统一渲染文本、图片和文件消息
- 展示 AI 建议、置信度、风险原因、证据缺口和审核轨迹
- 管理知识文档的草稿、发布、版本和检索元数据
- 查看 Agent 请求量、延迟、错误、降级、Outbox、DLQ 和人工转接指标

### AI 能力

- 意图识别、问题分类、情绪与风险分析
- 会话、订单、工单、商品与商家策略上下文组装
- 原生 Function Calling 与受控工具执行
- Agentic RAG 查询覆盖评估与多查询改写
- Dense、Keyword、RRF、Reranker 分层检索
- 图片凭证审核、风险识别与能力边界说明
- 多 Agent 正式审核、确定性 Gate 与人工兜底
- 离线安全评测、受控 Multi-Agent 评测和视觉基线评测

## 六、设计思想

1. **AI 辅助业务，不拥有业务**
   Agent 负责理解、检索、分析和建议；订单、工单、权限、事务和最终状态由 Java 控制。

2. **确定性规则约束概率模型**
   身份、金额、时效、状态机、可信政策资格、证据要求和自动审核条件写在代码中，模型输出不能绕过规则。

3. **最小上下文与最小工具权限**
   Supervisor 只向子 Agent 派发完成任务必需的数据；Agent 只能调用注册工具，不能直接访问业务数据库。

4. **事实来源唯一**
   MySQL 保存业务事实，pgvector 保存知识，Redis 保存短期控制状态，Kafka 传递事件，避免多份状态相互冲突。

5. **先持久化，再通知**
   工单、消息和审核结果先由 Java 事务落库，再通过 WebSocket 或历史重载同步给前端。

6. **异步解耦与幂等恢复**
   耗时 AI 审核不阻塞用户提交；Outbox、Kafka、Redis 和 Java 幂等共同处理重复投递与局部故障。

7. **失败时优先保证用户可继续**
   模型不确定、证据不足、政策不可信或外部服务异常时，系统明确补证或转人工，不进入无限推理和重试。

8. **检索质量优先于看似有答案**
   降级检索、Reranker 失败、政策版本不匹配或无可信引用时宁可拒绝自动审核，也不把低质量召回包装成确定结论。

9. **全链路可观测与可评测**
   节点耗时、工具结果、检索模式、置信度拆分、幂等状态、DLQ 和人工接管都有结构化记录和指标。

## 七、技术栈

| 层次 | 技术 |
| --- | --- |
| 业务后端 | Java 21、Spring Boot、MyBatis-Plus、Spring Security |
| AI 编排 | Python、LangGraph、LLM Function Calling |
| 模型能力 | DashScope LLM、text-embedding-v3、qwen3-rerank、视觉模型 |
| 知识检索 | PostgreSQL、pgvector、pg_trgm、RRF、Reranker |
| 数据与消息 | MySQL、Redis、Kafka、Transactional Outbox |
| 用户端 | uni-app、Vue 3、微信小程序 |
| 商家端 | Vue 3、Vite |
| 可观测性 | Prometheus、Grafana、Trace ID、结构化日志 |
| 部署 | Docker Compose |

## 八、项目结构

```text
.
├─ src/                         # Java 业务服务
├─ python_agent/                # Python LangGraph Agent
│  └─ after_sales_agent/
│     ├─ api/                   # HTTP 与 Kafka 入口
│     ├─ application/           # 会话、正式审核、RAG 与工具编排
│     ├─ providers/             # LLM、Embedding、Reranker、Vision
│     ├─ retrieval/             # pgvector、关键词、RRF 与过滤
│     └─ infra/                 # Redis 幂等、指标、Trace
├─ frontend/
│  ├─ uniapp/                   # 用户端小程序
│  └─ staff-auth-test-ui/       # 商家客服端与管理员端
├─ sql/                         # MySQL、pgvector 脚本与迁移
├─ observability/               # Prometheus / Grafana 配置
├─ tools/                       # 评测、审计和压测工具
├─ compose.yml                  # 本地完整链路编排
└─ Dockerfile                   # Java 服务镜像
```

## 九、快速启动

准备本地配置后，在仓库根目录运行：

```powershell
docker compose up -d --build
docker compose ps
```

主要地址：

- Java API：`http://127.0.0.1:8080/api`
- Java 健康检查：`http://127.0.0.1:8080/api/actuator/health`
- Python Agent：仅在 Compose 容器网络暴露 `8000`
- Grafana：按 `compose.yml` 的端口配置访问

用户端和商家端分别进入 `frontend/uniapp` 与 `frontend/staff-auth-test-ui` 安装依赖并启动。

## 十、配置安全

真实密钥、数据库密码和本机环境文件不应提交。项目通过环境变量或 Git 忽略的本地配置提供：

- Java 数据源、JWT、Kafka、Redis 和内部 Agent 鉴权配置
- Python LLM、视觉模型、Embedding、Reranker 与 pgvector 配置
- 前端不同环境的 API 地址
- Docker Compose 的本地变量

仓库只保留可公开的示例配置，运行日志、README 和提交记录不得输出真实凭据。
