# 后端性能优化阶段测试报告

测试日期：2026-08-20 至 2026-08-21  
测试环境：本机 Docker Compose（Java、Python Agent、4 个 review-consumer、MySQL、PostgreSQL、Redis、Kafka）

## 1. 本阶段目标

验证用户前台请求、Java Agent Gateway 与 Kafka 异步 AI 审核链路的实际吞吐、延迟、积压和故障恢复能力；完成 RRF-only 检索模式下的自动审核回归。

## 2. 本阶段修改

| 范围 | 修改 | 目的 |
| --- | --- | --- |
| RAG | 禁用 Reranker，RRF 作为排序依据 | 移除不可用 Reranker 服务对审核可信门禁的依赖 |
| 政策审核 | RRF 严格过滤结果可参与可信政策、版本和引用校验 | 保持严格政策来源、版本、引用和证据校验，不以 Reranker 成功作为前提 |
| Java 审核门禁 | `multi_query_rrf` 不再因 `RERANKER_NOT_SUCCEEDED` 被拒绝 | 与 RRF-only 模式一致 |
| 人工兜底 | 请求字段由 `expectedEvidenceRevision` 修正为 `evidenceRevision` | 修复 Java DTO 校验失败导致的 DLQ |
| 会话创建 | 会话号由毫秒时间戳改为 32 位内 UUID 格式 | 防止并发创建时 `chat_session.session_no` 唯一键冲突 |
| Gateway 容量 | `AGENT_PER_INSTANCE_MAX_CONCURRENT_REQUESTS` 设置为 4 | 与 Python Agent `AGENT_MAX_CONCURRENT_REQUESTS=4` 对齐 |
| 监控 | review-consumer 暴露处理计数、耗时、inflight 指标 | 支持后续 Kafka 异步链路观测 |

## 3. 测试口径

- 前台查询：使用开发用户 JWT，对本机 Java API 发起 100 次请求，分别测试订单列表与售后列表。
- Agent 聊天：使用真实模型、无订单测试场景；统计 HTTP 成功、业务成功、兜底、工具失败与延迟。
- 异步审核：创建带有效图片证据的真实售后工单；由 Kafka 驱动 Python 审核消费者并回写 Java/MySQL。
- Kafka lag：按 consumer group 的 committed offset 与 topic end offset 计算。
- 以下结果仅代表当前本机容器、当前知识库和当前外部模型服务，不等价于生产容量承诺。

## 4. 实测结果

### 4.1 前台查询入口

| 接口 | 请求数 | 并发 | 成功率 | 吞吐 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `GET /api/orders` | 100 | 20 | 100% | 383.50 RPS | 79.70 ms |
| `GET /api/aftersales` | 100 | 20 | 100% | 240.39 RPS | 118.40 ms |

说明：售后创建接口有每用户 60 秒 5 次限流，不能用单用户无限并发压测；上述数据表示用户读取路径的 Java/MySQL 能力。

### 4.2 Agent 聊天入口

| 配置/批次 | 请求数 | 并发 | 业务成功率 | 吞吐 | P95 | 429 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 优化前 | 2 | 2 | 100% | 0.18 RPS | 11.13 s | 0 |
| 优化前 | 4 | 4 | 50% | 0.34 RPS | 11.69 s | 2 |
| Gateway 容量对齐后 | 8 | 4 | 100% | 0.35 RPS | 12.25 s | 0 |

结论：原先的 429 来自 Java Gateway 单实例容量默认为 2，而 Agent 实际可处理 4 条请求；容量对齐后并发 4 的全部请求成功。当前主要耗时来自外部 LLM 的多步骤推理，约 10 至 12 秒。

### 4.3 Kafka 异步 AI 审核

| 项目 | 结果 |
| --- | --- |
| consumer 实例数 | 4 |
| 单笔真实审核耗时 | 约 12.4 至 14.0 秒 |
| 估算稳定处理能力 | 约 18 笔/分钟（4 个 consumer、每实例串行） |
| 持续测试 | 两批各 5 笔，间隔超过前台限流窗口 |
| 最终结果 | 10/10 `COMPLETED / APPROVE` |
| review topic lag | 0 |
| DLQ topic lag | 0 |
| 会话号冲突 / `evidenceRevision` 校验错误 | 未复发 |

## 5. 已发现并修复的故障

1. Reranker 服务不可用时，RRF 结果被错误视为不可信，导致 `policy_not_trusted`、`policy_version_not_matched` 和人工转接。
2. Python 人工兜底使用了 Java DTO 不存在的 `expectedEvidenceRevision` 字段，导致 `evidenceRevision is required`，并进入 DLQ。
3. 多个审核消费者在同一毫秒创建会话时使用相同会话号，触发 `uk_chat_session_no` 唯一键冲突。
4. Java Gateway 单实例并发默认值为 2，低于 Python Agent 的 4，造成多余 429。

## 6. 收尾判断

本阶段后端性能优化可以收尾：

- 前台查询入口在本机压测下无错误且延迟可接受。
- Agent Gateway 已与 Agent 实际并发容量对齐。
- 异步审核在 10 笔持续真实审核中无积压、无新增 DLQ、无会话冲突。
- 主要剩余延迟来自外部 LLM，不属于 Java/Kafka/MySQL 的本地容量瓶颈。

后续如业务量显著增长，应优先扩展 Agent 副本和 Kafka 分区，并用同一套指标重新验证，而不是盲目提高单实例并发。
