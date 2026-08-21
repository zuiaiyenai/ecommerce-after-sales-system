# 知识库覆盖审计报告

该报告由 `tools/audit_knowledge_coverage.py` 生成。`direct` 表示品类与场景都有专属知识；其余层级表示检索会依赖分层回退。

## 汇总

- 活跃知识文档：42
- 已向量化文档：42
- 知识块：42
- 审计组合：42

| 覆盖层级 | 组合数 | 含义 |
|---|---:|---|
| direct | 7 | 品类和场景专属知识 |
| scene_default | 35 | 保留场景的通用知识 |
| category_default | 0 | 保留品类的默认知识 |
| global_default | 0 | 全局通用知识 |
| missing | 0 | 无可用知识 |

## 待补齐清单

优先补齐 `missing`，其次补齐仅依赖 `global_default` 的高频业务组合。文档写入后执行知识入库/重建，确保 `indexed_documents` 同步增长。

| 品类 | 场景 | 当前覆盖 | 文档数 | 已向量化文档 |
|---|---|---|---:|---:|
| apparel | product_damage | scene_default | 2 | 2 |
| apparel | package_damage | scene_default | 1 | 1 |
| apparel | wrong_or_missing_items | scene_default | 3 | 3 |
| apparel | logistics_issue | scene_default | 1 | 1 |
| apparel | progress_query | scene_default | 1 | 1 |
| daily | product_damage | scene_default | 2 | 2 |
| daily | package_damage | scene_default | 1 | 1 |
| daily | wrong_or_missing_items | scene_default | 3 | 3 |
| daily | logistics_issue | scene_default | 1 | 1 |
| daily | progress_query | scene_default | 1 | 1 |
| digital | product_damage | scene_default | 2 | 2 |
| digital | package_damage | scene_default | 1 | 1 |
| digital | wrong_or_missing_items | scene_default | 3 | 3 |
| digital | logistics_issue | scene_default | 1 | 1 |
| digital | progress_query | scene_default | 1 | 1 |
| food | product_damage | scene_default | 2 | 2 |
| food | package_damage | scene_default | 1 | 1 |
| food | wrong_or_missing_items | scene_default | 3 | 3 |
| food | logistics_issue | scene_default | 1 | 1 |
| food | progress_query | scene_default | 1 | 1 |
| headphone | product_damage | scene_default | 2 | 2 |
| headphone | package_damage | scene_default | 1 | 1 |
| headphone | wrong_or_missing_items | scene_default | 3 | 3 |
| headphone | logistics_issue | scene_default | 1 | 1 |
| headphone | progress_query | scene_default | 1 | 1 |
| phone | product_damage | scene_default | 2 | 2 |
| phone | package_damage | scene_default | 1 | 1 |
| phone | wrong_or_missing_items | scene_default | 3 | 3 |
| phone | logistics_issue | scene_default | 1 | 1 |
| phone | progress_query | scene_default | 1 | 1 |
| shoes | product_damage | scene_default | 2 | 2 |
| shoes | package_damage | scene_default | 1 | 1 |
| shoes | wrong_or_missing_items | scene_default | 3 | 3 |
| shoes | logistics_issue | scene_default | 1 | 1 |
| shoes | progress_query | scene_default | 1 | 1 |
