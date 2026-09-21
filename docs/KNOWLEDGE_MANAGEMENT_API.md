# 知识库管理 API

## 1. 运行边界

- Java 上下文路径为 `/api`，本文使用浏览器实际调用的完整路径。
- 所有接口都要求管理员 Bearer Token；登录入口为 `POST /api/admin/auth/login`。
- Java 管理文档、草稿、版本和发布状态；Python Agent 负责解析、分类、Embedding 与检索。
- 业务库使用 PostgreSQL/pgvector，Embedding 维度为 1024。

## 2. 导入文档

### 2.1 文件导入

`POST /api/admin/knowledge/file-import`

请求类型为 `multipart/form-data`：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `knowledgeType` | 是 | 例如 `after_sales_policy`、`faq` |
| `scope` | 否 | 默认 `MERCHANT` |
| `merchantCode` | 按范围 | 指定商户时传入，例如 `MERCHANT_DEMO` |
| `title` | 否 | 留空时使用文件信息生成标题 |
| `file` | 是 | 仅支持 `.pdf`、`.md`、`.txt` |

成功响应只表示异步处理已创建：

```json
{
  "success": true,
  "code": 200,
  "message": "File import created",
  "data": {
    "documentId": "74",
    "reviewStatus": "PROCESSING",
    "duplicate": false
  }
}
```

### 2.2 文本导入

`POST /api/admin/knowledge/text-import`

```json
{
  "title": "服装退货规则",
  "knowledgeType": "after_sales_policy",
  "sourceCode": "apparel_return_001",
  "scope": "MERCHANT",
  "merchantCode": "MERCHANT_DEMO",
  "content": "# 服装退货规则\n正文",
  "productCategory": "apparel",
  "scene": "return",
  "intent": "refund"
}
```

旧的 `/api/admin/knowledge/import/text`、`/upload` 和 `/batch-upload` 没有映射，调用时返回 404。

## 3. 草稿审核与发布

### 3.1 查询处理状态

`GET /api/admin/knowledge/{id}/ingestion-status`

常见状态：

```text
PROCESSING → REVIEW_REQUIRED → PUBLISHING → PUBLISHED
```

解析、分类或向量化失败时会进入对应的失败状态，并返回 `errorCode`、`errorMessage`。

### 3.2 查询草稿切片

`GET /api/admin/knowledge/{id}/draft`

每个切片包含正文、页码/标题路径、`productCategories`、`scenes`、`intents`、分类来源、置信度、原因和 revision。发布前必须明确确认三组检索标签；空数组表示管理员确认该切片为通用知识，`null` 表示尚未确认。

### 3.3 保存政策版本和有效期

`PUT /api/admin/knowledge/{id}/draft`

```json
{
  "expectedRevision": 1,
  "policyVersion": "v2026.09",
  "validFrom": "2026-09-21T00:00:00",
  "validTo": "2027-09-21T00:00:00"
}
```

接口使用 revision 做并发更新检查。`after_sales_policy` 等版本化知识必须提供非空版本号和合法的生效区间。

### 3.4 保存单个切片

`PUT /api/admin/knowledge/{id}/draft/chunks/{chunkId}`

请求应携带当前 `expectedRevision` 和管理员确认后的标签。冲突返回 409，客户端应重新加载最新草稿。

### 3.5 发布

`POST /api/admin/knowledge/{id}/publish`

```json
{
  "expectedRevision": 2
}
```

发布是异步操作。收到 `Publishing started` 后继续轮询 ingestion status，直到 `PUBLISHED` 或失败终态。

### 3.6 失败重试

`POST /api/admin/knowledge/{id}/retry`

仅用于重新执行失败的解析/入库流程。

## 4. 查询和维护

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/admin/knowledge/list` | 按 `sourceType`、`merchantCode` 查询列表 |
| GET | `/api/admin/knowledge/{id}` | 查询单个知识文档 |
| PUT | `/api/admin/knowledge/{id}` | 更新文档内容或状态；内容变化会重新入库 |
| DELETE | `/api/admin/knowledge/{id}` | 逻辑删除知识文档 |
| GET | `/api/admin/knowledge/metadata-options` | 获取商户和标签选项 |
| POST | `/api/admin/knowledge/{id}/sync` | 触发单文档同步 |
| POST | `/api/admin/knowledge/reindex` | 触发全量安全重建 |

## 5. 测试真实检索

`GET /api/admin/knowledge/test-retrieval?query=...&merchantCode=MERCHANT_DEMO&topK=5`

该接口经过：

```text
Java KnowledgeRetrievalService
→ Python /api/knowledge/retrieve
→ Query Embedding
→ pgvector + 关键词召回
→ RRF / Reranker
→ 命中列表
```

响应示例：

```json
{
  "success": true,
  "code": 200,
  "message": "Retrieved",
  "data": [
    {
      "source_type": "after_sales_policy",
      "source_code": "apparel_return_001",
      "title": "服装退货规则",
      "snippet": "...",
      "score": 0.73,
      "tags": [],
      "metadata": {
        "document_id": 74,
        "revision": 3,
        "policy_version": "v2026.09"
      }
    }
  ]
}
```

## 6. 当前本地配置

共享配置示例位于根 `.env.example` 和 `python_agent/.env.example`。当前可复现本地链路使用：

```text
Java API:          127.0.0.1:8080/api
Python Agent:      127.0.0.1:8000/api
PostgreSQL:        127.0.0.1:5432/after_sales_rag
Embedding:         Ollama bge-m3
Reranker:          TEI BAAI/bge-reranker-v2-m3
Embedding 维度:    1024
```

本地模型链路不要求 DashScope Key。若切换远程模型，应通过被 Git 忽略的本地 `.env` 配置凭据。

## 7. 验收与排查

1. 上传后一直 `PROCESSING`：检查 Java 异步日志、Python `/api/health` 与 Ollama 状态。
2. `REVIEW_REQUIRED` 不能发布：确认三组标签、政策版本和有效期均已保存，并使用最新 revision。
3. 已发布但无检索结果：确认 `published_revision` 与 chunk revision 一致、向量维度为 1024、有效期覆盖检索时间、商户和标签过滤条件匹配。
4. 管理页面请求 404：确认前端调用的是 `text-import` 或 `file-import` 正式路径。

2026-09-22 实机验收记录见 `E2E_VERIFICATION.md`：TXT 文档经上传、解析、草稿确认、发布后生成 1024 维向量，并由管理检索接口命中文档 ID `74`。
