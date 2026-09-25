# 面试讲解指南

回答原则：先讲业务问题，再讲代码约束与验证证据；本地验收数据只代表当前环境，不推导生产吞吐。

## 1. Spring Boot 与分层

- **场景：** 订单、售后、客服、地址和反馈需要统一业务入口。
- **问题：** AI 与多端接入后，业务状态容易分散。
- **设计：** Controller 处理协议与身份，Service 管事务和状态，Mapper 访问 MySQL；Python 只通过内部 API 调用 Java。
- **实现：** `AfterSalesController`、`AfterSalesServiceImpl`、`ShippingAddressController`、`ShippingAddressServiceImpl`。
- **为什么：** 将可变的模型能力放在业务边界外，最终写入仍可校验和测试。
- **替代方案：** Agent 直接访问数据库，开发快但权限、事务和审计边界会重复。
- **Trade-off：** 多一次 HTTP 调用，换取单一业务事实来源。
- **面试回答：** “Java 是业务内核，Agent 生成建议或工具计划，最终状态只由 Java 按权限和状态机落库。”
- **追问：** Agent 超时、重复请求或返回非法动作时怎么处理？

## 2. MyBatis-Plus 与用户隔离

- **场景：** 用户只能操作自己的订单、工单和地址。
- **问题：** 只按主键查询会形成横向越权风险。
- **设计：** 身份来自 `@CurrentUserId`；关键资源 SQL 同时包含资源 ID 和所有者 ID。
- **实现：** `ShippingAddressMapper.selectOwned(userId, addressId)`，更新、删除、设默认前先校验所有权。
- **替代方案：** 全局数据权限插件。当前项目规模下显式 SQL 更容易审计。
- **Trade-off：** Mapper 方法增多，但权限条件清晰且测试可直接断言。
- **面试回答：** “前端不传可信 userId，JWT 解析出的 userId 同时进入查询条件。”
- **追问：** 批量接口、管理员接口如何复用数据权限？

## 3. MySQL 与事务

- **场景：** 售后申请要同时创建工单、会话记录和审核事件；默认地址只能有一个。
- **问题：** 多表写入或并发请求可能产生部分成功和重复默认值。
- **设计：** Service 使用事务；售后事件通过 Outbox 与业务数据同事务；默认地址先清旧值再设置，并用生成列唯一索引兜底。
- **实现：** `@Transactional`、`after_sales_event_outbox`、Flyway `V1__enforce_single_default_shipping_address.sql`。
- **替代方案：** 只靠应用锁或先发 Kafka。前者跨实例复杂，后者可能出现消息存在但业务回滚。
- **Trade-off：** Outbox 引入发布任务和状态表；换取可恢复的一致性。
- **面试回答：** “本地事务保证业务记录与待发布事件一起提交，独立 Publisher 负责最终发送。”
- **追问：** 唯一索引冲突、Publisher 崩溃和事件顺序怎么处理？

## 4. Redis

- **场景：** 接口限流、审核事件消费幂等和短期审核状态。
- **问题：** Kafka 至少一次投递会带来重复消费，模型调用又比较昂贵。
- **设计：** Consumer 用 Redis 原子认领 `event_id`，处理过程中续期，过期任务允许接管；Java 使用 Redis 做窗口限流和短期缓存。
- **实现：** `RedisRateLimiterServiceImpl`、Python `kafka_adapter.py` 的事件认领逻辑。
- **Trade-off：** Redis 不是最终事实源；业务完成仍由 Java/MySQL 幂等验证。
- **面试回答：** “Redis 降低重复工作，MySQL 状态和审核请求 ID 决定最终是否应用。”
- **追问：** Redis 故障时会不会重复修改工单？

## 5. Kafka、消息可靠性与失败重试

- **场景：** 图片审核和 RAG 推理耗时，不应阻塞售后提交。
- **问题：** 数据库和 Kafka 不能使用一个本地事务。
- **设计：** Transactional Outbox；Publisher 查询待发布记录，发送成功后标记；Consumer 手动决定提交 Offset，有限重试后进入 DLQ/人工处理。
- **实现：** `AfterSalesReviewEventServiceImpl`、`AfterSalesReviewDlqConsumer`、Python `AfterSalesReviewKafkaConsumer`。
- **幂等：** `event_id`、`review_request_id`、证据版本和 Java 状态机共同判重。
- **Trade-off：** 最终一致，用户先看到工单创建，审核状态随后更新。
- **面试回答：** “系统接受至少一次投递，通过多层幂等把重复消息变成可安全重放。”
- **追问：** Outbox 表不断增长、毒消息和分区暂停如何治理？

## 6. WebSocket 与 SSE

- **场景：** 客服消息需要双端同步，Agent 回复希望流式返回。
- **设计：** WebSocket 推送持久化后的消息/审核状态；SSE 代理 Agent 流式事件。
- **实现：** `ChatWebSocketHandler`、`AgentGatewayController.streamChat`、`AgentGatewayServiceImpl`。
- **为什么：** WebSocket 适合双向会话，SSE 对服务端单向流式响应更简单。
- **Trade-off：** 推送不作为事实来源，断线后客户端必须重新加载历史。
- **面试回答：** “先落库再通知，重连后以历史接口纠正本地展示。”
- **追问：** 多实例下 WebSocket 广播、背压和断点续传怎么做？

## 7. AI Agent 与 Ollama

- **场景：** 普通咨询需要按意图查询订单/政策；正式审核需要受控流程。
- **设计：** 单 `AfterSalesAgent` 调度 Skill/Workflow/Tool；本地 Ollama 提供文本、Embedding 和 Vision。
- **实现：** `python_agent/after_sales_agent/application/`、`skills/formal-review/`、provider 层。
- **为什么：** 单 Agent 减少多 Agent 协调状态；正式审核走确定性路由与 Gate。
- **Trade-off：** 本地 CPU 模型响应慢，适合功能验证，不代表生产容量。
- **面试回答：** “模型负责理解和建议，工具白名单、最大步数、版本校验和 Gate 限制它的动作范围。”
- **追问：** 如何防 Prompt Injection 和工具越权？

## 8. RAG 与 pgvector

- **场景：** 售后政策有商家、类目、版本和生效时间约束。
- **问题：** 单纯向量相似可能召回过期或跨商家政策。
- **设计：** 结构化硬过滤后执行 Dense + Keyword，RRF 融合，再由 Reranker 精排；知识不足时最多一次有界多查询改写。
- **实现：** `retrieval/knowledge_filters.py`、pgvector/pg_trgm 查询、Reranker provider。
- **失败策略：** 降级召回可用于提示，但正式审核不会把它当可信政策自动通过。
- **Trade-off：** 检索链路更长，换取来源、版本和覆盖情况可审计。
- **面试回答：** “模型只能改写自然语言查询，不能修改商家、版本、生效时间等硬过滤条件。”
- **追问：** RRF 参数、阈值、Chunk 策略和评测集怎么确定？

## 9. 服务降级

- **场景：** Ollama、Embedding、Reranker、Vision 或 Agent 可能超时/不可用。
- **设计：** 分类故障、有限重试；证据不足请求补证，其余不确定性转人工；Java 持久化终态和系统消息。
- **实现：** Python provider 错误分类、Kafka Consumer 重试/DLQ、Java 人工接管服务。
- **Trade-off：** 可用性优先于自动化率，部分请求需要人工处理。
- **面试回答：** “降级不是伪造一个成功答案，而是生成明确的人工状态并保证流程可继续。”
- **追问：** 如何避免下游故障造成重试风暴？

## 10. JWT、鉴权与 RBAC

- **场景：** 小程序用户、客服和管理员共用一套 API 服务。
- **设计：** Spring Security 无状态会话，JWT Filter 解析主体；Service 对管理员/商家角色再做数据库校验；内部 Agent API 使用独立 Token。
- **实现：** `SecurityConfig`、`JwtAuthenticationFilter`、`CurrentUserIdArgumentResolver`、`AdminConsoleServiceImpl.ensureAdmin`。
- **Trade-off：** JWT 撤销需要额外机制；当前项目依赖过期时间和账号状态校验。
- **面试回答：** “认证证明主体，资源归属和角色权限仍在业务查询中验证。”
- **追问：** Token 泄漏、密钥轮换和强制登出怎么实现？

## 11. 可观测性：Prometheus 与 Grafana

- **场景：** 需要判断慢在 Java 网关、检索、模型还是消息链路。
- **设计：** Trace ID 串联日志；Java Micrometer、Agent 和 Consumer 输出 Prometheus 指标；Grafana 汇总运行面板。
- **指标：** 请求延迟/错误、RAG 模式与降级、Outbox 发布、消费幂等、DLQ、人工接管。
- **Trade-off：** 高基数字段不进入 label，自由文本和密钥不记录。
- **面试回答：** “先用指标定位组件，再用 Trace ID 和结构化日志还原单次链路。”
- **追问：** 当前未接 Alertmanager，生产告警如何补齐？

## 12. Docker 与本地拓扑

- **场景：** Windows 开发机可使用 Docker Desktop，也支持专用 Ubuntu VMware。
- **设计：** `compose.yml` 定义完整环境；PowerShell 脚本支持 Docker、VM 和 Existing 模式。
- **实现：** `scripts/dev-start.ps1` 检查六个基础设施端点，再启动四个应用进程。
- **Trade-off：** VM 模式增加网络和 SSH 配置，但能在 Docker Desktop 不可用时复用同一 Compose 服务。
- **面试回答：** “拓扑可变，应用契约和健康检查保持一致。”
- **追问：** 如何迁移到 Kubernetes，哪些状态服务不应和应用同生命周期？

## 13. CI 与测试

- **场景：** Java、Python 和两个前端技术栈需要独立质量门禁。
- **设计：** GitHub Actions 分三个 Job；Java 跑 Maven 测试，Python 跑全量 pytest 和安全评测，前端跑契约测试与生产构建。
- **实现：** `.github/workflows/ci.yml`。
- **测试层次：** Service/Controller 单测、MySQL/Testcontainers 集成、Python unit/contract/integration、前端契约、微信开发者工具逐页回归。
- **Trade-off：** 微信平台与本地模型 E2E 不适合全部放入 CI，需要单独记录环境证据。
- **面试回答：** “CI 证明确定性代码；真实模型、微信能力和混合基础设施由本地 E2E 补充验证。”
- **追问：** 哪些测试可并行，哪些必须隔离数据库？

## 14. 微信小程序联调

- **场景：** 小程序覆盖登录、订单、售后、客服、地址和反馈。
- **设计：** `request.js` 统一注入 JWT、处理 401 与错误提示；业务页以服务端返回为准。
- **实现：** `frontend/uniapp/src/pages/`、`frontend/uniapp/src/utils/request.js`。
- **Trade-off：** `touristappid` 无法完整验证地图瓦片和部分正式能力；文件选择器也需要人工操作。
- **面试回答：** “构建通过后还在微信开发者工具逐页点击，并核对 Console、Network 和持久化结果。”
- **追问：** 正式 AppID 的域名白名单、隐私声明和上传限制如何配置？
