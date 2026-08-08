# 多格式文档结构化切分设计

## 1. 背景与目标

当前知识文件导入链路已经能够解析 PDF、Markdown 和纯文本，并为草稿 Chunk 保存 `heading_path`、`page_number` 及业务分类字段。但现有切分仍以固定字符上限和字符重叠为主：Markdown 仅做基础标题分段，PDF 基本按页处理，普通文本知识还保留 Java 字符滑窗路径。这会切断段落语义、制造重复文本，并导致不同入口的切分结果不一致。

本次优化针对单文件上传，不新增多文件批量上传。目标是同时优化 PDF、Markdown 和 TXT：

1. 先按标题与文档结构建立语义范围。
2. 在同一章节内按段落组合 Chunk。
3. 仅在超过硬上限时，按句子和 Token 递归拆分。
4. 合并同章节内过小且相邻的 Chunk。
5. 为每个 Chunk 保存标题路径、页码范围、内容类型、来源和业务 Metadata。
6. 使用确定性上下文前缀增强 embedding 与全文检索，同时保持引用原文不变。

不在本次范围内：批量上传、OCR、基于 PDF 字号或坐标的版面分析、LLM 生成 Chunk 摘要、Office 文档解析。

## 2. 设计原则

- Java 继续拥有知识文档状态、草稿 revision、人工审核、发布和最终持久化。
- Python Agent 负责文件解析、结构识别、切分和业务分类建议。
- PostgreSQL 中已发布的 `knowledge_chunk` 是知识检索来源；切分失败不得破坏当前已发布 revision。
- 原始 `chunk_text` 只保存文档原文。上下文前缀不得伪装成原文或进入引用正文。
- 结构识别采用确定性规则。识别不确定时降级为普通段落，不通过激进规则猜测标题。
- 不为切分调用远程 LLM，不引入 PDF 版面解析库。

## 3. 方案选择

采用规则驱动的统一结构块方案。

未采用 LangChain 通用 splitter，因为它难以同时保留 PDF 页码范围、Markdown 表格、代码块和完整标题层级。未采用 LLM 语义切分或逐 Chunk 摘要，因为其结果不稳定、可能引入原文外信息，并增加导入成本和失败点。

## 4. 总体架构

```text
PDF / Markdown / TXT
        |
        v
格式解析器
        |
        v
统一 DocumentBlock
        |
        v
章节构建与标题路径继承
        |
        v
段落组合 -> 递归超限拆分 -> 同章节小块合并
        |
        v
确定性上下文与结构 Metadata
        |
        v
Chunk 业务分类建议
        |
        v
Java 草稿审核 -> 发布 -> embedding / 检索
```

建议将当前集中在 `knowledge_ingestion_service.py` 的职责拆为：

```text
knowledge_ingestion/
|-- models.py
|-- token_counter.py
|-- parsers/
|   |-- markdown.py
|   |-- pdf.py
|   `-- plain_text.py
|-- section_builder.py
|-- structured_chunker.py
`-- service.py
```

现有 `KnowledgeIngestionService` 对外接口和 `/api/knowledge/parse` HTTP 端点保持兼容。Java 不感知具体格式解析器。

## 5. 统一结构模型

解析器输出统一的 `DocumentBlock`：

```python
DocumentBlock(
    block_type="paragraph",
    text="...",
    heading_path=["退款政策", "质量问题", "举证要求"],
    page_start=3,
    page_end=3,
    splittable=True,
)
```

支持的基础块类型为 `paragraph`、`list`、`table`、`code` 和 `quote`。标题用于维护标题栈，不作为独立正文 Chunk；标题语义通过 `heading_path` 进入上下文前缀和检索文本。

最终内部 `StructuredChunk` 还应包含块类型集合、估算 Token 数、页码范围和切分策略版本。

## 6. 各格式解析规则

### 6.1 Markdown

- 识别 ATX 标题和 Setext 标题，并维护 1 至 6 级标题栈。
- fenced code block 作为完整结构块，内部的 `#`、空行和列表符号不参与结构识别。
- 连续列表项组成列表块；连续 Markdown 表格行组成表格块；引用行组成引用块。
- 普通文本按空行形成段落。
- Markdown 和 TXT 不伪造页码，`page_start`、`page_end` 和兼容字段 `page_number` 均为 `null`。

### 6.2 PDF

- 继续使用 `pypdf` 按页提取文本，不引入 PyMuPDF 等版面库。
- 根据章节编号、中文序号、独占短行、上下空行等保守规则推断标题。
- 仅当短行在足够多页面的顶部或底部稳定重复时，才作为页眉页脚移除；单页和少页文档不应用高风险删除规则。
- 章节允许跨页延续，Chunk 保存 `page_start` 和 `page_end`。
- 无法可靠识别的标题按普通段落处理。单页提取异常不得被静默忽略。

### 6.3 TXT

- 按空行形成段落。
- 使用与 PDF 相同的保守编号标题规则识别章节。
- 无明确标题时，所有内容归入文档根章节。

## 7. 切分算法

### 7.1 默认参数

参数集中在 `ChunkingConfig`，不得散落为魔法数字：

| 参数 | 默认值 | 用途 |
| --- | ---: | --- |
| `target_tokens` | 500 | 同章节内组合完整结构块时的理想大小 |
| `hard_max_tokens` | 800 | 任意最终 Chunk 的硬上限 |
| `min_merge_tokens` | 150 | 判断相邻小 Chunk 是否需要回并 |
| `hard_max_chars` | 6400 | 防止异常长单词或估算偏差产生超大 Chunk 的安全上限 |
| `chunking_strategy` | `structured_recursive_v1` | 可观测和后续重建所需的策略版本 |

目标大小不是强制切割线。组合完整段落后略高于目标值但未超过硬上限时，可以保留完整段落。硬上限只在递归拆分和最终校验时强制执行。

### 7.2 章节内组合

只组合标题路径、业务分类上下文和来源一致的相邻块。候选组合不超过硬上限时，优先保留完整段落、列表、表格或代码块。不同标题路径之间禁止合并。

### 7.3 递归拆分

单个块超过硬上限时按以下顺序处理：

1. 普通段落和引用按句子边界拆分。
2. 列表按列表项拆分。
3. 表格按数据行拆分，并在子块中重复必要表头。
4. 代码块按代码行拆分。
5. 最小单元仍超限时，按本地 Token 估算单元硬拆。

不再使用固定字符重叠。只有递归边界确实需要上下文时，才允许携带有限的完整句子；标题路径和上下文前缀是主要语境载体。

### 7.4 小块回并

初次切分后，小于 `min_merge_tokens` 的 Chunk 优先与前一个或后一个相邻 Chunk 合并。合并必须同时满足：

- 标题路径相同。
- 来源和业务分类上下文兼容。
- 页码相邻或重叠。
- 合并后不超过硬上限。

无法安全合并的小块保留，不跨章节拼接。

### 7.5 Token 估算

当前项目没有可直接复用且与 Qwen 精确对应的本地 tokenizer。本次实现确定性的本地估算器：CJK 字符、英文数字词和标点分别计数，空白不单独计数，并辅以字符数安全上限。该值命名为 `estimated_tokens`，不得声明为模型精确 Token 数。

切分不得调用远程模型或依赖运行时下载 tokenizer。所有阈值和测试统一使用同一个估算器。

## 8. 确定性上下文增强

每个 Chunk 构造上下文前缀：

```text
文档：平台售后退款规则
章节：退款政策 > 质量问题 > 举证要求
位置：第 3-4 页
来源：policy.pdf / POLICY-2026
内容类型：段落、列表
```

- `chunk_text` 只保存原文。
- `contextualized_text` 是上下文前缀与原文的组合，仅用于 embedding 和全文检索输入。
- 检索结果和 citation 返回原始正文及结构化来源，不把前缀作为文档原文展示。
- 本次不生成 LLM 摘要。未来若评估证明有必要，可按章节生成一次摘要并由章节内 Chunk 共享，不能直接替换原文。

## 9. Metadata 与数据库契约

兼容现有字段：

- `heading_path` 继续使用 PostgreSQL `TEXT[]`。
- `page_number` 继续表示 PDF Chunk 的起始页，兼容旧接口。
- Markdown/TXT 的 `page_number` 改为 `null`，不再伪造第 1 页。
- `product_categories`、`scenes`、`intents` 继续使用现有独立字段。

新增结构信息写入 Chunk JSON Metadata：

```json
{
  "document_id": "42",
  "document_title": "平台售后退款规则",
  "source_type": "after_sales_policy",
  "source_format": "pdf",
  "source_code": "POLICY-2026",
  "file_name": "policy.pdf",
  "revision": 3,
  "chunk_index": 5,
  "heading_path": ["退款政策", "质量问题", "举证要求"],
  "page_start": 3,
  "page_end": 4,
  "content_types": ["paragraph", "list"],
  "estimated_tokens": 486,
  "chunking_strategy": "structured_recursive_v1"
}
```

为保证信息经过草稿审核后不丢失，正式 migration 为 `knowledge_chunk_draft` 增加 `metadata JSONB NOT NULL DEFAULT '{}'::jsonb`。发布时 Java 将草稿结构 Metadata 合并到 `knowledge_chunk.metadata`。

Metadata 合并优先级：

1. Java 文档级业务事实和当前 revision。
2. 人工修改后的草稿分类字段。
3. Python 生成的结构信息。

`source_type` 保持现有知识业务类型语义；新增的 `source_format` 才表示 `pdf`、`markdown` 或 `text`，禁止复用 `source_type` 表示文件格式。Python 不得覆盖 `document_id`、商家、版本、有效期等 Java 拥有的业务事实。任何可能通过 API 到达 JavaScript 的 Java `Long` ID 必须序列化为字符串。

## 10. Java 旧切分路径

文件上传继续调用 Python `/api/knowledge/parse`。Java 中普通文本知识的固定字符滑窗不得继续作为另一套独立算法：文本内容重建时也应调用同一 Python 结构化解析接口，使用合成文件名和 `text/plain` 语义。这样 PDF、Markdown、TXT 和后台文本入口共享同一切分器。

若 Python 解析不可用，处理应失败并保留现有发布 revision，不允许静默回退到字符滑窗后发布不同结构的数据。

## 11. 错误处理与可观测性

- 保留稳定错误码 `PDF_ENCRYPTED`、`PDF_TEXT_LAYER_MISSING`、`FILE_DECODE_FAILED` 和 `UNSUPPORTED_FILE_TYPE`。
- 解析结果为空时返回稳定错误，不创建空草稿。
- 标题识别不足时降级为普通段落，不中断导入。
- 最终校验确保 Chunk 非空、顺序稳定，并满足硬上限。
- 解析、切分、草稿持久化或 embedding 失败均不得覆盖当前已发布 revision。
- 日志记录文档 ID、格式、块数、平均与最大估算 Token 数、标题识别数、跨页 Chunk 数、策略版本和失败码，不记录完整文档正文或密钥。

## 12. 测试与验收

Python 单元测试覆盖：

- Markdown 多级标题、Setext 标题、列表、表格、引用和 fenced code。
- PDF 多页、编号标题、跨页章节、重复页眉页脚及页码范围。
- TXT 有标题与无标题两种情况。
- 未超限时按完整段落组合，不按固定 Token 截断。
- 超长段落按句子拆分，超长单句最终按估算 Token 拆分。
- 表格拆分时保留表头，列表和代码按各自结构边界拆分。
- 同章节小块合并，不同标题路径禁止合并。
- 每个 Chunk 非空、顺序稳定且不超过硬上限。
- 上下文前缀包含标题、章节、页码和来源，但 `chunk_text` 保持原文。

Java 测试覆盖：

- `/api/knowledge/parse` 响应兼容。
- 草稿 Metadata JSONB 持久化。
- 发布时结构 Metadata 与 Java 业务 Metadata 按优先级合并。
- embedding 和 `search_text` 使用上下文增强文本，citation 使用原文。
- `page_number` 兼容，`page_end` 可从 Metadata 追溯。
- 文本入口不再走固定字符滑窗。
- 重新处理失败时，旧发布 revision 仍可检索。

验收基准以固定 PDF、Markdown 和 TXT fixtures 为准。相同输入和配置必须产生相同 Chunk 边界与 Metadata；测试不依赖真实 LLM、远程 tokenizer 或外部网络。

## 13. 迁移与发布顺序

1. 添加正式 PostgreSQL migration，为 `knowledge_chunk_draft` 增加 Metadata JSONB。
2. 实现 Python 统一结构模型、格式解析器、Token 估算器和结构化切分器。
3. 扩展解析响应并保持旧字段兼容。
4. 更新 Java 草稿持久化、发布合并、上下文 embedding 和 citation 逻辑。
5. 将 Java 普通文本入口切换到统一解析链路，并删除固定字符滑窗代码。
6. 完成单元与集成测试后，使用测试文档验证解析草稿，不批量重建现有知识库。

现有已发布 Chunk 不在本次代码发布时自动重切。后续重建必须显式触发，保留 revision 发布安全，并遵守本机 PostgreSQL 数据卷不得擅自批量 reindex 的约束。
