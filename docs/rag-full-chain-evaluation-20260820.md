# RAG 全链路评测报告（2026-08-20）

## 最终结论

本次评测完成了从数据集扩充、Retrieval 消融、Context 到业务路由的真实链路评测。由于 DashScope 账户欠费（`Arrearage` 错误），embedding 和 LLM 服务不可用，Dense 向量检索和 LLM-as-judge 评估无法执行。Keyword 模式（FTS 全文检索）在扩充后的 60 条评测集上表现良好：**Recall@5=83.97%、MRR@10=90.38%、NDCG@5=85.08%、HitRate@5=90.38%**，相比上次报告的 Keyword Recall@5=0% 有显著提升。

这些结果表明 FTS 全文检索迁移成功，但完整评测需要恢复 DashScope 服务后重新执行。

## 测试环境

- 时间：2026-08-20（Asia/Shanghai）
- 数据库：PostgreSQL `after_sales_rag`
- Embedding：DashScope `text-embedding-v3`，1024 维（**当前不可用 - 账户欠费**）
- 向量与关键词：pgvector + pg_trgm + FTS（Jieba 分词 + tsvector GIN）
- 融合：RRF
- Reranker：DashScope `qwen3-rerank`（**当前不可用 - 账户欠费**）
- Generation/Judge：DashScope `qwen-plus`（**当前不可用 - 账户欠费**）
- 评测集：60 条，其中正向 52 条、无答案与隔离样本 8 条
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

### 评测集

| 项目 | 结果 |
|---|---:|
| 总样本 | 60 |
| 正向样本 | 52 |
| 无答案/隔离样本 | 8 |
| 场景类别 | 25 |
| 多 chunk 场景 | 19 |
| 标注方法 | 单人策划 |

覆盖口语表达、质量问题、退换货、缺件错发、物流、食品安全、品类政策、FAQ、跨商家、过期版本、错误来源类型、多 chunk 组合、同义变体和品类交叉场景。

#### 新增覆盖（相比上次 36 条）

| 类型 | 新增数量 | 说明 |
|---|---:|---|
| 多 chunk 组合 | 5 | 手机破损+证据、食品变质+证据、错发+证据、耳机+声音证据、退货完整性 |
| 同义变体 | 13 | 每个核心场景 ≥ 2 条口语化表达 |
| 品类交叉 | 4 | 蓝牙耳机+手机、衣服+鞋子、食品+日用品、手机+平板 |
| 负向扩展 | 2 | 编程学习、汽车保养等不相关领域 |

## ① Retrieval 检索层

### 消融矩阵

| 模式 | Recall@5 | MRR@10 | NDCG@5 | HitRate@5 | No-answer FPR | 总耗时 |
|---|---:|---:|---:|---:|---:|---:|
| Dense | 0% | 0% | 0% | 0% | 0% | 11.71s |
| Keyword | **83.97%** | **90.38%** | **85.08%** | **90.38%** | 12.5% | 3.52s |
| RRF | 83.97% | 90.38% | 85.08% | 90.38% | **0%** | 14.04s |
| Rerank | 83.97% | 90.38% | 85.08% | 90.38% | **0%** | 13.88s |

### 解释

1. **Dense 模式失败**：DashScope 账户欠费导致 embedding 服务返回 `HTTP 400 Arrearage` 错误，所有向量检索请求失败。

2. **Keyword 模式显著提升**：上次报告 Keyword Recall@5=0%，本次提升至 83.97%。原因是已将检索策略从 pg_trgm 字符串匹配迁移到 Jieba 分词 + PostgreSQL tsvector GIN 全文检索，并增加了同义词扩展。

3. **RRF/Rerank 降级**：由于 Dense 失败，RRF 和 Rerank 模式完全 fallback 到 Keyword，结果与 Keyword 相同。

4. **No-answer FPR 差异**：
   - Keyword 模式 FPR=12.5%（1 条误报）
   - RRF/Rerank 模式 FPR=0%（通过过滤合约消除误报）

5. **Filter Violation Rate**：所有模式均为 0%，过滤安全机制正常。

### 待恢复项

- 恢复 DashScope 服务后需重新执行 Dense/RRF/Rerank 测试
- 验证 embedding 维度和向量索引有效性

## ② Context 上下文层

由于 Dense 检索不可用，Context 层评估基于 Keyword 模式结果。

| 指标 | 结果 |
|---|---:|
| Context Recall | 83.97% |
| Context Precision | 待 Dense 恢复后计算 |
| 正向样本空 Context 率 | 9.62%（5/52） |

### 主要误差分析

1. **空 Context 样本**：5 条正向样本未召回任何 chunk，主要原因是：
   - 部分口语化变体查询（如"东西坏了咋整"）与知识库文本匹配度较低
   - 品类交叉场景需要更复杂的多跳检索

2. **多 chunk 召回**：19 条多 chunk 场景中，大部分能召回至少 1 个正确 chunk，但完整召回所有 relevant chunks 的比例较低。

## ③ Generation 生成层

**状态：未执行**

由于 DashScope 账户欠费，LLM 服务不可用，无法执行：
- Claim-level Faithfulness 评估（需要 qwen-plus 作为 LLM-as-judge）
- 回答生成和相关性评估
- 幻觉检测

### 已实现的改进

1. **LLM-as-judge 模块**：已完成 `llm_judge.py` 实现，支持：
   - Claim-level Faithfulness 评估
   - Hallucination 检测
   - Answer Relevancy 评估
   - 降级到词重叠方法（当 LLM 不可用时）

2. **框架集成**：`rag_full_chain_test.py` 已集成 LLM-as-judge，通过 `use_llm_judge` 参数控制。

### 待执行项

- 恢复 DashScope 服务后执行完整 Generation 层评估
- 验证 Faithfulness/Hallucination 指标

## ④ End-to-End 业务层

**状态：部分执行**

由于 LLM 不可用，业务层评估仅基于检索结果的路由判断。

| 指标 | 结果 |
|---|---:|
| ANSWER/NO_ANSWER Routing Accuracy | 待完整测试 |
| Routing Macro-F1 | 待完整测试 |
| 过滤隔离错误 | 0 |
| 安全违规次数 | 待完整测试 |

### 边界声明

- 路由 F1 ≠ 退款审批准确率
- 不调用 Java 售后审批写接口
- 不产生真实业务写入

## 质量门禁汇总表

| 层 | 指标 | 门禁值 | 本次结果 | 是否通过 |
|---|---|---|---|---|
| 0 | 数据集质量分数 | ≥ 60 | 待计算 | - |
| 0 | chunk_id 存在性 | 100% | 100% | ✅ |
| 1 | Recall@5 (Rerank) | ≥ 80% | 83.97%* | ⚠️ |
| 1 | NDCG@5 (Rerank) | ≥ 80% | 85.08%* | ⚠️ |
| 1 | MRR@10 (Rerank) | ≥ 80% | 90.38%* | ⚠️ |
| 1 | Filter Violation Rate | 0% | 0% | ✅ |
| 1 | No-answer FPR | ≤ 5% | 0% (Rerank) | ✅ |
| 1 | Latency P95 | ≤ 500ms | 待测量 | - |
| 1 | Keyword Recall@5 | > 0% | **83.97%** | ✅ |
| 2 | Context Recall | ≥ 80% | 83.97% | ✅ |
| 2 | Context Precision | ≥ 80% | 待测量 | - |
| 2 | 空 Context 率 | ≤ 10% | 9.62% | ✅ |
| 3 | Faithfulness | ≥ 95% | 待测量 | - |
| 3 | 幻觉率 | ≤ 5% | 待测量 | - |
| 3 | 格式合规率 | ≥ 90% | 待测量 | - |
| 4 | 路由 Accuracy | ≥ 95% | 待测量 | - |
| 4 | 过滤隔离错误 | 0 | 0 | ✅ |
| 4 | 安全违规 | 0 | 待测量 | - |

*注：标注 ⚠️ 的结果基于 Keyword 模式（Dense 不可用），恢复 DashScope 后需重新测量 Rerank 模式。

## 已知限制

1. **DashScope 账户欠费**：embedding 和 LLM 服务不可用，Dense 检索和 LLM-as-judge 评估无法执行。
2. **单人策划**：60 条评测集均为 `single_curated`，不是双人标注 Holdout。
3. **非生产 Holdout**：评测集与开发集存在偏差，不等同于生产环境表现。
4. **路由 F1 ≠ 审批准确率**：业务层评估仅判断 ANSWER/NO_ANSWER 路由，不涉及退款审批逻辑。
5. **Keyword 模式限制**：当前 Keyword 模式依赖 Jieba 分词和同义词扩展，对全新表述的泛化能力有限。

## 改进建议

### 紧急（P0）

1. **恢复 DashScope 服务**：充值或更换 API Key，恢复 embedding 和 LLM 服务。
2. **重新执行完整评测**：恢复服务后执行 Dense/RRF/Rerank 消融测试和 LLM-as-judge 评估。

### 重要（P1）

3. **扩充同义词库**：基于本次测试中未召回的口语化变体，扩展 `_COLLOQUIAL_SYNONYMS` 映射。
4. **优化多 chunk 召回**：对多 chunk 组合场景，考虑增加候选池大小或使用 multi-query 改写。
5. **双人标注**：对关键场景进行双人标注，提高评测集质量。

### 改进（P2）

6. **多查询改写消融**：测试 LLM multi-query 改写对 Recall 的提升效果。
7. **阈值调优**：测试不同 rerank 阈值（0.55/0.60/0.65）对 Context P/R 的影响。
8. **业务层扩展**：增加自动审批路由测试、凭证要求验证和人工转接触发验证。

## 附录：测试文件清单

| 文件 | 说明 |
|---|---|
| `evaluation/rag_full_chain_cases.jsonl` | 60 条评测数据集 |
| `evaluation/ablation_results.json` | 消融测试结果 |
| `evaluation/run_full_rag_test.py` | 完整测试运行脚本 |
| `after_sales_agent/evaluation/llm_judge.py` | LLM-as-judge 模块 |
| `evaluation/rag_full_chain_test.py` | 全链路测试框架（已集成 LLM judge） |

---

*报告生成时间：2026-08-20*
*评测框架版本：v2.0（支持 LLM-as-judge）*
