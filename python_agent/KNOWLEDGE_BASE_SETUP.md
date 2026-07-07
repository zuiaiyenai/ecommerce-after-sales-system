# 售后知识库初始化指南

## 概述

本指南帮助你初始化售后AI客服的向量知识库，解决当前`policy_hits数量: 0`的问题。

## 知识库内容

已创建的知识库包含：

### 1. 售后政策 (4条)
- **商品破损售后政策**：外壳破裂、碎裂等物理损坏的处理规则
- **质量问题售后政策**：电流声、异响、功能缺陷等质量问题处理规则
- **退货退款基本政策**：7天无理由、时效要求、退款流程
- **换货政策**：换货条件、流程、运费说明

### 2. 常见问题FAQ (2条)
- **破损商品证据要求**：需要拍摄哪些照片、拍摄技巧
- **质量问题证据要求**：不同质量问题的证据要求

### 3. 商品知识 (1条)
- **蓝牙耳机常见问题**：帮助AI判断哪些是质量问题、哪些不是

### 4. 使用指南 (1条)
- **售后照片拍摄指南**：照片拍摄规范和技巧

## 初始化步骤

### 前提条件

1. **PostgreSQL已安装并启动**
   - 数据库：`ecommerce_rag`
   - 用户：`ecommerce`
   - 密码：`ecommerce_pgvector`

2. **Python环境已配置**
   - 已安装`psycopg`库
   - 已配置`db.local.env`

3. **DashScope API Key（可选）**
   - 用于生成向量embeddings
   - 如果没有API Key，可以先导入文档，后续再生成向量

### 执行初始化

#### 方法1：使用PowerShell脚本（推荐）

```powershell
cd D:\develop\workspace\idea\ideaprojects\Ecommerce\python_agent
.\setup_knowledge_base.ps1
```

脚本会自动：
1. 检查PostgreSQL连接
2. 导入知识库文档
3. 检查DASHSCOPE_API_KEY配置
4. 生成向量embeddings（如果配置了API Key）
5. 显示统计结果

#### 方法2：手动执行

如果脚本执行失败，可以手动执行：

1. **导入知识库文档**：
```powershell
$env:PGPASSWORD = "ecommerce_pgvector"
psql -h localhost -p 5432 -U ecommerce -d ecommerce_rag -f ..\sql\seed_knowledge_base.sql
```

2. **生成向量embeddings**（需要配置DASHSCOPE_API_KEY）：
```powershell
cd python_agent
python ingest_pgvector_knowledge.py
```

## 配置DASHSCOPE_API_KEY

如果需要向量检索功能，必须配置API Key：

1. 打开`python_agent/db.local.env`
2. 取消注释并填写：
```
DASHSCOPE_API_KEY=sk-your-actual-api-key-here
```

3. 重新运行：
```powershell
python ingest_pgvector_knowledge.py
```

## 验证结果

初始化成功后，应该看到：

```
知识库文档统计：
类型                    | 文档数
-----------------------+-------
after_sales_policy     |   4
faq                    |   2
guideline              |   1
product_knowledge      |   1

总chunk数: 约10-15条
```

## 测试知识库

重新测试售后申请流程，Python控制台应该显示：

```
📚 policy_hits数量: 2-4  (之前是0)
📝 policy_uncertain: False  (之前是True)
✅ auto_approved: True  (如果图片识别成功且有破损)
```

## 后续优化

如果知识库效果不理想，可以：

1. **添加更多政策**：编辑`sql/seed_knowledge_base.sql`，添加更多场景
2. **调整检索参数**：修改`PGVECTOR_TOP_K`（默认5）
3. **优化policy内容**：让文本更接近用户的实际表达

## 故障排查

### 问题1：psql命令未找到

**解决**：安装PostgreSQL客户端工具或使用数据库工具手动执行SQL

### 问题2：DASHSCOPE_API_KEY无效

**解决**：
1. 检查API Key是否正确
2. 检查账户余额是否充足
3. 暂时跳过向量生成，先恢复`policy_uncertain=False`的逻辑

### 问题3：向量生成失败

**临时方案**：保持Python Agent中`policy_uncertain=False`的设置，AI会基于图片识别结果判断，不依赖知识库

## 总结

初始化知识库后：
- ✅ 解决`policy_hits数量: 0`的问题
- ✅ AI能匹配到相关售后政策
- ✅ 结合图片识别和政策匹配，更准确判断是否自动通过
- ✅ 如果知识库检索失败，仍然有`policy_uncertain=False`的兜底逻辑
