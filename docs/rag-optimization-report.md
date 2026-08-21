# RAG 优化总结报告

## 1. 起始状态

- **评测模式**：RRF（无 reranker）
- **数据集**：60 条（52 正向 + 8 负向）
- **起始指标**：
  - Recall@5: 82.37%
  - Faithfulness: 43.48%
  - Hallucination Rate: 81.67%
  - False Refusal: 未测量
  - Answer Relevancy: 未测量

## 2. 优化历程

| 轮次 | 改动 | 关键指标变化 | 发现 |
|---|---|---|---|
| 1 | 修 3 份 RERANK_THRESHOLDS | Recall 82%→91% | 阈值有 3 份副本，只改了 1 份 |
| 2 | generate_structured→chat_json | Faithfulness 43%→51% | jsonschema 严格校验导致 fallback |
| 3 | claim 分解→句子级 NLI | Faithfulness 66%→71.86% | 中文 claim 分解粒度不一致 |
| 4 | 解耦 true hallucination | Hallucination 46%→23% | neutral ≠ hallucination |
| 5 | NLI prompt 放宽 | Hallucination 28%→23% | 语义等价推断应算 entailed |
| 6 | 三态 prompt + is_refusal 修复 | False Refusal 不变 | prompt 正确但 context 为空 |
| 7 | 修 snippet vs chunk_text | False Refusal 55%→0% | **根因：字段名不匹配，context 一直为空** |
| 8 | _fallback_hallucination bug 修复 | 指标准确 | 缺失方法导致 AttributeError |

## 3. 最终结果

### 门禁通过情况（12 项门禁，11 项通过）

| 层 | 指标 | 结果 | 门禁 | 状态 |
|---|---|---|---|---|
| 1 | Recall@5 | 92.95% | ≥ 90% | ✅ |
| 1 | MRR@10 | 97.12% | ≥ 50% | ✅ |
| 1 | Filter Violation | 0 | = 0 | ✅ |
| 1 | Latency P95 | 496ms | ≤ 5000ms | ✅ |
| 2 | Context F1 | 85.80% | ≥ 60% | ✅ |
| 3 | Faithfulness | 85.99% | ≥ 70% | ✅ |
| 3 | Hallucination Rate | 13.33% | ≤ 15% | ✅ |
| 3 | True Hallucination | 5% | ≤ 15% | ✅ |
| 3 | False Refusal | 0% | ≤ 20% | ✅ |
| 3 | Answer Relevancy | 90.93% | ≥ 75% | ✅ |
| 4 | Routing Accuracy | 90% | ≥ 80% | ✅ |
| 3 | Correct Abstention | 75% | ≥ 80% | ❌ |

### 综合分数

**83.7/100**

## 4. 关键经验

### 4.1 字段名兼容

**根因**：检索层返回 `snippet`，评测层读 `chunk_text`，导致生成器收到空 context。

**教训**：先查数据流，再调 prompt。

**修复**：`hit.get("snippet") or hit.get("chunk_text", "")`

### 4.2 LLM Judge 不稳定

**现象**：temperature=0 仍有 ±5% 波动（API 侧负载均衡到不同 GPU 实例）。

**教训**：单次结果不可信，重要评测需跑 3 次取中位数。

### 4.3 指标解耦

**问题**：Hallucination 直接从 Faithfulness 派生，neutral ≠ hallucination。

**修复**：
- Faithfulness：句子级 NLI 评估
- Hallucination：独立检测明确编造的信息
- False Refusal：正向 case 中拒答的比例
- Correct Abstention：负向 case 中正确拒答的比例

## 5. 遗留项

| 遗留项 | 说明 | 后续计划 |
|---|---|---|
| Correct Abstention 75% | 8 条负向 case 中有 2 条未正确拒答 | 后续加 RRF score 门槛 |
| LLM 波动 | temperature=0 仍有 ±5% 波动 | 重要评测跑 3 次取中位数 |
| 数据集规模 | 60 条单人策划 | 后续扩充至 100+ 条双人标注 |

## 6. 门禁定义

### Generation 层指标

| 指标 | 定义 | 门禁 |
|---|---|---|
| Faithfulness | NLI entailed 句子比例 | ≥ 70% |
| Hallucination Rate | NLI non-entailment 比例 | ≤ 15% |
| True Hallucination Rate | detect_hallucination 检出的编造 | ≤ 15% |
| False Refusal Rate | 正向 case 中拒答的比例 | ≤ 20% |
| Correct Abstention Rate | 负向 case 中正确拒答的比例 | ≥ 80% |
| Answer Relevancy | LLM 相关性评分 | ≥ 75% |

### 检索层指标

| 指标 | 定义 | 门禁 |
|---|---|---|
| Recall@5 | 召回率 | ≥ 90% |
| MRR@10 | 排序质量 | ≥ 50% |
| Filter Violation | 过滤违规率 | = 0 |
| Latency P95 | 延迟 | ≤ 5000ms |

### 业务层指标

| 指标 | 定义 | 门禁 |
|---|---|---|
| Routing Accuracy | 路由准确率 | ≥ 80% |
| Context F1 | 上下文 F1 | ≥ 60% |

---

*报告生成时间：2026-08-21*
*评测框架版本：v3.0（句子级 NLI + 指标解耦）*
