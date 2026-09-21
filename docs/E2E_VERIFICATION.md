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
| Ollama | VMware | 11434 | DONE | `qwen2.5:3b`、`bge-m3`、`qwen2.5vl:3b` |
| TEI Reranker | VMware | 8081 | DONE | health 与真实 rerank 通过 |
| Vision | VMware Ollama | 11434 | DONE | 正常图与破损图各 1 张真实 E2E |
| Prometheus / Grafana | VMware | 9090/3000 | DONE | 三个 target UP、规则健康、dashboard 已加载 |

VM 为 `EcommerceAfterSalesInfra`，4 vCPU、8 GB 内存、4 GB swap。地址 `192.168.100.130` 来自 NAT DHCP，变化后需更新本机忽略配置。

## 2. 自动化门禁

| 门禁 | 结果 | 边界 |
| --- | --- | --- |
| Python 非集成测试 | `609 passed, 8 deselected` | 排除 `integration` 与 `real_llm` 标记 |
| Python pgvector 集成测试 | `3 passed` | 真实连接 VM PostgreSQL，覆盖稠密/关键词检索与可空硬过滤 |
| Python Redis Testcontainers | `1 passed` | 隔离 Redis 容器，覆盖 SET NX、心跳、过期接管与终态确认 |
| Python 真实 LLM | `4 passed` | Ollama OpenAI compatible 端点；对话、JSON、Tool Calling、流式协议 |
| Java Maven 测试 | `148 run, 0 failures, 0 errors, 0 skipped` | pgvector、MySQL、Kafka、Redis Testcontainers 全部实际执行 |
| `git diff --check` | PASS | Phase 6 提交前通过 |
| 前端契约测试 | PASS | 16/16，包含管理端文本导入正式路由与管理员首页无固定 Mock 数据契约 |
| 客服前端构建 | PASS | real API base URL 构建 |
| Compose 本地模型地址 | PASS | Agent/Consumer 解析后使用 `ollama:11434` 与 `reranker:80`，未继承宿主机回环地址 |
| CI workflow 本地校验 | PASS | 两个 YAML 可解析；RAG 指标门禁同款命令 13/13，通过不代表远端 Runner 已执行 |
| Spring Security 异步分派回归 | PASS | SSE 的 `ASYNC` 分派可完成；匿名初始请求仍为 401 |

Windows 通过 `scripts/run-vm-testcontainers.ps1` 使用 VM Docker。Docker API 仅绑定 VM 的 `127.0.0.1:23750`，再经 SSH 映射到 Windows 回环地址；脚本结束后关闭隧道与代理。没有向局域网暴露未加密 Docker API。

## 3. PostgreSQL / RAG

已验证：

- PostgreSQL `16.15`、pgvector `0.8.6`；
- `vector` 与 `pg_trgm` 扩展；
- 43 个当前发布文档对应 43 个真实 chunk；
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

启动脚本在 `OLLAMA_AUTO_PULL_MODELS=true` 时还会调用 `ensure-ollama-models.ps1`，已验证三个已缓存模型可被识别且不会重复下载；缺失模型会在应用进程启动前拉取。

停止过程没有执行 `docker compose down -v`，数据库与模型卷均保留。

## 7. 核心 API、浏览器与知识库生命周期

2026-09-22 使用 `cs_demo` 完成核心业务 API 验收：登录、当前用户、工作台、商品、订单、会话、消息、工单、评价及详情接口均成功；匿名请求返回 401，客服访问管理员接口返回 403。随后使用隔离 Microsoft Edge 完成 13 个页面和路由守卫检查，共观察 155 个资源/API 响应，失败 API 为 0。

最终真实性复核又使用 `admin_demo` JWT 读取管理员 overview、客服账号和知识库接口：当前为 1 个启用客服、0 个待审批/未分配账号、51 条知识记录和 0 条需维护记录。管理员首页已删除固定商家、任务、治理进度和操作日志数据；无法从 API 取得的操作记录显示空态。前端契约测试和 real API 生产构建均通过。

管理端知识库验收创建了唯一标记文档 `PHASE7-RAG-20260922025158-ZEPHYR-ORANGE-7319`，完整经过：

```text
TXT 上传 → 异步解析 → AI 分类草稿 → 政策版本/有效期确认
→ 发布 → 1024 维 Embedding → Java 管理接口 → Python RAG → pgvector 命中 → 管理页面展示
```

验收结果：

- 文档 ID `74`，草稿分类为 `apparel / return / refund`，模型置信度 `0.9`；
- 发布后 `revision=3`、`publishedRevision=3`，正式 chunk 为 1 条且向量维度为 1024；
- 查询“ZEPHYR ORANGE 7319 专属商品超过七日后应该如何处理”命中文档 `74`，rerank 分数 `0.7326`；
- 管理端页面显示“已发布”、`1 chunks` 与政策版本 `phase7-v1`；浏览器过程中 27 个 API 响应无失败；
- 修复前端文本导入仍调用旧 `/api/admin/knowledge/import/text` 的路由漂移，改为正式 `/api/admin/knowledge/text-import`；
- 修复 `/api/admin/knowledge/test-retrieval` 固定返回空列表的问题，现复用 Java `KnowledgeRetrievalService` 调用 Python `/knowledge/retrieve`。

浏览器使用 Playwright 驱动的隔离 Edge，不共享日常浏览器的 Cookie、扩展或登录状态。截图与 JSON 运行证据保存在被 Git 忽略的 `.runtime/evidence/phase7-*`。

## 8. SSE、WebSocket 与跨轮对话

2026-09-22 使用 `cs_demo` 和真实会话 `2101952086903840769` 完成实时通道验收：

- `POST /api/agent/chat/stream` 返回 HTTP 200，事件顺序为 `start → token → finish → done`，无流错误，耗时 188.358 秒；
- 当前 Python Agent 会在完整工作流结束后发送一个包含整段回答的 `token` 事件，已使用 SSE 协议，但不是模型逐 token 输出；
- 追问“那运费由谁承担？”耗时 196.578 秒，正确继承上一轮“七天无理由退货”语境；
- `/api/ws/chat` 使用 `cs_demo` JWT 完成订阅，客服发送消息后收到匹配广播，并由 HTTP 历史接口回读到相同消息；无 Token 握手返回 401；
- SSE 初次失败的根因是响应完成后的 Spring Security `ASYNC` 再分派被拒绝。现仅放行 `ASYNC`/`ERROR` 分派，普通初始请求仍要求认证。

跨轮聊天上下文由 Java 从 MySQL 最近消息和摘要重建。普通聊天工作流使用不带 checkpointer 的 `graph.compile()`；PostgreSQL `agent_runtime` checkpoint 只用于正式审核暂停、补证和恢复。实查 PostgreSQL 有 1 个正式审核 thread、5 个 checkpoint，聊天 session 对应 checkpoint 为 0。

本地 4 vCPU CPU 模型单次链路已观察到约 188–244 秒。Java Agent 超时为 300 秒，前端为 330 秒，以便前端接收 Java 网关的终态或错误事件。

运行证据保存在被 Git 忽略的 `.runtime/evidence/phase8-sse.json`、`phase8-sse-followup.json`、`phase8-websocket.json` 与 `phase8-checkpoint.json`。

## 9. Prometheus / Grafana

2026-09-22 在现有 Ubuntu VMware 上通过 `compose.vm-observability.yml` 启动 Prometheus 3.5.3 与 Grafana 12.4.3。Prometheus 从 VM 容器网络抓取 Windows 宿主机上的三个进程：

| Job | 指标入口 | 结果 |
| --- | --- | --- |
| `ecommerce-java` | `/api/actuator/prometheus` | UP |
| `ecommerce-python-agent` | `/api/metrics/prometheus` | UP |
| `ecommerce-review-consumer` | `/metrics` | UP |

4 条规则均为 `health=ok` 且当前未触发。Grafana `/api/health` 返回 `database=ok`，自动加载 UID 为 `ecommerce-agent-overview` 的 `Ecommerce After-sales Agent Overview` 仪表盘。共享指标 Token 从本地忽略配置生成并经 SSH 同步，没有进入 Git。

结构化运行证据保存在被 Git 忽略的 `.runtime/evidence/phase9-observability.json`。从 VM 匿名访问 Agent health 返回 200，匿名访问指标入口返回 401。

## 10. 本地 Vision

2026-09-22 在现有 Ubuntu VMware 的 Ollama 下载 `qwen2.5vl:3b`，无需远程 API Key。使用小程序演示用户 JWT 调用 Java `POST /api/agent/review-images`，再经内部 Token 调用 Python Vision：

| 样本 | 预期 | 结果 | 耗时 |
| --- | --- | --- | ---: |
| `01_外壳破裂.png` | 有破损 | `success=true`、识别裂纹、`has_damage_area=true` | 255.246 秒 |
| `image/耳机.png` | 正常商品图 | `success=true`、`has_damage_area=false` | 247.768 秒 |

破损样本首次独立评测曾因 160 token 输出截断触发 JSON 重试，最终成功；两次破损识别的 `damage_confidence` 分别为 0.8 和 0.2，均不足以支持当前 0.85 自动审批阈值。系统会保留人工复核边界，不会因 `has_damage_area=true` 直接修改业务状态。

这两张图片证明本地 Vision 功能链路可运行，不能替代完整质量评测。仓库中的 54 张 `qwen3-vl-plus` 报告属于历史远程模型证据，不能归因于当前本地模型。运行证据保存在被 Git 忽略的 `.runtime/evidence/phase10-vision-smoke.json`、`phase10-vision-java-e2e.json` 和 `phase10-vision-java-normal.json`。

## 11. 当前结论

- Java 核心业务：DONE
- 文本 AI / RAG：DONE（本地 CPU 功能闭环）
- Kafka 正式审核主链：DONE
- SSE / WebSocket / 跨轮聊天：DONE（SSE 当前为整段单事件）
- Prometheus / Grafana：DONE（本地混合拓扑）
- Vision：DONE（本地正负样本功能闭环；完整本地精度评测未执行）
- 生产容量、高可用、公网 TLS 与容灾：NOT_DONE
- 完整 Docker/Testcontainers 门禁：DONE
