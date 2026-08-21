# RAG 全链路评测报告（2026-08-18）

## 最终结论

本次完成了从知识库数据、Retrieval 消融、Context、Generation 到业务路由的真实链路评测。修复三类 provider/SQL 兼容问题后，在线 Agent 已恢复为：

- DashScope `text-embedding-v3` -> PostgreSQL pgvector/pg_trgm -> RRF -> `qwen3-rerank`
- Generation：DashScope compatible endpoint + `qwen-plus`
- 在线探针：`hybrid_reranked`、`reranker_succeeded=true`、`trusted_policy_eligible=true`

最终 36 条单人策划评测集上，Rerank `HitRate@5=100%`、`MRR@10=100%`、无答案误报率 `0%`；Context Precision/Recall 为 `91.67%/93.33%`；Faithfulness 为 `98.92%`；`ANSWER/NO_ANSWER` 路由 Accuracy 与 Macro-F1 均为 `100%`。

这些结果适合作为本地工程基线，不等同于双人标注生产 Holdout 或真实退款审批准确率。

## 测试环境

- 时间：2026-08-18（Asia/Shanghai）
- 数据库：PostgreSQL `after_sales_rag`
- Embedding：DashScope `text-embedding-v3`，1024 维
- 向量与关键词：pgvector + pg_trgm
- 融合：RRF
- Reranker：DashScope `qwen3-rerank`
- Generation/Judge：DashScope `qwen-plus`
- 评测集：36 条，其中正向 30 条、无答案与隔离样本 6 条
- 标注方法：`single_curated`，不是双人标注 Holdout
- Generation 评测绕过消息持久化，不产生 Java 业务写入

## 数据集质量

### 知识库

| 项目 | 结果 |
|---|---:|
| 启用文档 | 42 |
| 启用 Chunk | 42 |
| 有效 Embedding | 42/42（100%） |
| 空正文 / 空检索文本 | 0 / 0 |
| 完全重复 Chunk | 0 |
| 未发布文档 | 0 |
| revision 不一致 | 0 |
| Policy 缺失版本 | 0 |
| Chunk 字符长度 min / avg / max | 144 / 272.5 / 440 |

知识类型包括 20 篇售后政策、9 篇场景凭证、5 篇商品知识、4 篇指南、2 篇 FAQ、2 篇回复模板。

7 个品类乘 6 个核心场景共 42 个覆盖组合：7 个直接覆盖（16.67%），35 个依赖同场景通用知识回退（83.33%），无完全缺失组合。

限制：当前每篇启用文档只有一个 Chunk，尚未验证长文档跨 Chunk 召回、分块边界与上下文去重。

### 评测集

| 项目 | 结果 |
|---|---:|
| 总样本 | 36 |
| 正向样本 | 30 |
| 无答案/隔离样本 | 6 |
| 场景类别 | 23 |
| 标注方法 | 单人策划 |

覆盖口语表达、质量问题、退换货、缺件错发、物流、食品安全、品类政策、FAQ、跨商家、过期版本和错误来源类型。该数据集与当前 Chunk ID 对齐，但仍存在规模小、单人标注及开发集偏差。

## ① Retrieval 检索层

| 模式 | Recall@5 | MRR@10 | NDCG@5 | HitRate@5 | No-answer FPR | p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 97.78% | 100% | 98.44% | 100% | 50.00% | 300.25 / 441.77 ms |
| Keyword | 0% | 0% | 0% | 0% | 0% | 29.63 / 34.03 ms |
| RRF | 97.78% | 100% | 98.44% | 100% | 66.67% | 61.40 / 156.28 ms |
| Rerank | 93.33% | 100% | 94.60% | 100% | 0% | 221.84 / 349.58 ms |

解释：

- Rerank 在所有正向查询中都把至少一个正确 Chunk 排在第一位，因此 MRR 和 HitRate 为 100%。
- Rerank 阈值裁掉了部分“通用 + 品类专属”金标中的冗余通用 Chunk，集合 Recall 从 97.78% 降至 93.33%。
- Dense/RRF 会为域外查询返回低相关候选；Rerank 阈值将 6 条无答案/隔离样本全部拒绝，使 FPR 降为 0%。
- Keyword 为 0% 表明当前中文口语整句无法依赖 pg_trgm 单独召回，线上效果高度依赖 embedding。该通道需要中文 token/ngram 查询改造，不能宣称 Hybrid 带来正向召回增益。
- 所有模式 Filter Violation Rate 均为 0%。

## ② Context 上下文层

| 指标 | 结果 |
|---|---:|
| Context Precision | 91.67% |
| Context Recall | 93.33% |
| 正向样本空 Context 率 | 0% |

主要误差：

- 无品类的通用质量查询会带回数码、日用等相邻品类 Chunk，降低 Precision。
- 手机、耳机等查询优先保留最具体政策，通用质量政策被阈值裁掉，降低集合 Recall；最终答案仍有正确专属知识。
- “食品已拆封退货”等复合问题能召回口味、二次销售和无理由退货多个政策，属于合理多 Context。

## ③ Generation 生成层

| 指标 | 结果 |
|---|---:|
| 生成样本 | 30 |
| Claim-level Faithfulness | 98.92% |
| 完全忠实回答率 | 93.33% |
| Generation p50 / p95 | 2031.82 / 3846.54 ms |

Faithfulness 使用 `qwen-plus` 作为 LLM-as-judge，将回答拆为可验证声明，只允许由最终 Context 直接支持。30 条均完成 Schema 校验；两条非满分回答分别出现一条未被 Context 直接支持的安全流程话术：

- 建议提交售后申请并由系统综合判断方案。
- 最终结果以业务审核为准且不承诺退换货。

这两条没有虚构退款成功或订单状态，但按严格 grounded 口径仍计为 unsupported claim。后续可把稳定的系统权限边界作为受控 System Policy Context 注入，或限制生成器只复述检索证据。

## ④ End-to-End 业务层

| 指标 | 结果 |
|---|---:|
| ANSWER/NO_ANSWER Routing Accuracy | 100% |
| Routing Macro-F1 | 100% |
| 过滤隔离错误 | 0 |

业务层只评估“有可信知识则回答、无可信知识则拒答/转人工”的路由结果。没有调用 Java 售后审批写接口，因此不能将该数字表述为退款审批、换货审批或自动审核 Accuracy/F1。

## 恢复记录

初次评测发现 18/18 查询进入 `embedding_error`。最终修复：

1. 恢复 DashScope embedding 原生请求 `input.texts`、维度参数和 `output.embeddings` 解析，禁止吞掉 provider 原始异常。
2. 恢复 pg_trgm SQL 的 `%% %s` 操作符，真实 PostgreSQL integration 从 3/3 失败恢复为 3/3 通过。
3. 为 `LLM_PROVIDER=dashscope` 增加显式配置分支，复用现有 `DASHSCOPE_API_KEY`，不复制凭据。
4. 修复 httpx 相对路径，保留 `/compatible-mode` base path。
5. 将远程 structured output 的 `response_format` 从字符串恢复为 `{"type":"json_object"}`。
6. Provider 400 错误现在保留脱敏后的 `error.code/error.message`，不记录 Prompt 或请求体。

相关单元测试覆盖 provider payload、维度、HTTP 错误传播、URL path、structured output 和评测指标；在线 Agent 的 Retrieval 与结构化 LLM 探针均已通过。

## 简历建议

推荐写法：

> 构建售后 RAG 四层评测体系，覆盖 Retrieval 消融、Context Precision/Recall、claim-level Faithfulness 与业务拒答路由；在 36 条多场景策划集上实现 Rerank HitRate@5/MRR@10 100%、Context Precision/Recall 91.67%/93.33%、Faithfulness 98.92%、拒答路由 Macro-F1 100%，并通过真实 DashScope/pgvector 集成测试定位并修复 embedding 契约、pg_trgm SQL、compatible endpoint 路径和 structured-output 协议回归。

面试时必须主动说明：36 条是单人策划本地基线，不是生产 Holdout；业务 F1 是回答/拒答路由，不是退款审批准确率；Keyword 消融为 0%，当前召回主要来自 Dense，Reranker 的核心收益是排序与拒答控制。
