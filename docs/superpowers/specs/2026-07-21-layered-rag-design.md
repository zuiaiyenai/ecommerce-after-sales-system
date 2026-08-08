# 智能售后分层 RAG 设计

## 1. 目标与范围

本设计将当前知识导入和检索链路升级为可审核、可追踪、可降级的分层 RAG 系统，覆盖售后政策、FAQ、凭证要求和操作说明等知识类型。

目标链路：

```text
权限与商家硬过滤
        ↓
商品品类、政策版本与有效期过滤
        ↓
场景与意图路由
        ↓
向量 + 关键词混合召回
        ↓
RRF 融合
        ↓
托管 Reranker
        ↓
分类型阈值判断与最终回答
```

本次明确包含：

- 管理端只保留文件上传，不再提供自由文本导入；
- 第一版支持文本型 PDF、MD 和 TXT；
- 扫描版 PDF 和 OCR 不在第一版范围；
- 上传后先解析和预览，管理员确认后再发布；
- 管理员第一阶段只选择商家范围和知识类型；
- 品类、场景、意图按章节推断并在第二阶段确认；
- 版本化政策增加生效时间和失效时间；
- 所有知识类型共用统一检索引擎，但采用不同阈值和安全策略；
- 使用 PostgreSQL Keyword Retrieval，不引入 Elasticsearch；
- Dense 与 Keyword 结果使用 RRF 融合；
- 使用托管 Reranker，失败时降级到 RRF。

本次不包含：

- OCR；
- Elasticsearch；
- 本地 Cross-Encoder 部署；
- 具体 SKU 级知识绑定；
- 将离线小样本结果描述为生产效果。

## 2. 当前实现与差距

当前仓库已经具备：

- Java 管理接口和 `KnowledgeService`；
- `.txt/.md` 文件上传；
- `KnowledgeMetadataPolicy` 受控词表；
- 商家、品类、场景、意图、知识类型和政策版本过滤；
- DashScope `text-embedding-v3` 和 pgvector；
- Dense 与简单 Keyword 路径；
- 过滤放宽和可信政策判断；
- 基础 RAG 离线评测脚本。

当前主要差距：

- 不支持 PDF；
- 上传即进入处理，没有解析后确认阶段；
- 文档只能绑定一组品类、场景和意图，多场景文档会产生错误标注；
- 没有独立 Draft Chunk；
- 没有政策生效和失效时间；
- Keyword 路径主要依赖 `LIKE` 和手工加分；
- Dense 与 Keyword 没有真正的 RRF；
- 当前所谓 Rerank 是启发式加权，不是独立 Reranker；
- 缺少完整的分阶段 Trace、消融评测和阈值校准。

## 3. 架构与职责边界

### 3.1 Java

Java 负责：

- 管理员 JWT 鉴权和商家权限；
- 文件类型、大小、作用域和重复文件校验；
- 文件保存；
- 知识文档、Draft Chunk 和正式 Chunk 的持久化；
- 知识生命周期状态机；
- 管理员修改和发布 CAS；
- 正式索引的原子替换；
- 对外管理 API。

### 3.2 Python

Python 负责：

- PDF、MD、TXT 文本解析；
- 标题和章节感知切片；
- 规则优先的元数据推断；
- 受控模型分类；
- Embedding；
- Dense、Keyword、RRF 和 Rerank 编排；
- 阈值判断所需的检索结果和 Trace。

Python 不拥有知识发布状态，不直接决定文档是否可供正式检索。

### 3.3 前端

前端负责：

- 文件上传；
- 处理状态展示；
- Draft Chunk 预览；
- 低置信度和冲突字段确认；
- 发布与失败重试操作。

前端不维护 canonical 枚举，也不自行判断知识是否已发布。

### 3.4 PostgreSQL

PostgreSQL 继续作为知识检索来源，保存：

- 文档级生命周期与策略元数据；
- 待确认 Draft Chunk；
- 正式 Chunk、Embedding 和检索字段；
- Keyword 索引和 pgvector 索引。

## 4. 两阶段知识导入

### 4.1 第一阶段：上传和解析

管理员只提交：

- 商家范围；
- 知识类型；
- 文件；
- 可选标题，默认使用文件名。

处理流程：

```text
上传文件
→ Java 权限、类型、大小和 content_hash 校验
→ 创建 PROCESSING 文档
→ Python 解析文本并按章节切片
→ 规则优先、模型补充元数据建议
→ Java 保存 Draft Chunks
→ REVIEW_REQUIRED
```

文件支持：

- `.pdf`：只支持存在可提取文本层的 PDF；
- `.md`：保留标题层级；
- `.txt`：按段落和标题特征处理；
- 扫描版、空白、加密或损坏 PDF 返回明确失败原因。

重复文件使用以下持久键识别：

```text
merchant_code + source_type + content_hash
```

重复上传返回已有记录或提示创建新版本，Redis 不承担最终幂等。

### 4.2 Draft Chunk

新增 `knowledge_chunk_draft`，至少保存：

```text
id
document_id
chunk_index
heading_path
page_number
chunk_text
product_categories[]
scenes[]
intents[]
classification_source
classification_confidence
classification_reason
review_required
revision
```

Draft Chunk 不保存正式 Embedding，不参与线上检索。

### 4.3 第二阶段：管理员确认

前端展示：

- 章节标题路径、页码和文本摘要；
- 建议品类、场景和意图；
- 规则命中或模型推断来源；
- 分类置信度和解释；
- 版本化政策的版本、生效时间和失效时间；
- 低置信度、冲突和无法判断项目。

管理员只需处理 `review_required=true` 的项目，也可以主动修正其他建议。

“通用知识”和“未经确认”必须分开：

- Draft 阶段的 `NULL` 表示尚未确认；
- 正式阶段的空数组表示管理员确认适用于全部；
- 正式发布不允许保留未经确认的 `NULL`。

### 4.4 发布状态机

```text
PROCESSING
→ REVIEW_REQUIRED
→ PUBLISHING
→ PUBLISHED
```

失败状态：

```text
PARSE_FAILED
CLASSIFY_FAILED
EMBEDDING_FAILED
```

原有 `status=0/1` 继续表示停用或启用，不与导入生命周期混用。

## 5. 元数据模型

### 5.1 文档级字段

```text
merchant_code
source_type
policy_version
valid_from
valid_to
review_status
status
content_hash
revision
published_revision
```

其中，文档 `revision` 是管理端修改 Draft 时使用的乐观锁版本；`published_revision` 是当前对外服务的正式内容版本。两者允许不同：已发布文档编辑新 Draft 时，`revision` 继续增长，`published_revision` 保持不变。

### 5.2 Chunk 级字段

```text
revision
product_categories[]
scenes[]
intents[]
heading_path
page_number
search_text
```

数组支持一个章节适用于多个品类、场景或意图。正式数组为非空受控值或空数组，不使用未经确认的 `NULL`。

### 5.3 受控分类

入库分类顺序：

```text
标题、章节和显式字段
→ 确定性词典和映射规则
→ 对仍未确定的字段执行模型分类
→ 校验模型输出必须属于受控词表
→ 输出 value、confidence、reason
→ 低置信度或冲突项交给管理员
```

Java `KnowledgeMetadataPolicy` 是 canonical value 的最终校验入口。模型不能创建新枚举。

## 6. 查询路由与过滤

### 6.1 业务上下文来源

有订单或工单上下文时：

- 商家来自订单归属；
- 商品品类来自订单商品；
- 场景由售后原因确定性映射；
- 意图由退款、换货或补发等售后类型映射；
- 时间点优先使用售后申请时间，历史政策解释使用订单创建时间；
- 知识类型由当前 Agent 工具用途决定。

普通 FAQ 缺少业务上下文时，分类器可以输出场景和意图候选；低置信度候选不作为硬过滤条件。

### 6.2 过滤顺序

```text
document.published_revision IS NOT NULL
+ chunk.revision = document.published_revision
+ enabled + not deleted
→ 当前商家 + GLOBAL
→ knowledge source type
→ policy version + valid time range
→ product categories
→ scenes + intents
→ hybrid candidate retrieval
```

### 6.3 有效期

版本化政策满足：

```text
valid_from <= as_of_time
AND (valid_to IS NULL OR as_of_time < valid_to)
```

时间点规则：

- 售后工单：售后申请时间；
- 历史订单政策解释：订单创建时间；
- 无业务时间点的普通咨询：当前时间，只能形成一般性说明。

历史政策不删除，通过有效期参与历史审计和旧订单解释。

### 6.4 放宽边界

绝不放宽：

- 权限；
- 商家；
- 发布、启用和删除状态；
- 政策版本；
- 政策有效期。

受控放宽：

1. 严格品类、场景、意图；
2. 放宽品类，保留场景和意图；
3. 放宽场景，保留品类和意图；
4. 只有非政策知识允许继续放宽意图。

每次放宽记录 `filter_level`。放宽过滤命中的政策不能进入可信自动审核。

本次商品过滤只做到品类级。当前仓库没有知识与具体 SKU 的可靠关系，因此不虚构 SKU 精确过滤。

## 7. 混合召回

### 7.1 Dense

Dense 路径继续使用：

- DashScope `text-embedding-v3`；
- 1024 维向量；
- pgvector cosine distance；
- 严格过滤后的 Top20 候选。

### 7.2 Keyword

Keyword 路径使用 PostgreSQL `pg_trgm`：

- 将标题路径、Chunk 正文和标签组成规范化 `search_text`；
- 使用 GIN trigram 索引；
- 标题、标签和完整短语命中加权；
- 使用与 Dense 完全相同的过滤条件；
- 返回 Top20 候选。

该实现称为 PostgreSQL Keyword Retrieval，不称为标准 BM25。若离线评测证明 Keyword Recall 不足，再单独评估 Elasticsearch。

### 7.3 RRF

Dense 与 Keyword 分数量纲不同，不直接相加。按 `chunk_id` 去重并使用：

```text
RRF(chunk) =
    1 / (60 + dense_rank)
  + 1 / (60 + keyword_rank)
```

每个候选记录：

```text
dense_rank
dense_score
keyword_rank
keyword_score
rrf_score
retrieval_channels
```

融合后保留 Top20 进入 Reranker。

## 8. 托管 Reranker

统一接口：

```python
class Reranker:
    def rerank(query, candidates, top_n) -> RerankResult
```

配置：

```text
RERANK_PROVIDER
RERANK_MODEL
RERANK_TIMEOUT_SECONDS
RERANK_MAX_RETRIES
RERANK_MAX_CANDIDATES
```

可靠性要求：

- 最大候选数为 20；
- 使用短超时；
- 只对可恢复错误重试一次；
- Semaphore 限制并发；
- 连续失败触发熔断；
- 超时、限流或熔断时使用 RRF 顺序；
- 不使用通用 LLM 冒充 Reranker。

结果模式：

```text
hybrid_reranked
hybrid_rrf_degraded
vector_only_reranked
keyword_only_reranked
no_answer
```

## 9. 阈值与回答策略

阈值配置化，第一版保守默认值：

| 类型 | 最低 Rerank 分数 | 低于阈值 |
|---|---:|---|
| 售后政策 | 0.75 | 不形成可信政策，转人工 |
| 凭证要求 | 0.65 | 使用通用补证提示或转人工 |
| FAQ/操作说明 | 0.60 | 询问澄清，不直接回答 |

上述值是待 Holdout 校准的初始工程值，不是线上最优指标。

政策可信结果还必须满足：

- 严格商家过滤；
- 严格版本和有效期；
- 未放宽品类或场景；
- Reranker 成功；
- 分数达到阈值；
- 引用可以追踪到文档、章节和页码。

Reranker 降级到 RRF 后可以生成一般性辅助说明，但不能触发可信政策自动审核。

## 10. 管理 API 与并发控制

API：

```text
POST /admin/knowledge/file-import
GET  /admin/knowledge/{documentId}/ingestion-status
GET  /admin/knowledge/{documentId}/draft
PUT  /admin/knowledge/{documentId}/draft
PUT  /admin/knowledge/{documentId}/draft/chunks/{chunkId}
POST /admin/knowledge/{documentId}/publish
POST /admin/knowledge/{documentId}/retry
```

文档级 Draft 更新政策版本、生效时间和失效时间；Chunk 级 Draft 更新品类、场景和意图。两类 Draft 修改和发布都携带 `expectedRevision`。发布 CAS：

```sql
UPDATE knowledge_document
SET review_status = 'PUBLISHING',
    revision = revision + 1
WHERE id = ?
  AND review_status = 'REVIEW_REQUIRED'
  AND revision = ?
```

CAS 失败返回当前状态和最新 revision，不重复执行发布。

`review_status` 表示当前导入或更新任务的处理进度，`published_revision` 表示正在对外服务的正式版本。新文档首次发布前 `published_revision` 为 `NULL`；已发布文档开始新一轮解析时可以进入 `PROCESSING`，但旧 `published_revision` 继续被检索。

CAS 成功后得到 `targetRevision = expectedRevision + 1`。发布过程冻结并读取 `expectedRevision` 对应的 Draft 快照，生成的正式 Chunk 统一写入 `targetRevision`；后续状态更新必须同时匹配 `targetRevision`，避免旧任务完成后覆盖更新任务。

## 11. 原子发布

发布步骤：

1. 校验所有待确认项已经处理；
2. 读取并冻结 `expectedRevision` 对应的 Draft；
3. 调用 Python 批量生成全部 Embedding；
4. 全部成功后开启 PostgreSQL 事务；
5. 批量插入 `revision = targetRevision` 的正式 Chunk；
6. 更新文档元数据并把 `published_revision` 切换为 `targetRevision`；
7. 以 `review_status = PUBLISHING AND revision = targetRevision` 为条件将处理状态改为 `PUBLISHED`；
8. 删除非当前 published revision 的旧 Chunk。

上述数据库操作位于同一 PostgreSQL 事务中。Embedding 失败不删除旧索引；事务提交前的查询继续看到旧 `published_revision`，提交后的查询只看到新 revision。更新知识时，旧版本持续服务，直到新版本完整发布。

## 12. 失败恢复

| 故障 | 处理 |
|---|---|
| 空白或扫描版 PDF | `PARSE_FAILED`，提示不支持 OCR |
| PDF 损坏或加密 | `PARSE_FAILED`，记录明确错误类型 |
| 元数据模型不可用 | 保存规则结果，其余标记为待人工确认 |
| 模型输出非法枚举 | 丢弃非法值，不进入正式数据 |
| Embedding 部分失败 | `EMBEDDING_FAILED`，不发布部分向量 |
| 重复发布 | CAS 失败，返回当前状态 |
| Reranker 超时 | 降级 RRF，记录原因 |
| Dense 失败 | Keyword-only，政策不进入可信结果 |
| Keyword 失败 | Vector-only，降低可信等级 |
| 两路均失败 | `no_answer`，转人工或提示稍后重试 |

## 13. 可观测性

入库 Trace：

```text
trace_id
document_id
file_type
file_size
parse_page_count
draft_chunk_count
rule_classified_count
model_classified_count
manual_review_count
parse_latency_ms
classify_latency_ms
embedding_latency_ms
failure_stage
```

检索 Trace：

```text
query_id
filter_level
merchant/source/version/date filters
dense_candidate_count
keyword_candidate_count
rrf_candidate_count
rerank_candidate_count
retrieval_mode
top_scores
stage_latency_ms
fallback_reason
```

Prometheus 不使用 `document_id`、Query 原文或商家自由文本作为 Label，避免高基数。

## 14. 测试与评测

### 14.1 单元测试

- PDF、MD、TXT 解析；
- 标题感知切片；
- 规则优先和受控模型输出；
- RRF 排名；
- 阈值和降级状态；
- CAS 发布和重复请求。

### 14.2 PostgreSQL 集成测试

- 跨商家知识不命中；
- 没有 published revision、停用和软删除知识不命中；
- 历史订单只命中当时有效政策；
- Chunk 多标签匹配；
- Draft 不进入检索；
- Dense 与 Keyword 使用相同 Filter。

### 14.3 离线评测

评测集覆盖：

- 政策问答；
- 凭证要求；
- FAQ；
- 无答案；
- 跨商家；
- 过期政策；
- 口语、错别字和同义表达。

报告：

```text
Recall@5 / Recall@20
MRR@10
NDCG@5
HitRate@5
Filter Violation Rate
No-answer False Positive Rate
Rerank Uplift
p50 / p95 latency
单次检索模型成本
```

消融对比：

```text
Dense only
Keyword only
Dense + Keyword + RRF
Dense + Keyword + RRF + Reranker
```

安全门槛：

- 跨商家、过期政策和未发布知识的 Filter Violation 必须为 0；
- Reranker 若在 Holdout 上降低 NDCG@5，则默认关闭；
- 当前 18 条小样本只作为链路冒烟测试，不描述为生产召回率。

## 15. 迁移与兼容

- 现有正式 `knowledge_chunk` 保持可查询，迁移期间不中断检索；
- 为文档增加生命周期、有效期、content hash、乐观锁 revision 和 published revision；
- 新增 `knowledge_chunk_draft`；
- 正式 Chunk 增加 `revision`、数组元数据、标题路径、页码和 `search_text`；
- 历史单值品类、场景和意图迁移为单元素数组；
- 历史 `NULL` 只有经过明确规则确认后才迁移为空数组，否则保持待治理状态；
- 新检索器在数据迁移完成并通过安全评测后切换；
- 保留配置开关以便回退到旧检索器。

## 16. 验收标准

功能验收：

- 管理员只能通过 PDF、MD、TXT 导入知识；
- 文件解析后进入预览确认，未发布前不可召回；
- 一份文件的不同章节可以具有不同元数据；
- 有效期能够阻止新旧政策错误命中；
- Dense 与 Keyword 完成真正的 RRF 融合；
- 托管 Reranker 正常精排并能够安全降级；
- 管理端可以处理解析、分类和 Embedding 失败；
- Trace 能说明每个结果经过的 Filter、召回、融合、精排和降级过程。

安全验收：

- 跨商家、过期、未发布、停用和软删除知识零违规命中；
- 放宽过滤或 Reranker 降级的政策结果不能进入可信自动审核；
- 发布 CAS 能阻止重复发布和并发覆盖。

评测验收：

- 输出四组消融结果；
- 明确测试集规模、分布、标注方法和局限；
- 只有 Holdout 指标证明有效时才默认启用 Reranker；
- 不把离线结果外推为大规模线上效果。
