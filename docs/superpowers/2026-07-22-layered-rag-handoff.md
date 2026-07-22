# 分层 RAG 全链路交接

更新时间：2026-07-22（Asia/Shanghai）

分支：`codex/integrate-emotion`

当前实现 HEAD：`ba5cc21`

## 当前结论

Task 1-10 的代码链路均已搭建并提交。当前阶段按“先完成全链路、后补环境级测试”的要求，只保留必要的聚焦验证；真实 Provider、真实 pgvector 数据库、Docker 联调和目标环境开关演练留给后续验收分支。

核心链路已经形成：

`文件导入 -> Draft 解析/分块 -> 人工确认 -> revision CAS 发布 -> pgvector/pg_trgm 混合召回 -> RRF -> hosted rerank -> 可信策略守门 -> Agent 决策 -> Java 工单审批 -> 指标/灰度/回滚`

## 已完成范围

| 范围 | 主要提交 | 状态 |
| --- | --- | --- |
| Task 1-4：知识生命周期、解析、Draft、原子发布 | `7c06714..8d72878` | 已实现并通过逐项复审 |
| Task 5：严格/放宽过滤、Dense + Keyword、RRF、引用与可信边界 | `06c8a06..d0fcc23` | 已实现并获批 |
| Task 6：托管 reranker、超时/重试/熔断/降级 | `997b8e1..0210d2c` | 已实现并获批 |
| Task 7：策略证据、业务时间/版本、Java fail-closed 审批 | `6a90901`, `c302f06`, `ba5cc21` | 已实现，最终轻量复审 Approved |
| Task 8：商家知识 Draft 审核与发布体验 | `2eb2326`, `c302f06`, `ba5cc21` | 已实现，最终轻量复审 Approved |
| Task 9-10：评估、灰度开关、配置、运维和回滚 | `0ed1649`, `c302f06`, `ba5cc21` | 已实现，最终轻量复审 Approved |
| 干净检出依赖闭包 | `3f20d78..8044a4e` | Java、前端、Python 均可从 HEAD 构建/导入 |

## 关键安全约束

- MySQL 继续拥有订单、工单、政策版本和业务时间；Python 不自行制造这些业务事实。
- 自动 APPROVE 必须同时满足 strict filter、reranker 成功、可信政策资格、证据一致、有效 citation、政策版本一致；否则转人工。
- citation 必须有 `source_code`，并包含 `chunk_id` 或 `document_id`。
- 未知商家、空政策版本、旧工单缺少政策快照均 fail-closed。
- 分层检索默认开关仍为 `false`；非 dry-run 的四模式评估不得伪装成兼容路径。
- Dense 无命中时停止 Keyword/RRF/Reranker，避免消融指标失真。
- trace 仅输出白名单字段，不泄漏 token 或原始过滤值。

## 已有验证证据

- Task 6：87 个聚焦用例通过，最后回归 3 个用例通过；无真实 Provider 调用。
- 当前工作区 Python 关键链路：113 passed。
- 干净检出 `8044a4e`：Python 关键链路 113 passed。
- 干净检出 `f843b4f`：Java `mvn compile` BUILD SUCCESS。
- 干净检出 `f843b4f`：前端契约 14/14，Vite production build 成功。
- Task 9/10 dry-run：18 条 smoke，`provider_accessed=false`。
- Task 7 最终闭环：Java 聚焦测试 9 passed，主源码编译成功。
- Task 8 最终闭环：Controller 聚焦测试 8 passed，BUILD SUCCESS。
- Task 9/10 最终闭环：115 passed，`py_compile` 与 scoped `git diff --check` 通过。

Windows pytest 退出阶段仍可能打印临时目录 `PermissionError`，但测试命令退出码为 0；这是环境清理提示，不是用例失败。

## 后续验收分支应做什么

1. 准备带可靠标签与命中元数据的 holdout 数据，执行四模式离线评估和安全门。
2. 在测试环境配置 `DASHSCOPE_API_KEY`、`PGVECTOR_DSN`、reranker 凭据，验证标准路径显示 `knowledge mode = pgvector`。
3. 使用真实 PostgreSQL/pgvector/pg_trgm 数据验证 strict/relaxed 时间边界、发布 revision 可见性和召回质量。
4. 在目标环境按灰度文档开启 `RAG_LAYERED_RETRIEVAL_ENABLED`，观察 no-answer、filter violation、rerank latency/cost 与人工转接率，再演练回滚。
5. 如需迁移历史工单，先设计 `policy_version` 快照回填；未回填记录应继续转人工，不得放宽守门。

## 接手方式

实现提交是一条线性历史。新分支应以当前分支 HEAD 为基线；若采用 cherry-pick，则从 `52887c9` 开始按顺序取到本交接文档提交，核心代码收口点为 `ba5cc21`。不要对当前共享工作区执行 `git reset --hard`、`git clean`、`git add .`；工作区还有大量不属于本任务的用户改动。

详细实施计划：`docs/superpowers/plans/2026-07-21-layered-rag-implementation.md`

进度账本：`.superpowers/sdd/progress.md`

复审报告：`.superpowers/sdd/task-*-review*.md`
