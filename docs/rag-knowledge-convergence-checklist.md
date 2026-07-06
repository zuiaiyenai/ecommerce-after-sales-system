# RAG / 知识库收敛清单

## 1. 当前结论

当前项目已经做出了“知识库层”，但还不是完整的 RAG 检索增强链。

更准确地说，现在并存的是 4 层东西：

1. Spring Boot 资源目录
2. Spring Boot / MySQL 知识表
3. Python Agent 执行链
4. Python 内置默认常量兜底

问题不在于“版本太多完全不能用”，而在于：

- 有些知识已经落库，但没有真正进入执行链
- 有些逻辑已经接知识库，但同时还保留一套 Python 默认值
- 有些字段长得像 RAG，但并没有真实召回、重排、命中记录

所以当前最准确的判断是：

- 现在是“知识库化 + 配置化”阶段
- 还不是“完整 RAG 化”阶段

## 2. 现在到底有哪些版本

### 2.1 Spring Boot 策略目录

作用：提供商家策略、可编辑字段、默认规则目录。

关键文件：

- [after-sales-policy-catalog.json](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/resources/after-sales-policy-catalog.json)
- [ResourceAgentPolicyCatalogService.java](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/java/com/ecommerce/aftersales/service/impl/ResourceAgentPolicyCatalogService.java)

### 2.2 Spring Boot 知识库目录

作用：提供知识定义、术语、FAQ、模板、情绪知识、场景证据知识。

关键文件：

- [policy-knowledge-base.json](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/resources/agent-knowledge-base/policy-knowledge-base.json)

当前包含：

- `emotion_levels`
- `emotion_keyword_knowledge`
- `emotion_strategy_knowledge`
- `after_sales_scheme_knowledge`
- `scene_evidence_knowledge`
- `faq_knowledge`
- `after_sales_policy_knowledge`
- `product_knowledge`
- `reply_template_knowledge`
- `review_interpretation_knowledge`

### 2.3 MySQL 知识表

作用：让知识不只写死在 JSON，可落库、可维护。

关键文件：

- [20260705_add_agent_knowledge_base_tables.sql](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/sql/migrations/20260705_add_agent_knowledge_base_tables.sql)
- [seed_knowledge_base.sql](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/sql/seed_knowledge_base.sql)

当前已覆盖的表主要有：

- `emotion_keyword_knowledge`
- `emotion_strategy_knowledge`
- `reply_template_knowledge`
- `review_interpretation_knowledge`
- 以及已有的 `faq` / `product_knowledge` / `after_sales_policy` 等

### 2.4 Python 执行链

作用：真正做售后决策。

关键文件：

- [merchant_policy.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/merchant_policy.py)
- [policies.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/policies.py)
- [return_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/return_agent.py)
- [emotion_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/emotion_agent.py)
- [evidence_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/evidence_agent.py)

### 2.5 Python 默认常量兜底

作用：当远端策略接口或知识库不可用时，仍然能跑。

关键位置：

- [merchant_policy.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/merchant_policy.py:42)
- [merchant_policy.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/merchant_policy.py:52)
- [merchant_policy.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/merchant_policy.py:83)

## 3. 哪些已经真正接入主链

### 3.1 已真正生效

以下内容已经不只是“存在”，而是会真实影响 agent 行为：

- 情绪等级知识
- 情绪关键词知识
- 情绪回复策略知识
- 场景证据知识

对应代码：

- [emotion_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/emotion_agent.py:161)
- [emotion_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/emotion_agent.py:203)
- [emotion_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/emotion_agent.py:210)
- [evidence_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/evidence_agent.py:89)
- [evidence_agent.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/agents/evidence_agent.py:102)

### 3.2 已下发但未真正进入执行链

以下内容虽然已经能从 Spring Boot 组装进 `knowledge_base`，但 Python 主链目前并没有真实消费：

- `faq_knowledge`
- `product_knowledge`
- `after_sales_policy_knowledge`
- `reply_template_knowledge`
- `review_interpretation_knowledge`
- `after_sales_scheme_knowledge`

对应组装位置：

- [ResourceAgentPolicyCatalogService.java](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/java/com/ecommerce/aftersales/service/impl/ResourceAgentPolicyCatalogService.java:337)
- [ResourceAgentPolicyCatalogService.java](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/java/com/ecommerce/aftersales/service/impl/ResourceAgentPolicyCatalogService.java:378)
- [ResourceAgentPolicyCatalogService.java](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/java/com/ecommerce/aftersales/service/impl/ResourceAgentPolicyCatalogService.java:396)
- [ResourceAgentPolicyCatalogService.java](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/java/com/ecommerce/aftersales/service/impl/ResourceAgentPolicyCatalogService.java:415)
- [ResourceAgentPolicyCatalogService.java](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/java/com/ecommerce/aftersales/service/impl/ResourceAgentPolicyCatalogService.java:435)
- [ResourceAgentPolicyCatalogService.java](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/src/main/java/com/ecommerce/aftersales/service/impl/ResourceAgentPolicyCatalogService.java:456)

## 4. 现在为什么会显得紊乱

### 4.1 同一类真相源有两份

例如：

- 场景证据：知识库里有一份，Python 默认常量也有一份
- 回复模板：知识库里有一份，Python 默认常量也有一份
- 售后方案映射：策略层有一份，Python 默认常量也有一份

这会导致后面修改时出现：

- 改了数据库但效果没变
- 改了 JSON 但实际跑的是 Python 默认值
- 线上和本地表现不一致

### 4.2 “知识库”与“RAG”被混叫了

现在很多内容其实只是：

- 可维护知识
- 可配置规则
- 字典表
- 模板表

它们不等于真正的 RAG。

真正 RAG 至少还应包含：

- 查询改写
- 向量化
- 检索召回
- 重排序
- 命中片段引用
- 命中日志与置信度

当前项目里暂时没有完整看到这条运行链。

### 4.3 远端拿不到时会退回空知识库

当 Python 远端策略解析失败时，会回退到内建策略，而且 `knowledge_base` 可能为空。

关键位置：

- [merchant_policy.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/merchant_policy.py:414)
- [merchant_policy.py](/D:/ecommerce-after-sales-system-codex-test-ai-module-merge/python_agent/after_sales_agent/merchant_policy.py:434)

这意味着：

- 你以为自己在跑“知识库版”
- 实际有些时候跑的是“无知识库兜底版”

### 4.4 编码污染让知识本身失真

当前已有多处历史乱码：

- 资源 JSON
- SQL seed
- Python 默认中文常量
- 历史文档

这不是单纯显示问题，而是知识源本身已被污染一部分，后续越复制越乱。

## 5. 收敛原则

后面整理时，统一按下面 4 条原则执行：

1. 执行链只认一份真相源
2. 知识库和 RAG 分开命名
3. 默认常量只保留最小兜底
4. 未接主链的内容不算“完成”

## 6. 该保留什么

### 6.1 保留 Spring Boot 作为知识下发入口

保留原因：

- 它适合作为统一真相源
- 它能连接数据库
- 它能给前端、Python、后台配置页统一出接口

保留内容：

- `AgentPolicyCatalogService`
- `ResourceAgentPolicyCatalogService`
- `/api/agent/policies/catalog`
- `/api/agent/policies/resolve`

### 6.2 保留已接主链的知识项

优先保留：

- `emotion_levels`
- `emotion_keyword_knowledge`
- `emotion_strategy_knowledge`
- `scene_evidence_knowledge`

因为这 4 类已经真正影响执行结果。

### 6.3 保留知识表结构

保留原因：

- 后面确实要做后台维护
- 这些表天然适合做知识管理
- 不需要再回退成纯代码常量

## 7. 该并线什么

### 7.1 场景证据知识并线

目标：

- Spring Boot / DB 为主
- Python `DEFAULT_SCENE_EVIDENCE` 仅做兜底

### 7.2 情绪知识并线

目标：

- Spring Boot / DB 为主
- Python 默认关键词和默认策略仅做兜底

### 7.3 回复模板知识并线

目标：

- 优先从 `reply_template_knowledge` 读取
- Python `DEFAULT_REPLY_TEMPLATES` 只保留极少数兜底模板

### 7.4 售后方案映射并线

目标：

- 方案定义放知识库
- 商家命中规则放 policy
- Python 不再维护多套方案默认映射

## 8. 该删除或降级什么

### 8.1 不再对外宣传“已经做完 RAG”

建议改口径为：

- 已完成知识库层
- 已完成部分知识驱动执行
- RAG 检索链尚未正式接入

### 8.2 删除重复的业务中文常量

后续应逐步删掉这些重复内容：

- Python 默认回复模板中的中文大段文案
- Python 默认场景证据中文表
- 与知识库重复的中文术语表

前提是对应知识已经稳定从 Spring Boot / DB 下发。

### 8.3 删除乱码种子和乱码文档的继续扩散

原则：

- 旧乱码文件可暂留，不继续复制
- 新增文档、seed、JSON 全部只用 UTF-8 干净内容

## 9. 哪些先不要硬做成 RAG

以下内容现在更适合先做“知识库化”，不必急着上检索：

- 情绪等级
- 情绪关键词
- 情绪策略
- 场景证据
- 售后方案定义
- 回复模板

原因很简单：

- 它们更像配置和知识字典
- 不需要向量检索
- 用结构化读取更稳定

## 10. 哪些后面适合真正做 RAG

以下内容更适合进入真正的检索增强链：

- FAQ 知识
- 售后政策知识
- 商品知识
- 回复说明类知识
- 评价/舆情解释知识

原因：

- 内容长
- 文本型强
- 更新频繁
- 更适合“检索片段 + 引用回答”

## 11. 推荐目标架构

### 11.1 执行知识层

只放会直接影响 agent 判断的结构化知识：

- 情绪等级
- 情绪关键词
- 情绪策略
- 场景证据
- 方案定义
- 商家策略字段定义

执行方式：

- Spring Boot / DB 下发
- Python 结构化读取
- 不走向量检索

### 11.2 检索知识层

只放需要给 LLM 检索引用的长文本知识：

- FAQ
- 售后政策
- 商品知识
- 评价解释
- 标准说明话术

执行方式：

- 未来独立做真正 RAG
- 带召回、重排、命中日志

### 11.3 决策执行层

仍由 Python Agent 负责：

- Intent
- Scene
- State
- Evidence
- Risk
- Handoff
- Ticket Planner

### 11.4 业务真相层

仍由 Spring Boot / MySQL 负责：

- 用户
- 商品
- 订单
- 工单
- 会话
- 商家配置
- 知识维护

## 12. 推荐收敛顺序

### 第一阶段

先收拢“执行知识”：

1. `scene_evidence_knowledge`
2. `emotion_levels`
3. `emotion_keyword_knowledge`
4. `emotion_strategy_knowledge`
5. `reply_template_knowledge`

### 第二阶段

再收拢“策略真相源”：

1. `after_sales_scheme_map`
2. 商家策略修改入口
3. policy 版本审计

### 第三阶段

最后再做真正 RAG：

1. FAQ 检索
2. 商品知识检索
3. 售后政策检索
4. 命中片段引用
5. 命中日志和置信度

## 13. 一句话判断当前状态

当前项目不是“RAG 版本太多完全紊乱”，而是：

**知识库层已经成型，但执行层、配置层、未来 RAG 层的边界还没有彻底收口。**

后面整理时，应先把“执行知识”收成一套，再把“检索知识”单独做成真正 RAG。
