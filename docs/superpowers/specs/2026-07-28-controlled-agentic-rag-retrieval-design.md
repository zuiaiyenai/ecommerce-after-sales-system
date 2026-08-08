# 受控 Agentic RAG 检索优化设计

## 目标

在不改变 Java、前端、工单状态机和现有 Agent 工具契约的前提下，为售后
LangGraph 增加基于检索结果的有限自适应检索能力：

1. 首次检索后判断知识是否足够支持当前咨询或工单审核。
2. 仅在知识不足且基础设施正常时执行一次补充检索。
3. 补充检索必须保留原始商家、商品分类、场景、意图、来源类型、政策版本和
   业务发生时间过滤。
4. 达到上限仍不足时沿用现有缺少证据、人工复核或安全失败路径。

## 范围

允许修改：

- `python_agent/after_sales_agent/application/after_sales_workflow.py`
- 新增一个仅负责检索评估和查询改写的 Python 模块
- `python_agent/tests/` 中与售后工作流和检索策略相关的测试
- 非敏感示例配置和 Python Agent 说明

不允许修改：

- Java Controller、Service、DTO、状态机和数据库结构
- Python Agent 的 Java 工具 API 契约
- 前端代码
- pgvector 知识数据、索引和 migration
- 图片审核、AI 初审提交、人工转接的既有判定条件

## 方案比较

### 方案 A：受控确定性检索循环（采用）

工作流根据结构化 RAG 结果判断是否需要补充检索，使用确定性规则生成一个聚焦
查询，并限制总检索次数。

优点是可预测、成本有界、无需新增模型调用，并能保持政策过滤不变。缺点是查询
改写能力不如 LLM 自由改写灵活。

### 方案 B：LLM 反思和查询改写

新增 LLM 节点评价知识缺口并生成查询。灵活性较强，但会增加延迟、成本、协议
失败面和过滤条件被模型弱化的风险，暂不采用。

### 方案 C：在 Retriever 内部执行 Multi-Query

调用方无须修改，但工作流看不到中间观察，无法形成 Agent 的
`retrieve -> observe -> decide` 循环，也不利于统计每轮检索，暂不采用。

## 组件设计

### `RagRetrievalPolicy`

新增纯逻辑组件，输入当前查询、结构化检索结果、运行模式和尝试次数，输出：

- `sufficient`：当前知识是否足够。
- `should_retry`：是否允许补充检索。
- `reasons`：机器可读不足原因。
- `follow_up_query`：与原查询不同的聚焦查询。

基础设施错误、embedding 错误和检索服务错误不通过改写重试，因为换查询不能
修复这些故障。空命中、`no_answer=true`、工单政策命中不可信等语义不足场景
可以补充检索一次。

### LangGraph 状态

增加请求级短期字段：

- `retrieval_attempts`
- `retrieval_queries`
- `retrieval_assessment`

这些字段只用于当前图执行和可观测输出，不作为长期业务事实，不写入 MySQL、
Redis 或 PostgreSQL。

### 结果选择

所有成功的 `retrieve_knowledge` 结果仍保留在现有 `tool_results` 中。消费知识
结果时选择可靠性最高的一次：

1. 可信政策可用结果优先。
2. 非降级、rerank 成功结果优先。
3. 非 `no_answer` 且命中更多的结果优先。
4. 分数相同时优先较新的结果。

不跨不同过滤上下文合并 citation，避免把不同政策版本或商家结果混在一起。

## 数据流

```text
retrieve_knowledge
        |
observe_tool_result
        |
assess retrieval sufficiency
        |
        +-- sufficient -----------------> existing decision flow
        |
        +-- semantic gap + attempts left -> focused query -> retrieve_knowledge
        |
        +-- infrastructure failure ------> existing failure/manual-review flow
        |
        +-- attempts exhausted ----------> existing safe fallback
```

## 查询改写约束

- 总尝试次数默认 `2`，包括首次检索。
- 补充查询不能与历史查询标准化后相同。
- 工单审核聚焦“适用条件、排除条款、时效、凭证要求、自动审核规则”。
- 咨询聚焦“问题现象、所需证据、照片或凭证模板”。
- 查询参数只改 `query`，其他 metadata filters 原样复制。
- 不使用单品、截图或具体故障关键词硬编码。

## 错误处理

- `embedding_error`、`pgvector_error`、`*_not_configured`：不做语义重试。
- 工具抛出的 timeout/service unavailable：继续使用既有工具失败重试规则。
- 查询重复或达到上限：停止补充检索并进入既有安全路径。
- 第二次检索更差：知识消费者使用两次结果中可靠性较高的一次。

## 测试

必须覆盖：

1. 空命中触发一次补充检索。
2. 查询改写后仍保留全部 metadata filters。
3. 充分结果不触发第二次检索。
4. 基础设施错误不触发查询改写。
5. 达到两次上限后不继续检索。
6. 不允许重复查询。
7. 第二次结果更差时仍选择首次较可靠结果。
8. 现有售后工作流、Function Calling、pgvector、RRF 和 reranker 测试全部通过。

## 验收标准

- 单次 Agent 请求最多执行两次知识检索。
- 现有安全门禁和 Java 业务写入边界不变。
- 现有工具输入输出 schema 不变。
- 不新增外部依赖。
- 定向测试和 Python Agent 非真实外部服务测试通过。
- 若服务启动验证失败，只报告一次失败证据，不循环重启。
