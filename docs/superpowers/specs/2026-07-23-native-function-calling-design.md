# Native Function Calling 兼容升级设计

## 背景

当前 Python Agent 已经具备完整的工具注册表、LangGraph `tool_call -> observe_tool_result -> decide_next` 循环，以及受内部 Token 保护的 Java HTTP Tool API。模型决策目前通过 Prompt 要求模型输出 `action`、`tool_name` 和 `tool_arguments` JSON，再由 Python 手工解析和分发。

底层模型客户端已经能够向 OpenAI 兼容接口和 Ollama 发送 `tools` 参数，真实模型测试也验证了 OpenAI 兼容的 `tool_calls` 协议。本次升级只替换模型决策协议，不改变现有工具实现、Java 业务边界或 LangGraph 的确定性安全规则。

## 目标

- 主链路使用原生 `tools`、`tool_calls`、`tool_call_id` 和 `role=tool` 协议。
- Provider 不支持原生 Function Calling 或返回不兼容结构时，自动回退现有 JSON 决策协议。
- 保持现有 11 个工具的名称、行为和错误分类兼容。
- 保持 Java 对权限、订单、工单、事务、状态机和幂等的所有权。
- 不允许模型输出绕过现有的自动审核、人工转接和消息持久化防线。

## 非目标

- 不修改 Java 内部 Tool API 路径或 DTO 契约。
- 不改用 LangChain `bind_tools` 或 `ToolNode`。
- 不启用并行 Tool Call。
- 不把业务状态迁移到 Python、Redis 或 LangGraph Checkpointer。
- 不删除旧 JSON 协议；本阶段将其保留为兼容回退。

## 方案选择

采用“原生 Function Calling 优先、旧 JSON 协议回退”的兼容方案。

未选择仅传递 `tools` 参数但继续用普通 JSON 表达最终动作的最小方案，因为它没有建立标准 Tool Result 回传链路。也未选择全面迁移到 LangChain ToolNode，因为当前自定义节点承载了售后审核、失败分类、有限重试和人工兜底规则，整体替换的回归风险过高。

## 总体架构

```text
LangGraph Planner / Decider
        |
        v
FunctionCallingAdapter
        |-- native: tools -> tool_calls -> role=tool
        `-- fallback: legacy chat_json action
        |
        v
NormalizedAgentAction
        |
        v
现有 tool_call -> observe_tool_result -> decide_next
        |
        v
AgentToolRegistry
        |-- JavaToolClient -> Java Internal Tool API
        |-- PgVectorKnowledgeRetriever
        `-- VisionReviewService
```

## 工具 Schema

`AgentToolRegistry` 继续作为工具名称、执行函数和模型可见 Schema 的单一来源。现有 `tool_specs()` 将补全每个工具的 JSON Schema，再由适配器转换为标准格式：

```json
{
  "type": "function",
  "function": {
    "name": "get_after_sales_ticket",
    "description": "Get an existing ticket after Java ownership validation.",
    "parameters": {
      "type": "object",
      "properties": {
        "ticket_id": {"type": "string"}
      },
      "required": ["ticket_id"],
      "additionalProperties": false
    }
  }
}
```

模型可见 Schema 不允许模型决定 `user_id`。`session_id`、`order_id`、`ticket_id` 和 `review_request_id` 在已有可信 Graph State 中存在时，仍由 `_apply_action` 强制覆盖模型参数。

新增模型控制函数 `final_reply`，用于结构化表达最终回复：

```json
{
  "assistant_reply": "给用户看的自然中文",
  "need_human": false,
  "evidence_needed": []
}
```

`final_reply` 只转换成 LangGraph Action，不注册到执行 Registry，也不产生 Java 调用。

## 原生调用流程

1. Planner 或 Decider 构造当前上下文和标准 Function Schema。
2. 模型调用使用 `tool_choice=required`，并限制一次只处理一个 Tool Call。
3. 适配器解析 `message.tool_calls`，校验工具名称及 arguments 必须是 JSON 对象。
4. 普通业务工具归一化为现有 `action=tool_call`。
5. `handoff_to_human` 归一化为 `action=human_handoff`，继续进入已有人工转接节点。
6. `final_reply` 归一化为 `action=final_reply`。
7. Tool 执行结果带上 `tool_call_id` 写入 Graph State。
8. 需要再次询问模型时，使用标准的 assistant Tool Call 消息和 `role=tool` 结果消息，并仅暴露经过压缩的 Observation，避免完整业务数据泄漏到模型上下文。

确定性路由可以继续在调用模型之前接管流程，例如已有工单必须先查询、正式审核必须检索政策、证据不足必须转人工。这些路径无需为了使用 Function Calling 而强制调用模型。

## 兼容回退

以下情况不得执行原生 Tool Call，并触发一次旧 JSON 协议回退：

- Provider 明确拒绝 `tools` 或 `tool_choice`。
- 响应没有 `message.tool_calls`。
- `tool_calls` 结构缺失函数名称。
- arguments 不是合法 JSON 对象。
- Ollama 或其他兼容 Provider 只返回普通文本内容。

回退结果继续经过 `_apply_action`、可信标识覆盖、Registry 参数校验和 Java 业务门禁。回退仅发生在模型决策协议层，不改变 Provider 网络重试和熔断规则。

未知工具不会回退后直接执行，而是生成 `UNKNOWN_TOOL` 验证错误。模型返回多个 Tool Call 时，本阶段不并行执行：记录协议错误并回退旧单动作协议，避免产生部分成功。

## 错误处理与安全边界

- 原生 arguments 解析失败时不执行工具。
- 缺少必填参数由 Registry 返回 `INVALID_TOOL_ARGUMENTS`。
- Java 401/403 映射为 permission，不重试。
- Java 404 映射为 not_found。
- 超时、429 和 5xx 继续使用现有有限重试与人工兜底。
- 非 Kafka 来源调用 `submit_ai_review` 仍被 `_apply_action` 阻止。
- 没有成功的 `submit_ai_review` Tool Result 时，禁止声称 AI 初审完成。
- Java 继续校验用户归属、工单状态、`reviewRequestId` 幂等、可信政策门禁和 SQL 条件更新。
- 最终回复继续经过 JSON、Base64 和内部标识泄漏检查。

## 状态与可观测性

Graph State 的 Tool Trace 增加可选字段：

- `tool_call_id`
- `function_call_mode`: `native` 或 `legacy_fallback`
- `provider_tool_call_shape`: `openai` 或 `ollama`

日志记录调用模式、工具名、协议回退原因和 TraceId，不记录内部 Token、完整敏感参数或模型原始长响应。现有 Agent Tool 指标保持低基数，新增模式指标时只允许固定标签 `native` 和 `legacy_fallback`。

## 兼容性

- Java API 和前端无契约变化。
- 现有 `AgentToolRegistry.call()` 和所有工具执行函数保持兼容。
- 原有 Fake LLM 测试可继续返回旧 Action 字典，通过兼容入口运行。
- OpenAI 兼容主模型优先使用原生协议。
- Ollama 支持标准 Tool Call 时使用原生协议；不支持时回退旧 JSON。
- 可通过配置关闭原生 Function Calling，以便线上快速回滚到旧协议。

建议配置：

```text
LLM_NATIVE_FUNCTION_CALLING_ENABLED=true
LLM_LEGACY_TOOL_CALL_FALLBACK_ENABLED=true
```

## 测试策略

按照 TDD 增加以下测试：

1. 标准 OpenAI `tool_calls` 被归一化为现有 Tool Action。
2. Ollama arguments 对象结构被正确归一化。
3. Tool Result 使用相同 `tool_call_id` 回传。
4. `final_reply` 控制函数不会进入执行 Registry。
5. `handoff_to_human` 继续进入现有人工转接节点。
6. 非法 arguments、未知工具和多个 Tool Call 不执行任何业务工具。
7. Provider 不支持原生工具时只回退一次旧协议。
8. 回退关闭时协议错误安全失败，不隐式执行工具。
9. 可信 `user_id`、工单和审核请求标识覆盖模型输出。
10. 非 Kafka 来源仍不能提交 AI 审核。
11. 原有工作流、错误路由、RAG、图片审核和 Java Tool 测试全部通过。
12. 标记为 `real_llm` 的 Function Calling smoke test验证真实 Provider协议。

## 验收标准

- 主模型真实请求携带标准 `tools`，并能解析标准 `tool_calls`。
- Tool Result 通过标准 Tool Message 与调用 ID关联。
- Provider 不兼容时现有聊天和售后流程仍可通过旧协议工作。
- Java内部接口、业务状态、幂等和事务行为没有变化。
- 非法或模糊模型输出不能触发写工具。
- 所有相关 Python 单元测试和现有回归测试通过。
- 配置关闭原生模式后行为与升级前一致。
