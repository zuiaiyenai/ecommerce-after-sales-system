# 本地 E2E 验收记录

> 验收日期：2026-09-21 至 2026-09-22
> 环境：Windows 主机 + Ubuntu 24.04 VMware，全部为本地开发证据。

## 1. 服务状态

| 服务 | 位置 | 端口 | 状态 | 验证 |
| --- | --- | ---: | --- | --- |
| Vue 客服端 | Windows | 5173 | DONE | HTTP 200 |
| Java | Windows | 8080 | DONE | Actuator 200 / `UP` |
| Python Agent | Windows | 8000 | DONE | `/api/health` 200 / `ok=true` |
| Review Consumer | Windows | 8001 | DONE | `/metrics` 200 |
| MySQL | Windows | 3307 | DONE | 业务读写成功 |
| Redis | Windows | 6380 | DONE | Java/Consumer 可连接 |
| PostgreSQL + pgvector | VMware | 5432 | DONE | 版本、扩展、索引、查询通过 |
| Kafka | VMware | 9092 | DONE | Outbox 审核链路通过 |
| Ollama | VMware | 11434 | DONE | `qwen2.5:3b`、`bge-m3` |
| TEI Reranker | VMware | 8081 | DONE | health 与真实 rerank 通过 |
| Vision | 未配置 | - | NOT_DONE | 无模型/Key |
| Prometheus / Grafana | 未启动 | 9090/3000 | PARTIAL | 应用指标端点可用 |

VM 为 `EcommerceAfterSalesInfra`，4 vCPU、8 GB 内存、4 GB swap。地址 `192.168.100.130` 来自 NAT DHCP，变化后需更新本机忽略配置。

## 2. 自动化门禁

| 门禁 | 结果 | 边界 |
| --- | --- | --- |
| Python 非集成测试 | `609 passed, 8 deselected` | 排除 `integration` 与 `real_llm` 标记 |
| Java Maven 测试 | `148 run, 0 failures, 0 errors, 28 skipped` | 28 个 Testcontainers 测试因 Docker Engine 不可用跳过 |
| `git diff --check` | PASS | Phase 4 提交前通过 |
| 前端契约测试 | PASS | 14/14，见架构审计记录 |
| 客服前端构建 | PASS | real API base URL 构建 |

跳过不等于通过。真实 pgvector、Kafka 和聊天链路由 VMware 实机验收补充，但不等同于把所有 Testcontainers 用例重新执行了一遍。

## 3. PostgreSQL / RAG

已验证：

- PostgreSQL `16.15`、pgvector `0.8.6`；
- `vector` 与 `pg_trgm` 扩展；
- 42 个当前发布文档对应 42 个真实 chunk；
- 所有 Embedding 为 1024 维；
- 查询“七天无理由退货需要满足什么条件”时，Top-1 为 `return_policy_001`，cosine `0.8064`；
- 严格过滤命中为可信；放宽分类/场景的命中保持不可信并返回降级模式。

## 4. AI 客服真实请求

请求业务数据：

```json
{
  "order_id": "2101951877910061058",
  "message": "七天无理由退货需要满足什么条件？",
  "attachments": []
}
```

关键结果：

```text
elapsed_seconds: 141.35
need_human: false
session_mode: AI
knowledge_mode: hybrid_reranked
knowledge_hit_count: 1
policy_citations_count: 1
trace_id: 3c8c4c19d94c4b758e16026a2b4a4f1e
```

真实引用：

```text
source_code: return_policy_001
title: 7天无理由退货规则
policy_version: 2026-07-02-v3
```

持久化证据：

```text
session_id: 2101952086903840769
message_id: 2102063467434463234
```

`GET /api/chat/history?sessionId=2101952086903840769` 回读到相同 AI 回答文本。Java 使用登录用户与订单号从 MySQL 重建筛选上下文，未信任客户端自报商家或分类。

## 5. Kafka 正式审核真实链路

```text
Java 创建工单和 Outbox
→ Kafka after_sales.review.request
→ Python Consumer
→ Java Internal Agent Tools
→ MySQL AI_REVIEW_WAITING_EVIDENCE
→ Consumer 提交 offset
```

该次验收因缺少商品问题图片而选择 `REQUEST_EVIDENCE`，证明了状态机的补证分支。详情和事件 ID 见 `KAFKA_DESIGN.md`。

## 6. 启动复现

```powershell
.\scripts\dev-start.ps1
```

停止应用和基础设施时运行 `.\scripts\dev-stop.ps1`；只停应用时增加 `-KeepInfrastructure`。本机 `.env`、`python_agent/.env`、私钥、PID 和日志均被 Git 忽略。

2026-09-22 已完成一次真实停启验收：

1. 从四个应用端口全部关闭的状态运行 `dev-start.ps1`，Agent、Java、Vue、Consumer 依次恢复并通过健康检查；
2. `dev-stop.ps1 -KeepInfrastructure` 关闭四个受管进程树，MySQL/Redis 保持在线；
3. 默认 `dev-stop.ps1` 通过 SSH 停止 VM 的 PostgreSQL、Kafka、Ollama、Reranker，四个端口均不可达；
4. 再次运行 `dev-start.ps1`，脚本通过 SSH 拉起四个 VM 容器，等待 TEI 模型加载，再恢复全部 Windows 应用。

停止过程没有执行 `docker compose down -v`，数据库与模型卷均保留。

## 7. 当前结论

- Java 核心业务：DONE
- 文本 AI / RAG：DONE（本地 CPU 功能闭环）
- Kafka 正式审核主链：DONE
- Vision：NOT_DONE
- 生产容量、高可用、公网 TLS 与容灾：NOT_DONE
- 完整 Docker/Testcontainers 门禁：PARTIAL
