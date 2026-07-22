# 分层 RAG 离线评测基线

当前仓库中的 18 条检索查询已经迁移到 `python_agent/evaluation/rag_retrieval_cases.jsonl`，统一标记为 `split=smoke`。它们用于验证 Dense、Keyword、RRF、Rerank 四段链路、数据契约和可观测字段，不是 Holdout，也不能支持“Recall@5 为 100%”或线上效果结论。

## 数据契约

JSONL 每行必须包含：

- `case_id`、`query`、`filters`
- `relevant_chunk_ids`、`expect_no_answer`
- `forbidden_merchant_codes`、`forbidden_policy_versions`
- `split`、`annotation_method` 和可选的 `category`

当前 15 条旧场景查询标记为 `legacy_scene_heuristic_unverified`，3 条负例标记为 `negative_intent_reviewed`。旧场景匹配不能替代 chunk 级相关性标注，因此正例的 `relevant_chunk_ids` 暂为空，排名指标显示为 `N/A`，而不是人为记为 0 或 100%。

新增 Holdout 只能使用：

- `split=holdout`
- `annotation_method=dual_annotated`，或争议复核后的 `annotation_method=adjudicated`
- 明确的相关 Chunk、非空的禁止商家和禁止政策版本安全标注

## 指标口径

- Recall@5/20：正例中相关 Chunk 的宏平均召回比例。
- MRR@10：首个相关 Chunk 的倒数排名宏平均。
- NDCG@5：二元相关性的宏平均归一化折损累计增益。
- HitRate@5：Top 5 至少命中一个相关 Chunk 的正例比例。
- Filter Violation Rate：带安全标注用例中，命中禁止商家或禁止政策版本的返回项占比。
- No-answer FPR：期望无答案的用例中，系统实际作答的比例。
- Rerank Uplift：Rerank 相对 RRF 的 NDCG@5 差值。
- p50/p95 latency：每条检索端到端耗时分位数。
- 单次 Rerank 成本：`RERANK_COST_PER_CALL` 配置的每次调用估算均值，不等同于供应商账单。

安全门禁只对可靠标注 Holdout 生效。它先要求每个案例同时具有商家和政策版本安全标注、至少存在一个可检查命中，并要求每个命中都携带 `merchant_code` 与 `policy_version`；证据不足时返回 `not_applicable` 或失败，不会把零样本记为通过。证据完整后才要求 `filter_violation_rate == 0`。smoke 集不设置 Recall 硬阈值。

## 运行方式

只校验数据，不访问模型或数据库：

```powershell
python tools/evaluate_rag_recall.py --dataset python_agent/evaluation/rag_retrieval_cases.jsonl --mode all --dry-run
```

配置 PostgreSQL、Embedding 和 Rerank 后运行真实消融：

```powershell
$env:RAG_LAYERED_RETRIEVAL_ENABLED = 'true'
python tools/evaluate_rag_recall.py --dataset python_agent/evaluation/rag_retrieval_cases.jsonl --mode all
```

非 dry-run 会在任何 Provider/数据库访问前校验该开关，并拒绝把兼容检索结果标记为 Dense、Keyword、RRF 或 Rerank。

真实运行会生成 `docs/rag-recall-baseline.json` 和本文件的指标表。JSON/Markdown 报告包含样本规模、类别与 split 分布、标注方法、运行时间、模型/阈值配置、每个模式的聚合指标、每个 case 的计数型 trace 和局限说明。

Retriever trace 固定提供：`filter_level`、Dense/Keyword/RRF/Rerank 候选数、`retrieval_mode`、各阶段延迟和 `fallback_reason`。默认 trace 在 Retriever 源头按白名单序列化，不包含 Query 派生 token、过滤条件对象或商家/政策版本自由值；日志只记录安全化的 `query_id`、模式和计数，Query 原文、document ID 和商家自由文本不得进入日志或 Prometheus label。

## 当前局限

- 18 条 smoke 尚无可靠 chunk 级正例标注，不能得出 Recall/MRR/NDCG/HitRate 结论。
- 数据规模小，且不是线上流量抽样。
- Rerank 成本是配置估算；供应商计费口径变化时需同步更新。
- nightly 只有所有受保护配置齐全时才执行真实集成评测，否则明确 skip。
