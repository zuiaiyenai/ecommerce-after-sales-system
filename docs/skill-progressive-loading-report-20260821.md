# Skill 渐进式加载与 Token 对比

日期：2026-08-21

## 实现结果

当前 Skill 加载分为三级：

1. Agent 启动时只读取4个 `SKILL.md` 的 frontmatter，建立名称、描述、路径和 reference 清单。
2. 场景确定后，`select(stage)` 只读取并缓存命中的 `SKILL.md` 正文。
3. 正式审核进入 Policy Retrieval 或 Evidence Review 后，再分别读取 `policy-workflow.md` 或 `evidence-workflow.md`。

正式审核 Workflow 本身也改为首次收到正式审核任务时创建。咨询回答、人工转接、补证和正式审核路径分别按需激活 `policy-consultation`、`human-handoff`、`evidence-request` 和 `formal-review`。其中人工转接与补证使用确定性模板，不额外调用 LLM。Skill 包版本由主文件及 references 共同计算内容哈希，references 内容不会因为计算版本而进入模型上下文。

## Token 口径

本地环境没有 Qwen 官方 tokenizer。以下数字使用统一静态估算器统计中文字符、英文词和标点，适合做改造前后相对对比，不作为模型账单的精确 Token 数。文件读取和内存缓存本身不消耗 LLM Token，只有进入 Prompt 的文本才计入模型上下文。

## 对比结果

| 指标 | 改造前 | 改造后 | 变化 |
| --- | ---: | ---: | ---: |
| 启动阶段驻留的 Skill 内容估算量 | 1,838 | 354 | -80.7% |
| Policy 正式审核分支注入的 Skill 指令 | 447 | 230 | -48.5% |
| Evidence 正式审核分支注入的 Skill 指令 | 447 | 211 | -52.8% |
| 政策咨询链路注入的 Skill 指令 | 0 | 347 | +347 |

政策咨询增加的上下文不是性能回退，而是修复原主链路未使用 `policy-consultation` 的治理缺口。正式审核的下降来自只向每个内部 Workflow 注入对应 reference，而不是重复注入完整父 Skill。

## 验证

- Skill Registry、Agent 路由、咨询与正式审核：36项测试通过。
- LangGraph 会话链路回归：87项测试通过，合计123项。
- Registry 测试覆盖启动零正文缓存、单 Skill 加载、单 reference 加载及路径穿越拒绝。
