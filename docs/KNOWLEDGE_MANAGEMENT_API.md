# 知识库管理系统使用指南

## 概述

已实现完整的知识库管理系统，管理员可以通过API上传、编辑、删除售后政策，系统自动完成文本切片和向量化。

## API接口

### 1. 上传知识库

**接口**: `POST /admin/knowledge/upload`

**请求体**:
```json
{
  "sourceType": "after_sales_policy",
  "sourceCode": "damage_policy_001",
  "merchantCode": "MERCHANT_DEMO",
  "title": "商品破损售后政策",
  "content": "商品破损售后处理规则：\n1. 适用范围：收到商品后发现外观破损、裂纹、碎裂、断裂等物理损坏\n2. 时效要求：签收后7天内提出申请，超过7天不予受理\n...",
  "productCategory": "digital",
  "scene": "damage",
  "intent": "refund",
  "policyVersion": "v1.0",
  "tags": ["破损", "退款", "7天"],
  "metadata": {}
}
```

**响应**:
```json
{
  "code": 200,
  "message": "知识库上传成功",
  "data": {
    "documentId": 1,
    "title": "商品破损售后政策",
    "chunkCount": 3
  }
}
```

### 2. 批量上传

**接口**: `POST /admin/knowledge/batch-upload`

**请求体**: 数组格式
```json
[
  {
    "sourceType": "after_sales_policy",
    "sourceCode": "damage_policy_001",
    "title": "商品破损售后政策",
    "content": "..."
  },
  {
    "sourceType": "faq",
    "sourceCode": "faq_damage_evidence",
    "title": "破损商品需要提供什么证据？",
    "content": "..."
  }
]
```

### 3. 查询知识库列表

**接口**: `GET /admin/knowledge/list`

**参数**:
- `sourceType` (可选): 类型过滤
- `merchantCode` (可选): 商户过滤
- `page` (默认1): 页码
- `pageSize` (默认20): 每页数量

**响应**:
```json
{
  "code": 200,
  "message": "查询成功",
  "data": [
    {
      "id": 1,
      "sourceType": "after_sales_policy",
      "sourceCode": "damage_policy_001",
      "title": "商品破损售后政策",
      "content": "...",
      "chunkCount": 3,
      "createdAt": "2026-07-07T10:00:00",
      "updatedAt": "2026-07-07T10:00:00"
    }
  ]
}
```

### 4. 更新知识库

**接口**: `PUT /admin/knowledge/{id}`

**请求体**:
```json
{
  "title": "更新后的标题",
  "content": "更新后的内容",
  "status": 1
}
```

### 5. 删除知识库

**接口**: `DELETE /admin/knowledge/{id}`

**响应**:
```json
{
  "code": 200,
  "message": "删除成功",
  "data": null
}
```

### 6. 测试知识库检索

**接口**: `GET /admin/knowledge/test-retrieval`

**参数**:
- `query`: 查询文本
- `merchantCode` (可选): 商户代码
- `topK` (默认5): 返回数量

**响应**:
```json
{
  "code": 200,
  "message": "检索成功",
  "data": [
    {
      "title": "商品破损售后政策",
      "snippet": "商品破损售后处理规则：1. 适用范围...",
      "score": 0.85
    }
  ]
}
```

### 7. 重建向量索引

**接口**: `POST /admin/knowledge/reindex`

**说明**: 当更换embedding模型或需要全量重建时使用

## 工作流程

### 管理员上传知识库

1. **前端调用上传接口**，传递标题和内容
2. **Java后端**:
   - 将文档插入PostgreSQL `knowledge_document`表
   - 调用文本切片算法，将长文本切分为多个chunks（每个700字符，20%重叠）
   - 调用Python Agent的`/api/embeddings`接口生成向量
   - 将chunks和向量批量插入`knowledge_chunk`表
3. **Python Agent**:
   - 接收chunks数组
   - 调用DashScope/Bailian的text-embedding-v3模型生成1024维向量
   - 返回向量数组给Java后端

### AI检索知识库

1. 用户发送售后咨询消息（如"耳机外壳破了"）
2. Python Agent调用`PgVectorKnowledgeRetriever.retrieve()`
3. 将query文本向量化
4. 在PostgreSQL中执行向量相似度搜索（余弦距离）
5. 返回Top-K最相关的知识库chunks
6. AI基于检索结果判断是否满足售后政策

## 知识库类型

- **after_sales_policy**: 售后政策（退货、换货、破损、质量问题等）
- **faq**: 常见问题解答
- **product_knowledge**: 商品知识（用于辅助判断）
- **guideline**: 操作指南（拍照规范、流程说明等）

## 配置要求

### Java后端配置

在`application.yml`中配置PostgreSQL数据源：

```yaml
spring:
  datasource:
    pgvector:
      url: jdbc:postgresql://localhost:5432/ecommerce_rag
      username: ecommerce
      password: ecommerce_pgvector
      driver-class-name: org.postgresql.Driver

python:
  agent:
    url: http://localhost:8765
```

### Python Agent配置

在`python_agent/db.local.env`中配置：

```
PGVECTOR_DSN=postgresql://ecommerce:ecommerce_pgvector@127.0.0.1:5432/ecommerce_rag
PGVECTOR_DIMENSIONS=1024
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_PROVIDER=dashscope
DASHSCOPE_API_KEY=sk-your-api-key-here
```

## 注意事项

1. **API Key必须配置**: 没有DASHSCOPE_API_KEY将无法生成向量
2. **文本切片**: 每个chunk最多700字符，重叠20%确保语义完整
3. **向量维度**: 固定1024维（text-embedding-v3模型）
4. **PostgreSQL扩展**: 需要安装pgvector扩展
5. **批量上传**: 建议每次不超过50条，避免超时

## 初始化示例数据

使用API批量上传初始政策：

```bash
curl -X POST http://localhost:8080/admin/knowledge/batch-upload \
  -H "Content-Type: application/json" \
  -d '[
    {
      "sourceType": "after_sales_policy",
      "sourceCode": "damage_policy_001",
      "title": "商品破损售后政策",
      "content": "商品破损售后处理规则：...",
      "productCategory": "digital",
      "scene": "damage",
      "intent": "refund",
      "policyVersion": "v1.0"
    }
  ]'
```

## 故障排查

### 问题1: embedding生成失败

**症状**: 日志显示"Failed to generate embeddings via Python Agent"

**解决**:
1. 检查Python Agent是否启动（http://localhost:8765/health）
2. 检查DASHSCOPE_API_KEY是否配置正确
3. 检查账户余额是否充足

### 问题2: PostgreSQL连接失败

**症状**: "Connection refused"

**解决**:
1. 检查Docker容器是否运行：`docker ps | grep pgvector`
2. 检查端口5432是否被占用
3. 检查用户名密码是否正确

### 问题3: 向量检索无结果

**症状**: AI回复"policy_hits数量: 0"

**解决**:
1. 确认knowledge_chunk表中有数据
2. 检查query文本是否与知识库内容相关
3. 调整topK参数（默认5，可增加到10）

## 下一步优化

1. ✅ 管理后台UI界面（表格+表单）
2. ✅ 知识库版本管理（支持回滚）
3. ✅ 知识库生效时间设置
4. ✅ 知识库A/B测试
5. ✅ 检索效果评估（展示召回率、准确率）
