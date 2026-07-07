# 情绪模块整合指南

本文档给负责整合情绪模块的同学使用。当前项目已将售后 AI 主链路迁移为：

- Java：只负责业务 API、鉴权、订单、售后单、会话、通知、状态硬校验。
- Python Agent：负责 LLM、LangGraph、Tools、RAG、图片理解、最终回复。
- PostgreSQL/pgvector：负责 AI 知识库向量检索。
- MySQL：继续负责订单、售后单、聊天会话、消息、通知等业务数据。

情绪模块应作为 Python Agent 的能力扩展或 Java 业务字段消费方接入，不要重新把 LLM prompt、tool schema 或 RAG 编排放回 Java。

## 1. 先准备 pgvector

本项目的 RAG 知识库依赖 PostgreSQL + pgvector。建议本地用 Docker 启动。

```powershell
docker run -d `
  --name ecommerce-pgvector `
  -e POSTGRES_USER=ecommerce `
  -e POSTGRES_PASSWORD=ecommerce_pgvector `
  -e POSTGRES_DB=ecommerce_rag `
  -p 5432:5432 `
  ankane/pgvector
```

连接信息：

```text
Host: 127.0.0.1
Port: 5432
Database: ecommerce_rag
User: ecommerce
Password: ecommerce_pgvector
DSN: postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag
```

初始化 schema：

```powershell
psql "postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag" -f sql/pgvector_schema.sql
```

如果本机没有 `psql`，可以用 DataGrip 执行 `sql/pgvector_schema.sql`。

## 2. 获取阿里百炼 embedding API Key

当前向量模型使用阿里百炼 DashScope `text-embedding-v3`，维度固定为 `1024`。

步骤：

1. 登录阿里云百炼控制台。
2. 进入模型市场，找到 `text-embedding-v3`。
3. 开通模型服务。
4. 在 API Key 管理页面创建或复制 DashScope API Key。
5. 不要把真实 key 提交到 Git。

本地设置环境变量：

```powershell
[Environment]::SetEnvironmentVariable('DASHSCOPE_API_KEY', 'sk-your-api-key', 'User')
```

当前终端立即生效：

```powershell
$env:DASHSCOPE_API_KEY=[Environment]::GetEnvironmentVariable('DASHSCOPE_API_KEY','User')
$env:PGVECTOR_DSN='postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag'
```

重要排障规则：

- 如果日志出现 `knowledge mode = lexical_fallback_after_embedding_error`
- 并且 `embedding_error = DASHSCOPE_API_KEY or BAILIAN_API_KEY is required`
- 说明 Python Agent 启动进程没有拿到 embedding key，不代表知识库为空。

## 3. 导入和重建知识库

执行基础知识和扩展知识 SQL：

```powershell
psql "postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag" -f sql/seed_knowledge_base.sql
psql "postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag" -f sql/seed_extended_after_sales_knowledge.sql
```

重建向量 chunk：

```powershell
$env:DASHSCOPE_API_KEY=[Environment]::GetEnvironmentVariable('DASHSCOPE_API_KEY','User')
$env:PGVECTOR_DSN='postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag'
.\.venv\Scripts\python.exe python_agent\ingest_pgvector_knowledge.py
```

验证：

```sql
SELECT COUNT(*) FROM knowledge_document;
SELECT COUNT(*), MIN(vector_dims(embedding)), MAX(vector_dims(embedding)) FROM knowledge_chunk;
```

期望：

- `knowledge_document` 至少 30 条。
- `knowledge_chunk` 有数据。
- embedding 维度为 `1024`。

## 4. 启动服务

Python Agent：

```powershell
$env:DASHSCOPE_API_KEY=[Environment]::GetEnvironmentVariable('DASHSCOPE_API_KEY','User')
$env:PGVECTOR_DSN='postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag'
.\.venv\Scripts\python.exe python_agent\api_server.py
```

Java 后端：

```powershell
$env:JAVA_HOME='D:\develop\SDKs\jdk-edition\jdk21'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\mvnw.cmd spring-boot:run
```

## 5. 情绪模块建议接入点

推荐把情绪模块分成三层：

1. Python Agent 情绪识别
   - 输入：用户当前消息、最近会话历史、售后状态、是否多次催促。
   - 输出：`emotion_label`、`emotion_score`、`emotion_confidence`、`handoff_reason`。
   - 可在 LangGraph 的 `classify_or_plan` 或 tool 结果观察阶段接入。

2. Java 会话字段落库
   - `chat_session.emotion_label`
   - `chat_session.emotion_score`
   - `chat_session.emotion_confidence`
   - `chat_message.emotion_label`
   - `chat_message.emotion_score`
   - `chat_message.emotion_confidence`

3. 商家端 UI 消费
   - 会话列表显示情绪标签。
   - 高负面情绪提高优先级。
   - 强投诉/多轮催促触发人工接入。

## 6. 边界要求

- 不要恢复旧 MySQL 情绪知识表作为 RAG 主库。
- 情绪策略知识如需长期维护，应写入 PostgreSQL `knowledge_document`，然后重建 `knowledge_chunk`。
- Java 不直接调用 LLM，不定义 Agent tools。
- Python 可以定义情绪分析 tool，但写入业务数据仍通过 Java API。
- 高风险情绪只影响优先级、转人工和话术风格，不应绕过售后状态机硬校验。

## 7. 建议新增 Python Tool

建议在 Python Agent tools 中新增：

```text
analyze_emotion
```

输入：

```json
{
  "user_id": "1",
  "session_id": "string",
  "message": "用户当前消息",
  "recent_history": [],
  "ticket_status": "PENDING|PROCESSING|COMPLETED|REJECTED"
}
```

输出：

```json
{
  "emotion_label": "calm|anxious|dissatisfied|angry|complaint_risk",
  "emotion_score": 0.0,
  "emotion_confidence": 0.0,
  "need_human": false,
  "reason": "简要原因"
}
```

## 8. 触发人工的建议规则

以下情况建议转人工：

- 用户明确说“转人工”“投诉”“举报”“差评”。
- 同一售后多轮催促且状态未变化。
- 情绪分数高于阈值，例如 `emotion_score >= 0.75`。
- 图片和描述不一致。
- 功能类质量问题图片无法核验。
- 物流签收争议、赔付金额争议、运费争议。

## 9. 联调检查清单

- Python Agent 启动日志确认拿到 `DASHSCOPE_API_KEY` 和 `PGVECTOR_DSN`。
- `退款多久到账` 能命中 FAQ。
- `手机充电很慢要退款` 能命中手机充电慢规则。
- 用户说“太久了我要投诉”时，情绪标签应升级。
- 情绪标签能写入 `chat_message` 和 `chat_session`。
- 商家端会话列表能看到高风险会话。
- 售后完成后能自动发送评价邀请。

