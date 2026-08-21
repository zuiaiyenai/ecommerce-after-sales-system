# Agent 安全决策离线评测基线

- 数据集版本：`1.0`
- 用例：16
- 通过：16
- 通过率：100%
- 显式转人工召回率：100%
- 自动审核安全违规：0
- 质量门禁：通过

覆盖范围：

- 严格 pgvector 政策授权路径。
- lexical fallback、放宽过滤和低分命中禁止自动审核。
- 跨商家、错误来源类型、政策版本错配和商家上下文缺失。
- 当前消息与可信历史中的显式人工请求。
- HTTP 请求伪造 Kafka 信任来源。
- Java 403/503 工具错误分类与重试语义。
- 自动审核和人工审核置信度校准。

运行命令：

```powershell
.\.venv\Scripts\python.exe tools/evaluate_agent_safety.py --check
```

数据集位于 `python_agent/evaluation/agent_safety_cases.jsonl`。CI 在每次 push 和 pull request 中执行该质量门禁。

> 该结果验证的是确定性业务护栏，不代表真实用户分布上的自然语言回答质量。RAG、情绪和视觉模型仍使用各自独立的离线基线。
