# AI 售后模块 — 转人工逻辑与状态流改动文档

> 生成时间：2026-07-01  
> 分支：`codex/test-ai-module-merge`  
> 改动范围：Java 后端 + 商家客服端 Vue 前端 + Python AI Agent + 用户端 uniapp

---

## 一、改动的整体目标

将售后工单（Ticket）的状态流从旧的 **PENDING → APPROVED/REJECTED** 模式改为 **PENDING → PROCESSING → COMPLETED/REJECTED** 模式，并让 Python AI Agent 在图片核验通过时自动审核，在核验失败时转人工。

---

## 二、状态流转对比

### 旧流程

```
用户提交 → PENDING（待审核）
  ├── 审核通过 → APPROVED（已通过）
  └── 驳回     → REJECTED（已拒绝）
```

### 新流程

```
用户提交 → PENDING（待审核）
  ├── AI自动审核 或 人工通过 → PROCESSING（处理中）
  │     └── 人工点击"处理完成" → COMPLETED（已完成）
  └── 驳回                    → REJECTED（已驳回）
```

| 旧状态 | 新状态 | 说明 |
|--------|--------|------|
| `PENDING` / `PENDING_REVIEW` | `PENDING_REVIEW`（待审核） | 不变 |
| `PROCESSING`（处理中） | `PROCESSING`（处理中） | 含义改变：原"审核中"→现"审核通过后处理中" |
| `APPROVED`（已通过） | **删除** | 合并到 PROCESSING |
| `COMPLETED`（已完成） | `COMPLETED`（已完成） | **新增人工操作** |
| `REJECTED`（已驳回） | `REJECTED`（已驳回） | 不变 |

---

## 三、修改的文件清单

### 3.1 Java 后端（6 个文件）

| 文件 | 改动内容 |
|------|----------|
| `src/main/java/.../service/MerchantCsService.java` | 新增 `completeTicket()` 接口方法 |
| `src/main/java/.../controller/MerchantCsController.java` | 新增 `POST /merchant-cs/tickets/{id}/complete` 端点 |
| `src/main/java/.../service/impl/MerchantCsServiceImpl.java` | **核心改动**：<br>1. `approveTicket()` 状态从 `APPROVED` 改为 `PROCESSING`，增加状态校验<br>2. `rejectTicket()` 增加状态校验（仅 PENDING 可驳回）<br>3. **新增** `completeTicket()`：仅 PROCESSING → COMPLETED，记录日志+通知<br>4. `toTicketView()` 调整 `approvedRefundAmount` 判断<br>5. 所有中文文案"工单"→"申请" |
| `src/main/java/.../dto/MerchantCsDtos.java` | 新增 `TicketCompleteRequest` DTO |
| `src/main/java/.../service/impl/AfterSalesServiceImpl.java` | `getStatusText()` 移除 `APPROVED`，`REJECTED` 改为"已驳回" |
| `src/main/java/.../controller/AfterSalesController.java` | 错误提示"售后工单不存在"→"售后申请不存在" |

### 3.2 商家客服端前端（staff-auth-test-ui，10 个文件）

| 文件 | 改动内容 |
|------|----------|
| `src/views/TicketsView.vue` | 核心页面改动：<br>1. 标题"工单审核工作台"→"审核工作台"<br>2. 筛选栏：`APPROVED(已通过)` → `COMPLETED(已完成)`<br>3. 新增"处理完成"按钮（仅 PROCESSING 状态显示）<br>4. `handleApprove()` 消息改为"已进入处理中"<br>5. 新增 `handleComplete()` + `isCompletable()` |
| `src/views/TicketDetailView.vue` | 1. 状态映射更新（移除 APPROVED）<br>2. `reviewable` 仅 PENDING_REVIEW<br>3. 新增 `completable` + "处理完成"按钮<br>4. `handleApprove()` 消息更新 |
| `src/views/DashboardView.vue` | "待审核工单"→"待审核申请" |
| `src/components/SidebarNav.vue` | 导航标签"售后工单"→"售后申请" |
| `src/api/merchantCs.js` | 1. **新增** `completeTicket()` API 函数<br>2. `approveTicket()` mock 改为设置 `PROCESSING`<br>3. mock 数据文案更新 |
| `src/router/index.js` | 路由 title："售后工单"→"售后申请"，"工单详情"→"申请详情" |
| `src/views/LoginView.vue` | 描述"售后工单"→"售后申请" |
| `src/views/OrdersView.vue` | 按钮"关联工单"→"关联申请" |
| `src/views/OrderDetailView.vue` | 按钮"查看关联工单"→"查看关联申请" |
| `src/styles.css` | CSS 类名 `.ticket-status.approved` → `.ticket-status.completed` |

### 3.3 用户端前端（uniapp，3 个文件）

| 文件 | 改动内容 |
|------|----------|
| `src/pages/after-sale/list.vue` | 1. Tab 改为：全部/待审核/处理中/已驳回/已完成<br>2. 操作按钮适配新状态 |
| `src/pages/after-sale/detail.vue` | 1. `statusSteps` 新增 `PENDING` 步骤，`REJECTED` "已拒绝"→"已驳回"<br>2. 移除 `APPROVED` 分支<br>3. `fillAfterSaleInfoFromOrder` 默认状态改为 `PENDING` |
| `src/utils/mockData.js` | Mock 数据 `APPROVED` → `PROCESSING` |

### 3.4 Python AI Agent（2 个文件）

| 文件 | 改动内容 |
|------|----------|
| `after_sales_agent/agents/handoff_agent.py` | 转人工判定逻辑细化：<br>1. 用户说"转人工"+ evidence_complete + 有图片 + visual_review_failed → **转人工**（场景 D）<br>2. 用户说"转人工"+ evidence_complete + 有图片 + visual_evidence 非空 → **不转人工**（场景 B，静默通过）<br>3. 用户说"转人工"+ evidence_complete + 无图片 → 走旧逻辑转人工 |
| `after_sales_agent/agents/return_agent.py` | 三处改动：<br>1. **第 120-165 行**：HUMAN_SERVICE 意图下，若证据完整+图片核验通过 → `CREATE_TICKET` + `force_auto_approve=True`，不转人工<br>2. **第 420-468 行**：质量场景 `_handle_scene_specific_flow()`：<br>   - 图片核验失败(`visual_review_failed`) → 转人工（场景 D）<br>   - 图片核验通过 → 直接 `CREATE_TICKET` + `force_auto_approve=True`（场景 B）<br>3. **`_build_ticket()`**：新增 `force_auto_approve: bool = False` 参数 |

---

## 四、Python Agent 转人工逻辑（完整版）

### 四个触发场景

```
用户发起售后咨询
  │
  ├─ 场景 A：用户说"转人工" + human_request_count >= 2
  │   → 无条件转人工（用户连续多次强烈要求）
  │
  ├─ 场景 B：用户上传图片 + 视觉模型核验通过 + 描述详细 + 证据完整
  │   → AI 自动审核通过，生成 AUTO_APPROVED 工单，进入 PROCESSING 状态
  │   → 不转人工，不跳过 LLM 回复生成
  │   （适用于：用户说"转人工" 或 质量问题场景）
  │
  ├─ 场景 C：情绪紧急（DISSATISFIED/ANGRY）+ 意图=COMPLAINT/GENERAL
  │   → 转人工
  │
  └─ 场景 D：用户上传图片 + 视觉模型核验失败
      → 转人工（视觉模型不可用/超时/无法识别）
      （适用于：用户说"转人工" + 有图片 + visual_review_failed 或
                质量问题 + 有详细描述 + visual_review_failed）
```

### 关键判断条件

| 条件变量 | 含义 | 代码位置 |
|----------|------|----------|
| `request.attachments` 非空 | 用户上传了图片 | `handoff_agent.py:34` |
| `request.visual_review_failed` | True=视觉模型不可用/超时/失败 | `vision_utils.py:23-35` |
| `request.visual_evidence` 非空 | 视觉模型识别到破损照片/外包装/物流面单等 | `vision_utils.py:8-20` |
| `evidence_result.evidence_complete` | 所需证据（图片+描述）齐全 | `evidence_agent.py:32-38` |
| `_has_detailed_quality_description()` | LLM 判断用户描述了具体异常现象 | `return_agent.py:498-504` |

### 服务启动

```powershell
# 在 python_agent 目录下
C:\Users\29146\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe api_server.py
```

服务监听 `http://127.0.0.1:8000`，主要端点：
- `POST /api/chat` — 售后咨询对话
- `GET /health` — 健康检查（返回 404，但服务正常）

如果遇到 `ModuleNotFoundError: No module named 'pymysql'`：
```bash
C:/Users/29146/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -m pip install pymysql
```

---

## 五、商家客服端审核操作流程

### 操作按钮可见性

| 状态 | 可见操作 |
|------|----------|
| 待审核 `PENDING_REVIEW` | "通过"、"驳回" |
| 处理中 `PROCESSING` | "处理完成" |
| 已完成 `COMPLETED` | 无操作按钮（已终结） |
| 已驳回 `REJECTED` | 无操作按钮（已终结） |

### API 端点

| 操作 | 端点 | 请求体 | 状态转换 |
|------|------|--------|----------|
| 审核通过 | `POST /merchant-cs/tickets/{id}/approve` | `{"auditOpinion":"..."}` | PENDING → PROCESSING |
| 驳回 | `POST /merchant-cs/tickets/{id}/reject` | `{"rejectReason":"..."}` | PENDING → REJECTED |
| 处理完成 | `POST /merchant-cs/tickets/{id}/complete` | `{"completeNote":"..."}` | PROCESSING → COMPLETED |

### 后端状态校验

- `approveTicket()`：仅 `PENDING` 或 `PENDING_REVIEW` 可操作，否则抛 BizException
- `rejectTicket()`：仅 `PENDING` 或 `PENDING_REVIEW` 可操作，否则抛 BizException
- `completeTicket()`：仅 `PROCESSING` 可操作，否则抛 BizException

---

## 六、数据库状态值对照

数据库 `after_sales_ticket.status` 字段使用以下值：

| status 值 | 商家端显示 | 用户端显示 | 说明 |
|-----------|-----------|-----------|------|
| `PENDING` | PENDING_REVIEW（待审核） | 待审核 | 用户提交后初始状态 |
| `PROCESSING` | PROCESSING（处理中） | 处理中 | AI或人工审核通过后 |
| `COMPLETED` | COMPLETED（已完成） | 已完成 | 人工点击处理完成后 |
| `REJECTED` | REJECTED（已驳回） | 已驳回 | 审核不通过 |

> 注意：Python Agent 中的 `TicketStatus.AUTO_APPROVED` 和 `TicketStatus.PENDING_REVIEW` 是工单创建时的内部状态标记，最终会映射到数据库的 `PENDING` 或后续由后端状态机处理。

---

## 七、后续注意事项

1. **数据库 schema**：`sql/schema.sql` 中 `after_sales_ticket.status` 的 ENUM 值已包含 `PENDING`, `PROCESSING`, `APPROVED`, `REJECTED`, `COMPLETED`, `CLOSED`，无需修改。但业务代码中 `APPROVED` 已不再使用。

2. **Python Agent 状态映射**（`infra/db.py:605-613`）：`_map_after_sales_status()` 中 `APPROVED` 的映射保留不动，但新创建的工单不会再用该值。

3. **前端 mock 数据**：`staff-auth-test-ui/src/api/merchantCs.js` 和 `uniapp/src/utils/mockData.js` 中已无 `APPROVED` 状态的 mock 数据。

4. **CSS 样式**：`staff-auth-test-ui/src/styles.css` 中 `.ticket-status.approved` 已改为 `.ticket-status.completed` 复用绿色样式。

5. **Python Agent 服务**：如果本地的 Anaconda Python 缺少 SSL 模块，需要使用 hermes-agent 的 venv Python 来启动服务。
