# 正式售后审核独立 Subagent 上下文设计

## 背景

当前 `FormalReviewGraph` 使用一个共享的 `FormalReviewState` 并行执行
`policy_agent` 和 `evidence_agent`。两个节点虽然只把部分字段传给领域
Specialist，但节点函数仍能读取父图的完整 State，并且两个 Specialist
共用通用 `AgentToolRegistry`。这种设计实现了 Prompt 层面的软隔离，
没有实现输入和工具权限层面的硬隔离。

本次改造把 Policy 与 Evidence 变成父图派生的独立 Subagent：父图只发送
最小任务信封，每个 Subagent 使用自己的私有 State、执行图和工具端口，
完成后只返回结构化结果。共享父图继续负责调度、汇总、确定性 Gate 和
Java 提交。

## 目标

1. Policy Subagent 和 Evidence Subagent 不接收 `FormalReviewState` 或完整
   `TrustedCaseContext`。
2. 每个 Subagent 从全新的私有 State 开始执行，不继承父图的 messages、
   scratchpad、工具轨迹或另一个专家的结果。
3. Policy Subagent 只能检索知识；Evidence Subagent 只能调用视觉审核。
4. Subagent 只返回有版本标识的结构化结果，不返回自由形式的内部推理。
5. 父图继续并行执行两个专家，并在汇总前校验 `context_version`。
6. Python 只产生审核建议；Java 继续负责权限、幂等、状态机和 MySQL
   最终落库。
7. 保持 Kafka 事件、Java 内部 API 和现有正式审核响应契约兼容。

## 非目标

- 不把专家拆成独立部署的微服务或 Kafka Consumer。
- 不引入新的数据库、消息主题或 LangGraph 长期 Checkpointer。
- 不让 Subagent 自由创建其他 Agent。
- 不把确定性 Gate 改为 LLM 判断。
- 不在本次改造中增加 Emotion 或 Handoff Summary 正式审核节点。
- 不改变普通 `/api/chat` 的 `AgenticRagChatService`。

## 方案比较

### 方案 A：只增加最小输入 DTO

父图构造 `PolicyTask` 和 `EvidenceTask`，但继续直接调用普通 Python
方法。改动最小，也能防止大部分字段误传，但没有独立的子图生命周期和
私有执行 State。

### 方案 B：进程内独立 LangGraph Subagent

Policy 和 Evidence 各自拥有独立的 `StateGraph`。父图创建全新的任务
对象并调用子图，子图内部只有该领域所需字段和工具结果。完成后返回
结构化 Assessment。

这是本次采用的方案。它提供与“新上下文执行后向父 Agent 返回”相同的
隔离语义，同时保留现有进程内并行、Trace 和部署方式。

### 方案 C：独立进程或服务

每个专家通过 HTTP/Kafka 独立部署。隔离和扩容能力最强，但需要处理
额外的投递幂等、超时、版本协商、部署、监控和部分结果恢复。当前只有
两个边界清晰的专家，没有足够业务收益支撑这项复杂度。

## 总体架构

```text
Kafka review.request
        |
        v
FormalReviewGraph.load_trusted_context
        |
        v
SupervisorPlan
        |
        +-------------------------------+
        |                               |
        v                               v
PolicyTask                         EvidenceTask
        |                               |
        v                               v
PolicySubagentGraph               EvidenceSubagentGraph
private state + policy tools      private state + vision tools
        |                               |
        v                               v
PolicyAssessment                  EvidenceAssessment
        |                               |
        +---------------+---------------+
                        |
                        v
             context_version validation
                        |
                        v
               Review Supervisor
                        |
                        v
               Deterministic Gate
                        |
          +-------------+--------------+
          |             |              |
        APPROVE    REQUEST_EVIDENCE   MANUAL
          |             |              |
          +-------------+--------------+
                        |
                        v
                 Java internal API
                        |
                        v
                 Java/MySQL final state
```

## 任务信封

### 公共元数据

两个任务都携带：

- `task_id`：由 `review_request_id + specialist + context_version` 稳定派生。
- `trace_id`：用于跨父图、子图和工具调用关联 Trace。
- `review_request_id`：正式审核请求幂等标识。
- `ticket_id`：业务对象标识，只用于审计和必要工具参数。
- `context_version`：Java 可信上下文版本。

### PolicyTask

Policy Subagent 只能接收：

- 用户问题或工单问题描述
- 商家编码
- 商品名称和分类
- 售后类型
- 政策版本
- 业务生效时间
- Supervisor 生成的政策查询
- 公共元数据

它不接收图片、完整工单 DTO、会话历史、Evidence 结果、提交工具或父图
工具轨迹。

### EvidenceTask

Evidence Subagent 只能接收：

- 问题描述
- 商品名称和分类
- 售后类型
- 订单 ID
- 凭证附件
- 公共元数据

它不接收政策正文、RAG 命中、reranker 结果、Policy Assessment、提交
工具或完整父图 State。

## 私有 Subagent State

### PolicySubagentState

```text
task
retrieval_result
assessment
failure_category
steps
```

### EvidenceSubagentState

```text
task
image_review_result
assessment
failure_category
steps
```

两个子图不包含父图的：

- `payload`
- `ticket_data`
- `supervisor_plan`
- 另一个专家的 Assessment
- `review_proposal`
- `gate_action`
- `review_result`
- Java 提交结果

每次 `invoke` 都使用新建的 State，不复用上一次执行的 messages 或工具
轨迹。本次子图不配置长期 Checkpointer。

## 工具能力边界

不把通用 `AgentToolRegistry.call(name, arguments)` 直接交给 Subagent。

Policy Subagent 依赖专用端口：

```python
class PolicyRetrievalPort(Protocol):
    def retrieve(self, task: PolicyTask) -> ToolResult: ...
```

唯一允许的底层工具是 `retrieve_knowledge`。

Evidence Subagent 依赖专用端口：

```python
class EvidenceReviewPort(Protocol):
    def review(self, task: EvidenceTask) -> ToolResult: ...
```

唯一允许的底层工具是 `review_images`。

适配器可以继续复用现有 `AgentToolRegistry`，但工具名称封装在适配器内部，
Subagent 无法选择或调用 `submit_ai_review`、`handoff_to_human`、
`append_chat_message` 等业务写工具。

父图的提交节点继续使用现有通用工具门面，因为它们是受确定性路由控制的
普通代码节点，不是专家自主工具调用。

## Subagent 图

### PolicySubagentGraph

```text
receive_task
    -> retrieve_policy
    -> assess_policy
    -> END
```

- `receive_task` 校验必需标识和 `context_version`。
- `retrieve_policy` 通过 Policy 专用端口执行严格过滤检索。
- `assess_policy` 沿用当前商家、版本、时间、citation、阈值和 reranker
  可信校验，输出 `PolicyAssessment`。
- 所有失败都转换为结构化不确定结果，不产生业务写入。

### EvidenceSubagentGraph

```text
receive_task
    -> review_evidence
    -> assess_evidence
    -> END
```

- `receive_task` 校验订单、附件和 `context_version`。
- 无附件时不调用视觉 Provider，直接返回缺少凭证的 Assessment。
- 有附件时通过 Evidence 专用端口调用视觉审核。
- Provider 失败输出 `success=false` 和明确 `failure_category`，由父图
  Gate 转人工。

## 父图通信与汇总

父图仍保留 `policy_agent` 和 `evidence_agent` 包装节点，以保持现有
LangGraph 拓扑与 Trace 名称兼容。包装节点只负责：

1. 从 `TrustedCaseContext` 构建最小 Task。
2. 使用全新 State 调用对应 Subagent。
3. 将返回的 Assessment 写入父 State。

父图不接收子图内部工具轨迹、scratchpad 或中间 State。

`review_supervisor` 在综合前必须检查：

```text
policy_assessment.context_version
    == evidence_assessment.context_version
    == trusted_context.context_version
```

任一不一致时：

- 不调用 LLM 综合；
- 设置 `gate_action = MANUAL_REVIEW`；
- 添加 `specialist_context_version_mismatch`；
- 最终通过现有 Java 接口提交人工复核建议。

## 错误处理

- Task 校验错误：返回失败 Assessment，父图转人工，不重试业务写入。
- RAG 或视觉服务超时：Subagent 记录结构化失败；外层 Kafka 任务仍由现有
  总超时控制。
- 专家返回缺失 Assessment：父图 fail closed，转人工。
- `context_version` 不一致：拒绝综合，转人工。
- Java 提交失败：继续使用现有 Kafka manual fallback 和 DLQ 机制。
- Kafka、Redis、Outbox 行为保持不变。

## 可观测性

保留现有父图步骤名：

- `review_policy_agent`
- `review_evidence_agent`
- `review_supervisor_synthesize`

每个专家步骤补充：

- `subagent_task_id`
- `subagent_type`
- `input_context_version`
- `output_context_version`
- `subagent_steps`
- `failure_category`

日志和 Trace 不记录图片内容、知识正文、密钥或完整用户消息。

## 兼容性

- `FormalReviewGraph.handle()` 返回结构保持不变。
- `PolicyAssessment`、`EvidenceAssessment` 和 Java
  `specialistAssessments` JSON 结构保持兼容。
- Kafka event schema 不变。
- Java `/internal/agent-tools/aftersales/review` 请求契约不变。
- Python 不直接访问 MySQL。
- 所有到 JavaScript 的 Java `Long` ID 字符串序列化规则不受影响。

## 测试策略

### 契约测试

- PolicyTask 不包含 `attachments`、会话历史或提交字段。
- EvidenceTask 不包含政策命中、Policy Assessment 或提交字段。
- 两个专用工具端口不暴露通用 `call(name, ...)`。

### Subagent 单元测试

- Policy 子图从新 State 执行并生成现有 `PolicyAssessment`。
- Evidence 子图无附件时不调用视觉工具。
- Evidence 子图有附件时只调用视觉端口。
- RAG/视觉失败生成结构化失败 Assessment。
- 两次执行不共享私有 State 或工具轨迹。

### 父图测试

- Policy/Evidence 仍可并行汇入 Review Supervisor。
- 父图传入两个不同的最小 Task，而不是 `FormalReviewState`。
- 三方 `context_version` 一致时保持现有 APPROVE、补凭证和人工分支。
- 版本不一致时不调用 Supervisor synthesize，确定性转人工。
- 正式审核外部响应和 Java 提交 payload 保持兼容。

### 回归测试

- `python_agent/tests/test_formal_review_graph.py`
- `python_agent/tests/test_kafka_review_consumer.py`
- `python_agent/tests/test_controlled_multi_agent_evaluator.py`
- Python Agent 全量测试

## 验收标准

1. 专家实现的公开入口不能接收 `FormalReviewState` 或
   `TrustedCaseContext`。
2. Policy 与 Evidence 各自在新建私有 State 中执行。
3. 每个专家只能通过自己的专用工具端口访问一个领域能力。
4. 专家间不共享 messages、scratchpad、工具轨迹或原始结果。
5. 父图只接收现有结构化 Assessment。
6. `context_version` 不一致必定 fail closed 到人工审核。
7. 现有 Kafka、Java、MySQL 权责和外部响应契约保持不变。
8. 目标测试及 Python Agent 全量测试通过。
