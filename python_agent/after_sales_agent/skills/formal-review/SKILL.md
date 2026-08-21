---
name: formal-review
description: 对已提交的售后申请执行正式初审。当 Kafka 审核事件到达后，需要基于 Java 可信工单上下文并行完成政策检索与视觉凭证评估、判断是否升级复杂复核、经过确定性 Gate，并通过 Java 内部接口提交自动通过、补证或转人工建议时使用。
---

# 正式售后审核

## 执行流程

1. 从 Java 加载最新工单、订单、附件、政策版本、证据版本和 `context_version`，不得用 Kafka 文本覆盖业务事实。
2. 输入缺少问题描述或附件时请求补证，不启动政策或凭证工作流。
3. 并行执行 Policy Retrieval Workflow 与 Evidence Review Workflow；需要检查具体约束时分别读取 `references/policy-workflow.md` 和 `references/evidence-workflow.md`。
4. 校验两个工作流的 `context_version`。版本不一致时失败关闭并转人工。
5. 常规案例生成确定性提案；政策不可信、检索不足、视觉不确定或证据冲突时进入复杂案例综合节点。
6. 对提案应用确定性置信度和 Gate，最后通过 Java 内部接口提交建议。

## 能力边界

- 不得直接写入 MySQL，不得拥有订单、工单、权限、事务或最终业务状态。
- Policy/Evidence 是本 Skill 内部 Workflow，不是独立 Agent，也不得生成最终结论。
- 复杂案例综合节点只能生成建议，不能绕过 Gate。
- 模型调用失败、上下文版本冲突和工具失败必须失败关闭。
- 不得为某个截图、关键词或单品编写一次性审核规则。

## 输出契约

输出审核建议、结构化政策与凭证评估、Skill 版本、升级原因、Gate 原因和 Java 持久化结果。只有 Java 返回已应用时，才能对外表示业务动作成功。
