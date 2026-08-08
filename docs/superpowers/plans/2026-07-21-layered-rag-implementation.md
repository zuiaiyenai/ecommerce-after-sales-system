# Layered RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前“上传后立即固定切片并向量化”的知识模块升级为可审核、可版本切换、可分层过滤、可混合召回和可离线评测的售后 RAG 系统。

**Architecture:** Java 继续拥有管理员鉴权、商家范围、知识生命周期、Draft、CAS 和原子发布；Python 负责文档解析、章节切片、受控元数据建议、Embedding、Dense/Keyword/RRF/Rerank；PostgreSQL 同时保存 Draft 和正式检索数据；Vue 管理端只负责文件上传、预览确认和发布。正式查询只读取 `knowledge_chunk.revision = knowledge_document.published_revision`，因此更新失败时旧发布版本仍可服务。

**Tech Stack:** Java 21、Spring Boot、JdbcTemplate、PostgreSQL 16、pgvector、pg_trgm、Python 3.11、pypdf、psycopg 3、DashScope `text-embedding-v3`、可配置托管 Reranker、Vue 3、Vite、JUnit 5、pytest、Node test runner。

## Global Constraints

- AI 只推断知识标签和相关性，不拥有知识发布状态或售后业务状态。
- Java 是知识导入生命周期和发布操作的唯一写入口；Python 不直接切换 `review_status` 或 `published_revision`。
- PostgreSQL 是知识检索来源；MySQL、Redis 和 Kafka 不承担知识正文或知识发布状态。
- 第一版只接受文本型 `.pdf`、`.md`、`.txt`；扫描版、空白、加密或损坏 PDF 返回明确解析失败，不实现 OCR。
- 管理员上传时只提供商家范围、知识类型、可选标题和文件；品类、场景、意图在章节级推断后确认。
- Java `KnowledgeMetadataPolicy` 是品类、场景、意图 canonical value 的最终校验入口；模型不能创建新枚举。
- `NULL` 表示 Draft 尚未确认；正式 Chunk 的空数组表示管理员确认该维度为通用知识。
- 权限、商家、发布状态、启用状态、删除状态、政策版本和有效期永不放宽。
- 商品过滤只到品类级，不增加当前仓库不存在的 SKU 知识绑定。
- Dense 和 Keyword 各取 Top20，RRF 常量 `k=60`，融合 Top20 进入 Reranker。
- 初始 Rerank 阈值为政策 `0.75`、凭证要求 `0.65`、FAQ/操作说明 `0.60`；这些是待 Holdout 校准的工程默认值，不描述为线上最优指标。
- Reranker 超时、限流、熔断或不可用时降级为 RRF；降级结果不能驱动可信政策自动审核。
- 所有返回到 Vue/JavaScript 的 Java `Long` ID 必须序列化为 JSON 字符串。
- 保留旧检索器配置开关；数据迁移和安全评测通过前不删除旧字段和旧检索路径。

---

## File Structure

### PostgreSQL

- Create `sql/migrations/20260721_add_layered_rag_lifecycle.sql`: 生命周期、有效期、Draft、Chunk revision、数组元数据、pg_trgm 和索引迁移。
- Modify `sql/pgvector_schema.sql`: 新环境直接创建最终结构。
- Create `src/test/java/com/ecommerce/aftersales/integration/PostgresRagIntegrationSupport.java`: 统一启动 pgvector PostgreSQL Testcontainer 并加载 schema。
- Create `src/test/java/com/ecommerce/aftersales/integration/LayeredRagSchemaIntegrationTest.java`: 用 PostgreSQL Testcontainers 验证约束、索引和版本可见性。

### Java

- Create `src/main/java/com/ecommerce/aftersales/common/enums/KnowledgeReviewStatus.java`: 唯一生命周期枚举。
- Create `src/main/java/com/ecommerce/aftersales/common/KnowledgeRevisionConflictException.java`: 携带当前 revision 和 review status 的 409 冲突。
- Create `src/main/java/com/ecommerce/aftersales/dto/KnowledgeDraftDtos.java`: 文件导入、状态、Draft、Chunk 编辑、发布和重试契约。
- Create `src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java`: Draft 查询、受控字段校验和乐观锁修改。
- Create `src/main/java/com/ecommerce/aftersales/service/KnowledgePublishService.java`: 发布 CAS 和 PostgreSQL 原子版本切换。
- Modify `src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java`: 调 Python 解析服务并落 Draft；发布时调用 Embedding 后交给发布服务提交。
- Modify `src/main/java/com/ecommerce/aftersales/service/KnowledgeService.java`: 文件校验、content hash、列表/详情兼容和任务入口。
- Modify `src/main/java/com/ecommerce/aftersales/controller/KnowledgeManagementController.java`: 对外暴露设计规格中的管理 API。
- Modify `src/main/java/com/ecommerce/aftersales/dto/KnowledgeUploadDto.java`: 列表/详情补充 revision、published revision、有效期和审核状态。
- Modify `src/main/resources/application.yml` and `application-local.example.yml`: 文件限制、分层 RAG 开关和内部超时配置。

### Python

- Create `python_agent/after_sales_agent/application/knowledge_ingestion_service.py`: PDF/MD/TXT 解析、标题路径切片和受控分类建议。
- Create `python_agent/after_sales_agent/retrieval/knowledge_filters.py`: 单一来源的严格过滤与受控放宽计划。
- Create `python_agent/after_sales_agent/retrieval/rrf.py`: 纯函数 RRF 融合。
- Create `python_agent/after_sales_agent/providers/reranker_client.py`: 托管 Reranker 的超时、一次重试、Semaphore、熔断和结果归一化。
- Modify `python_agent/after_sales_agent/retrieval/pgvector_retriever.py`: 只保留编排、Embedding 和数据库候选查询，接入上述组件。
- Modify `python_agent/after_sales_agent/application/knowledge_admin_service.py`: 暴露 parse/classify 和新版检索响应。
- Modify `python_agent/after_sales_agent/api/http_server.py`: 增加受内部 Token 保护的 `/api/knowledge/parse`。
- Modify `python_agent/after_sales_agent/application/after_sales_workflow.py`: 只信任严格过滤、Reranker 成功且过阈值的政策结果。
- Modify `python_agent/requirements.txt`: 增加 `pypdf`。

### Vue 管理端

- Modify `frontend/staff-auth-test-ui/src/api/adminConsole.js`: 新增状态、Draft、编辑、发布和重试 API。
- Modify `frontend/staff-auth-test-ui/src/components/KnowledgeImportModal.vue`: 只保留文件上传第一阶段。
- Create `frontend/staff-auth-test-ui/src/components/KnowledgeDraftReviewPanel.vue`: 章节预览、低置信度字段确认、有效期和发布。
- Create `frontend/staff-auth-test-ui/src/api/knowledgeDraft.js`: Draft 纯函数映射和发布前校验。
- Modify `frontend/staff-auth-test-ui/src/views/AdminKnowledgeView.vue`: 状态轮询、Review 面板和发布/重试流程。
- Modify `frontend/staff-auth-test-ui/package.json`: 让知识契约测试进入统一 test script。

### Evaluation and operations

- Create `python_agent/evaluation/rag_retrieval_cases.jsonl`: 带 relevant chunk、无答案、跨商家和过期政策标注的 Holdout 格式。
- Create `python_agent/after_sales_agent/evaluation/rag_metrics.py`: Recall、MRR、NDCG、HitRate、过滤违规和无答案误报纯函数。
- Replace `tools/evaluate_rag_recall.py`: 输出四组消融、延迟和成本口径，不再把 18 条冒烟集称为生产召回率。
- Modify `compose.yml`, `python_agent/.env.example`, `.github/workflows/ci.yml`, `.github/workflows/nightly-smoke.yml`: Reranker 配置、数据库迁移和离线质量门禁。
- Modify `docs/rag-recall-baseline.md`: 标注旧结果适用范围，并链接新评测报告格式。

---

### Task 1: PostgreSQL 生命周期、Draft 与版本可见性

**Files:**
- Create: `sql/migrations/20260721_add_layered_rag_lifecycle.sql`
- Modify: `sql/pgvector_schema.sql:1-50`
- Create: `src/test/java/com/ecommerce/aftersales/integration/PostgresRagIntegrationSupport.java`
- Create: `src/test/java/com/ecommerce/aftersales/integration/LayeredRagSchemaIntegrationTest.java`

**Interfaces:**
- Produces: `knowledge_document.review_status/revision/published_revision/valid_from/valid_to/content_hash`。
- Produces: `knowledge_chunk_draft` 和带 `revision`、数组标签、引用字段、`search_text` 的正式 `knowledge_chunk`。
- Produces: `published_knowledge_chunk` 只暴露启用、未删除且 `chunk.revision = document.published_revision` 的正式 Chunk。
- Consumes: 现有 `knowledge_document`、`knowledge_chunk` 数据；旧单值过滤列迁移期间保留。

- [ ] **Step 1: 写失败的 PostgreSQL 集成测试**

```java
@Testcontainers(disabledWithoutDocker = true)
abstract class PostgresRagIntegrationSupport {
    @Container
    static final GenericContainer<?> POSTGRES = new GenericContainer<>("pgvector/pgvector:pg16")
            .withEnv("POSTGRES_DB", "after_sales_rag")
            .withEnv("POSTGRES_USER", "postgres")
            .withEnv("POSTGRES_PASSWORD", "postgres")
            .withExposedPorts(5432)
            .waitingFor(Wait.forListeningPort());

    static JdbcTemplate jdbc;

    @BeforeAll
    static void initializeSchema() throws Exception {
        PGSimpleDataSource dataSource = new PGSimpleDataSource();
        dataSource.setURL("jdbc:postgresql://" + POSTGRES.getHost() + ":" + POSTGRES.getMappedPort(5432) + "/after_sales_rag");
        dataSource.setUser("postgres");
        dataSource.setPassword("postgres");
        jdbc = new JdbcTemplate(dataSource);
        try (Connection connection = dataSource.getConnection()) {
            ScriptUtils.executeSqlScript(connection,
                    new EncodedResource(new FileSystemResource("sql/pgvector_schema.sql"), StandardCharsets.UTF_8));
        }
    }
}

class LayeredRagSchemaIntegrationTest extends PostgresRagIntegrationSupport {
@Test
void onlyPublishedRevisionIsVisibleAndDraftHasNoEmbedding() {
    jdbc.update("INSERT INTO knowledge_document(id, source_type, source_code, merchant_code, title, content, review_status, revision, published_revision) VALUES (9001,'faq','T-1','MERCHANT_DEMO','标题','正文','PROCESSING',2,1)");
    jdbc.update("INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding, revision, product_categories, scenes, intents, search_text) VALUES (9001,'faq',0,'旧版本',?::vector,1,'{}','{}','{}','旧版本')", zeroVector());
    jdbc.update("INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text, embedding, revision, product_categories, scenes, intents, search_text) VALUES (9001,'faq',0,'新版本',?::vector,2,'{}','{}','{}','新版本')", zeroVector());

    List<String> visible = jdbc.queryForList("SELECT kc.chunk_text FROM knowledge_chunk kc JOIN knowledge_document kd ON kd.id=kc.document_id WHERE kc.revision=kd.published_revision", String.class);

    assertThat(visible).contains("旧版本").doesNotContain("新版本");
    assertThat(columns("knowledge_chunk_draft")).doesNotContain("embedding");
}

private String zeroVector() {
    return "[" + String.join(",", Collections.nCopies(1024, "0")) + "]";
}

private List<String> columns(String table) {
    return jdbc.queryForList("SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position", String.class, table);
}
}
```

- [ ] **Step 2: 运行测试确认旧结构失败**

Run: `.\mvnw.cmd -Dtest=LayeredRagSchemaIntegrationTest test`

Expected: FAIL，错误包含缺少 `review_status` 或 `knowledge_chunk_draft`。

- [ ] **Step 3: 编写幂等迁移和最终 schema**

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE knowledge_document
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'PUBLISHED',
    ADD COLUMN IF NOT EXISTS content_hash CHAR(64) NULL,
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS published_revision BIGINT NULL;

ALTER TABLE knowledge_chunk
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS product_categories TEXT[] NULL,
    ADD COLUMN IF NOT EXISTS scenes TEXT[] NULL,
    ADD COLUMN IF NOT EXISTS intents TEXT[] NULL,
    ADD COLUMN IF NOT EXISTS heading_path TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS page_number INTEGER NULL,
    ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS knowledge_chunk_draft (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES knowledge_document(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    page_number INTEGER NULL,
    chunk_text TEXT NOT NULL,
    product_categories TEXT[] NULL,
    scenes TEXT[] NULL,
    intents TEXT[] NULL,
    classification_source VARCHAR(16) NOT NULL,
    classification_confidence NUMERIC(5,4) NULL,
    classification_reason TEXT NULL,
    review_required BOOLEAN NOT NULL DEFAULT TRUE,
    revision BIGINT NOT NULL,
    UNIQUE(document_id, chunk_index)
);

UPDATE knowledge_document kd
SET published_revision = 1
WHERE published_revision IS NULL
  AND EXISTS (SELECT 1 FROM knowledge_chunk kc WHERE kc.document_id = kd.id);

UPDATE knowledge_chunk kc
SET product_categories = ARRAY[kd.product_category]
FROM knowledge_document kd
WHERE kc.document_id = kd.id
  AND kc.product_categories IS NULL
  AND kd.product_category IS NOT NULL;

UPDATE knowledge_chunk kc
SET scenes = ARRAY[kd.scene]
FROM knowledge_document kd
WHERE kc.document_id = kd.id
  AND kc.scenes IS NULL
  AND kd.scene IS NOT NULL;

UPDATE knowledge_chunk kc
SET intents = ARRAY[kd.intent]
FROM knowledge_document kd
WHERE kc.document_id = kd.id
  AND kc.intents IS NULL
  AND kd.intent IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uk_kc_document_revision_index
    ON knowledge_chunk(document_id, revision, chunk_index);
CREATE INDEX IF NOT EXISTS idx_kc_product_categories ON knowledge_chunk USING GIN(product_categories);
CREATE INDEX IF NOT EXISTS idx_kc_scenes ON knowledge_chunk USING GIN(scenes);
CREATE INDEX IF NOT EXISTS idx_kc_intents ON knowledge_chunk USING GIN(intents);
CREATE INDEX IF NOT EXISTS idx_kc_search_text_trgm ON knowledge_chunk USING GIN(search_text gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS uk_kd_active_content_hash
    ON knowledge_document(merchant_code, source_type, content_hash)
    WHERE content_hash IS NOT NULL AND COALESCE(metadata ->> 'deleted','false') <> 'true';
```

为 `valid_to` 增加 `CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)`，并把同样定义同步到 `sql/pgvector_schema.sql`。

- [ ] **Step 4: 运行 schema 集成测试**

Run: `.\mvnw.cmd -Dtest=LayeredRagSchemaIntegrationTest test`

Expected: PASS；重复应用迁移仍 PASS。

- [ ] **Step 5: 提交**

```powershell
git add sql/migrations/20260721_add_layered_rag_lifecycle.sql sql/pgvector_schema.sql src/test/java/com/ecommerce/aftersales/integration/PostgresRagIntegrationSupport.java src/test/java/com/ecommerce/aftersales/integration/LayeredRagSchemaIntegrationTest.java
git commit -m "feat: add layered RAG lifecycle schema"
```

### Task 2: Python 文档解析、章节切片与受控元数据建议

**Files:**
- Create: `python_agent/after_sales_agent/application/knowledge_ingestion_service.py`
- Create: `python_agent/tests/test_knowledge_ingestion_service.py`
- Modify: `python_agent/after_sales_agent/application/knowledge_admin_service.py:9-116`
- Modify: `python_agent/after_sales_agent/api/http_server.py:400-439,699-726`
- Modify: `python_agent/requirements.txt`

**Interfaces:**
- Consumes: `parse(file_name, content_base64, knowledge_type, allowed_metadata)`。
- Produces: `ParseResult(content, policy_version, valid_from, valid_to, chunks)`；每个 Chunk 含 `heading_path/page_number/text/product_categories/scenes/intents/source/confidence/reason/review_required`。
- Depends on: Java 传入的 canonical `allowed_metadata`，Python 不持有第二套枚举真相。

- [ ] **Step 1: 写解析和分类失败测试**

```python
class FakeClassifier:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def classify(self, **_kwargs: object) -> dict[str, object]:
        return self.response

def test_markdown_sections_keep_heading_path_and_unknown_metadata_requires_review():
    service = KnowledgeIngestionService(classifier=FakeClassifier({"scenes": ["made_up"]}))
    result = service.parse(
        file_name="policy.md",
        content=b"# 退款\n## 质量问题\n功能异常可申请退款。",
        knowledge_type="after_sales_policy",
        allowed_metadata={"product_categories": ["headphone"], "scenes": ["quality_issue"], "intents": ["refund"]},
    )
    assert result.chunks[0].heading_path == ["退款", "质量问题"]
    assert result.chunks[0].scenes is None
    assert result.chunks[0].review_required is True

def test_scanned_pdf_is_rejected_without_ocr():
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)
    with pytest.raises(KnowledgeParseError, match="PDF_TEXT_LAYER_MISSING"):
        KnowledgeIngestionService().parse(file_name="scan.pdf", content=buffer.getvalue(), knowledge_type="faq", allowed_metadata={})
```

- [ ] **Step 2: 运行测试确认服务不存在**

Run: `cd python_agent; python -m pytest tests/test_knowledge_ingestion_service.py -q`

Expected: FAIL with `ModuleNotFoundError: knowledge_ingestion_service`。

- [ ] **Step 3: 实现解析模型和结构感知切片**

```python
@dataclass(frozen=True)
class DraftChunk:
    chunk_index: int
    heading_path: list[str]
    page_number: int | None
    text: str
    product_categories: list[str] | None
    scenes: list[str] | None
    intents: list[str] | None
    classification_source: str
    classification_confidence: float | None
    classification_reason: str | None
    review_required: bool

@dataclass(frozen=True)
class ParseResult:
    content: str
    policy_version: str | None
    valid_from: str | None
    valid_to: str | None
    chunks: list[DraftChunk]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

class KnowledgeIngestionService:
    def parse(self, *, file_name: str, content: bytes, knowledge_type: str, allowed_metadata: dict[str, list[str]]) -> ParseResult:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".pdf":
            pages = self._pdf_pages(content)
        elif suffix in {".md", ".txt"}:
            pages = [(1, content.decode("utf-8-sig"))]
        else:
            raise KnowledgeParseError("UNSUPPORTED_FILE_TYPE")
        sections = self._sections(suffix, pages)
        chunks = self._chunk_sections(sections, max_chars=700, overlap_chars=120)
        return self._classify(chunks, knowledge_type, allowed_metadata)
```

切片必须优先在标题、段落、句号边界截断；一个 Chunk 不跨越顶级章节；PDF 保留起始页码。先用集中式规则函数映射明确标题和短语，只把仍为 `None` 的字段交给 `OpenAICompatibleClient.chat_json`，并在返回后与 Java 传入词表求交集。模型不可用时保留规则结果，未知项 `review_required=true`。

- [ ] **Step 4: 增加内部 parse API**

```python
def parse_document(self, data: dict[str, Any]) -> dict[str, Any]:
    raw = base64.b64decode(str(data["content_base64"]), validate=True)
    result = self.ingestion.parse(
        file_name=str(data["file_name"]),
        content=raw,
        knowledge_type=str(data["knowledge_type"]),
        allowed_metadata=dict(data.get("allowed_metadata") or {}),
    )
    return result.to_dict()
```

在 `http_server.py` 注册 `POST /api/knowledge/parse`，复用现有 `X-Agent-Internal-Token` 校验；错误分别返回 `UNSUPPORTED_FILE_TYPE`、`PDF_ENCRYPTED`、`PDF_TEXT_LAYER_MISSING`、`FILE_DECODE_FAILED`。

- [ ] **Step 5: 运行 Python 测试**

Run: `cd python_agent; python -m pytest tests/test_knowledge_ingestion_service.py tests/test_http_request_body.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add python_agent/requirements.txt python_agent/after_sales_agent/application/knowledge_ingestion_service.py python_agent/after_sales_agent/application/knowledge_admin_service.py python_agent/after_sales_agent/api/http_server.py python_agent/tests/test_knowledge_ingestion_service.py
git commit -m "feat: parse and classify knowledge drafts"
```

### Task 3: Java 文件导入与 Draft 生命周期

**Files:**
- Create: `src/main/java/com/ecommerce/aftersales/common/enums/KnowledgeReviewStatus.java`
- Create: `src/main/java/com/ecommerce/aftersales/dto/KnowledgeDraftDtos.java`
- Create: `src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java`
- Modify: `src/main/java/com/ecommerce/aftersales/service/KnowledgeService.java:62-183,399-438,505-528`
- Modify: `src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java:48-188`
- Modify: `src/main/java/com/ecommerce/aftersales/controller/KnowledgeManagementController.java:21-67`
- Modify: `src/main/java/com/ecommerce/aftersales/dto/KnowledgeUploadDto.java:12-89`
- Test: `src/test/java/com/ecommerce/aftersales/service/KnowledgeDraftServiceTest.java`
- Test: `src/test/java/com/ecommerce/aftersales/controller/KnowledgeManagementControllerTest.java`

**Interfaces:**
- Produces: `POST /admin/knowledge/file-import`、`GET /{id}/ingestion-status`、`GET /{id}/draft`、`POST /{id}/retry`。
- Consumes: Python `/api/knowledge/parse` 响应。
- Produces: `documentId` 使用 `@JsonSerialize(ToStringSerializer.class)`，前端收到字符串。

- [ ] **Step 1: 写 Controller 契约失败测试**

```java
@Test
void fileImportOnlyAcceptsPdfMarkdownAndTextAndReturnsStringId() throws Exception {
    when(knowledgeService.createFileImport(any())).thenReturn(new FileImportResponse(42L, "PROCESSING", false));
    mockMvc.perform(multipart("/admin/knowledge/file-import")
            .file(new MockMultipartFile("file", "policy.pdf", "application/pdf", "%PDF".getBytes()))
            .param("knowledgeType", "after_sales_policy")
            .param("scope", "MERCHANT")
            .param("merchantCode", "MERCHANT_DEMO"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.data.documentId").value("42"));
}
```

再添加 `.docx` 返回 400、相同 content hash 返回已有 ID 且 `duplicate=true`、未发布 Draft 不出现在可检索状态的测试。

- [ ] **Step 2: 运行 Java 测试确认契约失败**

Run: `.\mvnw.cmd -Dtest=KnowledgeManagementControllerTest,KnowledgeDraftServiceTest test`

Expected: FAIL，缺少新 DTO、端点和服务。

- [ ] **Step 3: 定义生命周期和 DTO**

```java
public enum KnowledgeReviewStatus {
    PROCESSING, REVIEW_REQUIRED, PUBLISHING, PUBLISHED,
    PARSE_FAILED, CLASSIFY_FAILED, EMBEDDING_FAILED
}

public record FileImportResponse(
        @JsonSerialize(using = ToStringSerializer.class) Long documentId,
        String reviewStatus,
        boolean duplicate
) {}

public record FileImportCommand(
        String title,
        String knowledgeType,
        String scope,
        String merchantCode,
        MultipartFile file
) {}

public record DraftChunkResponse(
        @JsonSerialize(using = ToStringSerializer.class) Long chunkId,
        int chunkIndex,
        List<String> headingPath,
        Integer pageNumber,
        String text,
        List<String> productCategories,
        List<String> scenes,
        List<String> intents,
        String classificationSource,
        BigDecimal confidence,
        String reason,
        boolean reviewRequired,
        long revision
) {}
```

- [ ] **Step 4: 实现文件入口和重复文件规则**

`KnowledgeService.createFileImport` 只接收标题可选、知识类型、scope、merchant 和文件。标题为空时使用去掉扩展名的原文件名。文件名规范化后校验后缀与 MIME；保存时计算 SHA-256。查询相同 `merchant_code + source_type + content_hash` 的未删除文档，命中则返回原 ID，不创建新异步任务。新记录初始 `review_status=PROCESSING`、`revision=1`、`published_revision=NULL`。

```java
@PostMapping(value = "/file-import", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
public ApiResponse<FileImportResponse> fileImport(
        @RequestParam String knowledgeType,
        @RequestParam(defaultValue = "MERCHANT") String scope,
        @RequestParam(required = false) String merchantCode,
        @RequestParam(required = false) String title,
        @RequestPart MultipartFile file) {
    return ApiResponse.success("文件导入任务已创建", knowledgeService.createFileImport(
            new FileImportCommand(title, knowledgeType, scope, merchantCode, file)));
}
```

删除管理端公开的 `/import/text`、`/upload` 和 `/batch-upload` Controller 映射；Service 兼容方法先保留为 package-private 迁移辅助，不再对外暴露。

- [ ] **Step 5: 异步解析并持久化 Draft**

`KnowledgeIngestionAsyncService.processFileImport` 读取最多 10MB 文件，Base64 调用 `/api/knowledge/parse`。在一个 PostgreSQL 事务中删除当前 Draft、批量插入新 Draft、保存解析正文/有效期建议，并条件更新：

```sql
UPDATE knowledge_document
SET content = ?, valid_from = ?, valid_to = ?, review_status = 'REVIEW_REQUIRED', updated_at = NOW()
WHERE id = ? AND revision = ? AND review_status = 'PROCESSING'
```

解析失败只更新 `review_status` 和结构化 `error_code/error_message`，不改 `published_revision`。已发布文档重试解析时，旧正式 revision 继续可检索。

- [ ] **Step 6: 运行 Java 测试**

Run: `.\mvnw.cmd -Dtest=KnowledgeManagementControllerTest,KnowledgeServiceTest,KnowledgeIngestionAsyncServiceTest,KnowledgeDraftServiceTest test`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/main/java/com/ecommerce/aftersales/common/enums/KnowledgeReviewStatus.java src/main/java/com/ecommerce/aftersales/dto/KnowledgeDraftDtos.java src/main/java/com/ecommerce/aftersales/dto/KnowledgeUploadDto.java src/main/java/com/ecommerce/aftersales/controller/KnowledgeManagementController.java src/main/java/com/ecommerce/aftersales/service/KnowledgeService.java src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java src/test/java/com/ecommerce/aftersales/controller/KnowledgeManagementControllerTest.java src/test/java/com/ecommerce/aftersales/service/KnowledgeDraftServiceTest.java src/test/java/com/ecommerce/aftersales/service/KnowledgeServiceTest.java src/test/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncServiceTest.java
git commit -m "feat: add reviewable knowledge drafts"
```

### Task 4: Draft 编辑、CAS 和原子发布

**Files:**
- Create: `src/main/java/com/ecommerce/aftersales/common/KnowledgeRevisionConflictException.java`
- Create: `src/main/java/com/ecommerce/aftersales/service/KnowledgePublishService.java`
- Modify: `src/main/java/com/ecommerce/aftersales/common/GlobalExceptionHandler.java`
- Modify: `src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java`
- Modify: `src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java`
- Modify: `src/main/java/com/ecommerce/aftersales/controller/KnowledgeManagementController.java`
- Test: `src/test/java/com/ecommerce/aftersales/service/KnowledgePublishServiceTest.java`
- Test: `src/test/java/com/ecommerce/aftersales/integration/KnowledgePublishIntegrationTest.java`

**Interfaces:**
- Produces: `PUT /{id}/draft` 更新政策版本和有效期。
- Produces: `PUT /{id}/draft/chunks/{chunkId}` 更新章节标签。
- Produces: `POST /{id}/publish`，body 为 `{ "expectedRevision": 4 }`。
- Produces: CAS 冲突 HTTP 409，响应 data 为 `{ "currentRevision": 5, "reviewStatus": "REVIEW_REQUIRED" }`。
- Consumes: Python `/api/embeddings` 批量向量结果。

- [ ] **Step 1: 写 CAS 与迟到任务失败测试**

```java
@Test
void stalePublishCannotReplaceNewerRevision() {
    assertThatThrownBy(() -> service.startPublishing(42L, 3L))
        .isInstanceOf(BizException.class)
        .hasMessageContaining("知识已被其他操作更新");
    verify(asyncService, never()).publish(anyLong(), anyLong());
}

@Test
void failedEmbeddingKeepsPublishedRevisionAndOldChunks() {
    publishService.markEmbeddingFailed(42L, 6L, "TIMEOUT");
    assertThat(document(42L).publishedRevision()).isEqualTo(5L);
    assertThat(chunks(42L, 5L)).isNotEmpty();
}
```

- [ ] **Step 2: 运行测试确认发布服务不存在**

Run: `.\mvnw.cmd -Dtest=KnowledgePublishServiceTest,KnowledgePublishIntegrationTest test`

Expected: FAIL。

- [ ] **Step 3: 实现 Draft 编辑 CAS**

在一个 PostgreSQL 事务中先执行文档 CAS，再更新文档级或 Chunk 级字段，最后把同一文档全部 Draft 行更新为新 revision：

```sql
UPDATE knowledge_document
SET revision = revision + 1, updated_at = NOW()
WHERE id = ? AND revision = ? AND review_status = 'REVIEW_REQUIRED'
RETURNING revision;

UPDATE knowledge_chunk_draft
SET revision = ?
WHERE document_id = ?;
```

Chunk 的三个数组必须逐项经过 `KnowledgeMetadataPolicy` 归一化。空数组允许发布，`NULL` 不允许发布。版本化政策必须满足 version 非空且 `valid_to > valid_from`。

CAS 影响行数为 0 时查询当前 revision/status 并抛出专用异常；`GlobalExceptionHandler` 保留冲突数据：

```java
@Getter
public final class KnowledgeRevisionConflictException extends RuntimeException {
    private final long currentRevision;
    private final String reviewStatus;

    public KnowledgeRevisionConflictException(long currentRevision, String reviewStatus) {
        super("知识已被其他操作更新，请刷新后重试");
        this.currentRevision = currentRevision;
        this.reviewStatus = reviewStatus;
    }
}

@ExceptionHandler(KnowledgeRevisionConflictException.class)
public ResponseEntity<ApiResponse<Map<String, Object>>> handleKnowledgeRevisionConflict(
        KnowledgeRevisionConflictException exception) {
    Map<String, Object> data = Map.of(
            "currentRevision", exception.getCurrentRevision(),
            "reviewStatus", exception.getReviewStatus());
    return ResponseEntity.status(HttpStatus.CONFLICT)
            .body(new ApiResponse<>(false, 409, exception.getMessage(), data));
}
```

- [ ] **Step 4: 实现发布冻结和异步 Embedding**

发布 CAS 将状态改为 `PUBLISHING` 并获得 `targetRevision=expectedRevision+1`；同事务把 Draft 行 revision 更新为 target revision。异步任务只读取该 target revision，调用 `/api/embeddings`。任何数量不一致、维度不等于 1024 或部分失败都进入 `EMBEDDING_FAILED`。

```sql
UPDATE knowledge_document
SET review_status='PUBLISHING', revision=revision+1, updated_at=NOW()
WHERE id=? AND revision=? AND review_status='REVIEW_REQUIRED'
RETURNING revision;
```

- [ ] **Step 5: 实现正式版本原子切换**

`KnowledgePublishService.commitPublishedRevision` 使用 `@Transactional(transactionManager="pgTransactionManager")`，按以下顺序执行且最后一步必须影响一行，否则整笔回滚：

```sql
INSERT INTO knowledge_chunk(document_id, document_type, chunk_index, chunk_text,
    embedding, revision, product_categories, scenes, intents, heading_path,
    page_number, search_text, metadata, create_time)
VALUES (?, ?, ?, ?, ?::vector, ?, ?, ?, ?, ?, ?, ?, ?::jsonb, NOW());

UPDATE knowledge_document
SET published_revision=?, review_status='PUBLISHED', updated_at=NOW()
WHERE id=? AND review_status='PUBLISHING' AND revision=?;

DELETE FROM knowledge_chunk
WHERE document_id=? AND revision<>?;
```

`search_text` 由标题路径、正文和确认后的标签规范化拼接。正式 metadata 保存 title/source/source_code/merchant/policy_version/validity/citation 信息，但过滤使用结构化列，不依赖 JSON 字符串。

- [ ] **Step 6: 运行发布单元和集成测试**

Run: `.\mvnw.cmd -Dtest=KnowledgePublishServiceTest,KnowledgePublishIntegrationTest test`

Expected: PASS；并发 publish 只有一个成功；旧任务结果不能覆盖新 revision。

- [ ] **Step 7: 提交**

```powershell
git add src/main/java/com/ecommerce/aftersales/common/KnowledgeRevisionConflictException.java src/main/java/com/ecommerce/aftersales/common/GlobalExceptionHandler.java src/main/java/com/ecommerce/aftersales/service/KnowledgePublishService.java src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java src/main/java/com/ecommerce/aftersales/controller/KnowledgeManagementController.java src/test/java/com/ecommerce/aftersales/service/KnowledgePublishServiceTest.java src/test/java/com/ecommerce/aftersales/integration/KnowledgePublishIntegrationTest.java
git commit -m "feat: publish knowledge revisions atomically"
```

### Task 5: 严格过滤、Keyword 候选和真正的 RRF

**Files:**
- Create: `python_agent/after_sales_agent/retrieval/knowledge_filters.py`
- Create: `python_agent/after_sales_agent/retrieval/rrf.py`
- Create: `python_agent/tests/test_knowledge_filters.py`
- Create: `python_agent/tests/test_rrf.py`
- Modify: `python_agent/after_sales_agent/retrieval/pgvector_retriever.py:113-535`
- Modify: `python_agent/tests/test_pgvector_retriever.py`

**Interfaces:**
- Produces: `FilterContext`、`FilterPlan`、`rrf_fuse(dense_hits, keyword_hits, k=60, limit=20)`。
- Produces: Dense/Keyword 都返回 `chunk_id/rank/raw_score` 和统一 citation metadata。
- Consumes: `as_of_time`；无值时普通咨询使用当前时间，工单工具必须显式传入业务时间。

- [ ] **Step 1: 写过滤和 RRF 失败测试**

```python
def test_hard_filters_never_relax_merchant_revision_or_validity():
    plans = build_filter_plans(FilterContext(
        merchant_code="M1", source_type="after_sales_policy", policy_version="v2",
        as_of_time=datetime(2026, 7, 21), product_category="headphone",
        scene="quality_issue", intent="refund",
    ))
    assert all(plan.merchant_code == "M1" for plan in plans)
    assert all(plan.policy_version == "v2" for plan in plans)
    assert all(plan.as_of_time == datetime(2026, 7, 21) for plan in plans)
    assert all(plan.intent == "refund" for plan in plans)  # 政策不放宽 intent

def test_rrf_uses_rank_not_incompatible_raw_scores():
    fused = rrf_fuse(
        [{"chunk_id": "A", "score": .99}, {"chunk_id": "B", "score": .98}],
        [{"chunk_id": "B", "score": 100.0}, {"chunk_id": "C", "score": 99.0}],
        k=60, limit=20,
    )
    assert fused[0]["chunk_id"] == "B"
    assert fused[0]["dense_rank"] == 2
    assert fused[0]["keyword_rank"] == 1
```

- [ ] **Step 2: 运行测试确认组件不存在**

Run: `cd python_agent; python -m pytest tests/test_knowledge_filters.py tests/test_rrf.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现严格过滤计划**

```python
@dataclass(frozen=True)
class FilterContext:
    merchant_code: str
    source_type: str | None
    policy_version: str | None
    as_of_time: datetime
    product_category: str | None
    scene: str | None
    intent: str | None

@dataclass(frozen=True)
class FilterPlan:
    level: str
    merchant_code: str
    source_type: str | None
    policy_version: str | None
    as_of_time: datetime
    product_category: str | None
    scene: str | None
    intent: str | None
    trusted_policy_eligible: bool

def build_filter_plans(ctx: FilterContext) -> list[FilterPlan]:
    strict = FilterPlan(
        level="strict",
        merchant_code=ctx.merchant_code,
        source_type=ctx.source_type,
        policy_version=ctx.policy_version,
        as_of_time=ctx.as_of_time,
        product_category=ctx.product_category,
        scene=ctx.scene,
        intent=ctx.intent,
        trusted_policy_eligible=True,
    )
    plans = [strict]
    plans.append(replace(strict, level="category_relaxed", product_category=None, trusted_policy_eligible=False))
    plans.append(replace(strict, level="scene_relaxed", scene=None, trusted_policy_eligible=False))
    if ctx.source_type not in {"after_sales_policy", "refund_policy", "exchange_rule"}:
        plans.append(replace(strict, level="intent_relaxed", intent=None, trusted_policy_eligible=False))
    return plans
```

SQL 公共硬过滤片段必须同时用于 Dense 和 Keyword：

```sql
kd.status = 1
AND COALESCE(kd.metadata ->> 'deleted','false') <> 'true'
AND kd.published_revision IS NOT NULL
AND kc.revision = kd.published_revision
AND kd.merchant_code IN (%s, 'GLOBAL')
AND (%s IS NULL OR kd.source_type = %s)
AND (%s IS NULL OR kd.policy_version = %s)
AND (kd.valid_from IS NULL OR kd.valid_from <= %s)
AND (kd.valid_to IS NULL OR %s < kd.valid_to)
AND (%s IS NULL OR kc.product_categories = '{}' OR %s = ANY(kc.product_categories))
AND (%s IS NULL OR kc.scenes = '{}' OR %s = ANY(kc.scenes))
AND (%s IS NULL OR kc.intents = '{}' OR %s = ANY(kc.intents))
```

- [ ] **Step 4: 实现 Dense、pg_trgm Keyword 与 RRF**

Dense 查询在公共过滤后按 `embedding <=> query_vector` 取 20；Keyword 查询在相同过滤后使用 `similarity(kc.search_text, query)`、完整短语命中和标题路径加权取 20。两路候选使用纯函数 RRF，不能再调用当前 `_merge_and_rerank_hits` 的启发式分数相加。

```python
def rrf_fuse(dense_hits, keyword_hits, *, k=60, limit=20):
    merged: dict[str, dict] = {}
    for channel, hits in (("dense", dense_hits), ("keyword", keyword_hits)):
        for rank, hit in enumerate(hits, start=1):
            item = merged.setdefault(str(hit["chunk_id"]), {**hit, "rrf_score": 0.0, "retrieval_channels": []})
            item["rrf_score"] += 1.0 / (k + rank)
            item[f"{channel}_rank"] = rank
            item[f"{channel}_score"] = hit.get("score")
            item["retrieval_channels"].append(channel)
    return sorted(merged.values(), key=lambda x: (-x["rrf_score"], x["chunk_id"]))[:limit]
```

- [ ] **Step 5: 运行检索测试**

Run: `cd python_agent; python -m pytest tests/test_knowledge_filters.py tests/test_rrf.py tests/test_pgvector_retriever.py -q`

Expected: PASS；SQL 捕获测试证明两路都含 revision、merchant、status、validity 条件。

- [ ] **Step 6: 提交**

```powershell
git add python_agent/after_sales_agent/retrieval/knowledge_filters.py python_agent/after_sales_agent/retrieval/rrf.py python_agent/after_sales_agent/retrieval/pgvector_retriever.py python_agent/tests/test_knowledge_filters.py python_agent/tests/test_rrf.py python_agent/tests/test_pgvector_retriever.py
git commit -m "feat: add filtered hybrid RAG retrieval"
```

### Task 6: 托管 Reranker、阈值、超时和安全降级

**Files:**
- Create: `python_agent/after_sales_agent/providers/reranker_client.py`
- Create: `python_agent/tests/test_reranker_client.py`
- Modify: `python_agent/after_sales_agent/retrieval/pgvector_retriever.py`
- Modify: `python_agent/after_sales_agent/retrieval/__init__.py`
- Modify: `python_agent/.env.example`
- Modify: `compose.yml:60-80`

**Interfaces:**
- Produces: `RerankResult(items, mode, degraded, failure_reason, latency_ms)`。
- Consumes: RRF Top20；返回按原 candidate index 对齐的 `relevance_score`。
- Configuration: `RERANK_PROVIDER`、`RERANK_BASE_URL`、`RERANK_API_KEY`、`RERANK_MODEL`、`RERANK_TIMEOUT_SECONDS=3`、`RERANK_MAX_RETRIES=1`、`RERANK_MAX_CONCURRENCY=4`、`RERANK_CIRCUIT_FAILURE_THRESHOLD=5`、`RERANK_CIRCUIT_RECOVERY_SECONDS=30`。

- [ ] **Step 1: 写超时、熔断和排序失败测试**

```python
class TimeoutTransport:
    def post_json(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        raise RerankError("TIMEOUT")

class FakeTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def post_json(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return self.response

def test_timeout_degrades_to_rrf_without_marking_policy_trusted():
    candidates = [{"chunk_id": "A", "chunk_text": "退款政策", "rrf_score": 0.03}]
    config = RerankerConfig(
        provider="dashscope", base_url="https://example.invalid/rerank", api_key="test",
        model="text-rerank-v2", timeout_seconds=0.01, max_retries=1,
        max_candidates=20, max_concurrency=1, circuit_failure_threshold=5,
        circuit_recovery_seconds=30,
    )
    client = RerankerClient(transport=TimeoutTransport(), config=config)
    result = client.rerank("退款条件", candidates, top_n=5)
    assert result.mode == "hybrid_rrf_degraded"
    assert result.degraded is True
    assert result.items == candidates

def test_invalid_provider_indexes_fail_closed():
    candidates = [{"chunk_id": "A", "chunk_text": "退款政策", "rrf_score": 0.03}]
    config = RerankerConfig(
        provider="dashscope", base_url="https://example.invalid/rerank", api_key="test",
        model="text-rerank-v2", timeout_seconds=1, max_retries=1,
        max_candidates=20, max_concurrency=1, circuit_failure_threshold=5,
        circuit_recovery_seconds=30,
    )
    client = RerankerClient(transport=FakeTransport({"results": [{"index": 99, "relevance_score": .9}]}), config=config)
    result = client.rerank("query", candidates, top_n=5)
    assert result.degraded is True
    assert result.failure_reason == "INVALID_RESPONSE"
```

- [ ] **Step 2: 运行测试确认客户端不存在**

Run: `cd python_agent; python -m pytest tests/test_reranker_client.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现可靠 Reranker 客户端**

```python
@dataclass(frozen=True)
class RerankerConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    max_retries: int
    max_candidates: int
    max_concurrency: int
    circuit_failure_threshold: int
    circuit_recovery_seconds: int

@dataclass(frozen=True)
class RerankResult:
    items: list[dict[str, Any]]
    mode: str
    degraded: bool
    failure_reason: str | None
    latency_ms: float

class RerankerClient:
    def rerank(self, query: str, candidates: list[dict[str, Any]], top_n: int) -> RerankResult:
        if self.breaker.is_open():
            return RerankResult.degraded(candidates[:top_n], "CIRCUIT_OPEN")
        with self.semaphore:
            try:
                payload = {"model": self.config.model, "query": query,
                           "documents": [c["chunk_text"] for c in candidates], "top_n": top_n}
                data = self.transport.post_json(payload, timeout=self.config.timeout_seconds, retries=1)
                return self._validated_result(data, candidates, top_n)
            except RerankError as exc:
                self.breaker.record_failure()
                return RerankResult.degraded(candidates[:top_n], exc.code)
```

只对超时、HTTP 429 和 5xx 重试一次；400/401/403 不重试。Semaphore 等待超过超时直接降级。响应 index 必须唯一且在候选范围，score 必须可转换为 `[0,1]`。

- [ ] **Step 4: 在 Retriever 应用分类型阈值**

```python
THRESHOLDS = {
    "after_sales_policy": 0.75,
    "refund_policy": 0.75,
    "exchange_rule": 0.75,
    "evidence_requirement": 0.65,
    "faq": 0.60,
}
```

检索响应增加 `mode`、`filter_level`、`reranker_succeeded`、`threshold`、`no_answer`、`trace.stage_latency_ms`。政策只有 `strict + reranker_succeeded + score >= threshold` 才设置 `trusted_policy_eligible=true`。Dense-only、Keyword-only、RRF degraded 和任何放宽过滤都为 false。

- [ ] **Step 5: 运行 Reranker 和 Retriever 测试**

Run: `cd python_agent; python -m pytest tests/test_reranker_client.py tests/test_pgvector_retriever.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add python_agent/after_sales_agent/providers/reranker_client.py python_agent/after_sales_agent/retrieval/pgvector_retriever.py python_agent/after_sales_agent/retrieval/__init__.py python_agent/tests/test_reranker_client.py python_agent/tests/test_pgvector_retriever.py python_agent/.env.example compose.yml
git commit -m "feat: add resilient hosted reranking"
```

### Task 7: Agent 政策信任边界和调用上下文

**Files:**
- Modify: `python_agent/after_sales_agent/application/tool_registry.py:161-174`
- Modify: `python_agent/after_sales_agent/application/after_sales_workflow.py:1817-1860`
- Modify: `python_agent/after_sales_agent/application/knowledge_admin_service.py:12-43`
- Modify: `python_agent/tests/test_after_sales_workflow.py`
- Modify: `python_agent/tests/test_agent_contracts.py`

**Interfaces:**
- Consumes: Retriever 的 `trusted_policy_eligible/filter_level/reranker_succeeded/citations`。
- Produces: 工单查询显式传 `policy_version` 和 `as_of_time`；自动审核只消费可信政策结果。

- [ ] **Step 1: 写降级政策不能自动审核的失败测试**

```python
def test_rrf_degraded_policy_hit_is_not_trusted():
    knowledge = {
        "mode": "hybrid_rrf_degraded",
        "filter_level": "strict",
        "reranker_succeeded": False,
        "hits": [{"source_type": "after_sales_policy", "score": .99,
                  "merchant_code": "MERCHANT_DEMO", "policy_version": "v2"}],
    }
    hits = LangGraphAfterSalesAgent._trusted_policy_hits(
        knowledge, {"merchant_code": "MERCHANT_DEMO", "policy_version": "v2"})
    assert hits == []
```

再覆盖放宽过滤、高分但过期、商家不匹配、严格 Rerank 成功且带 citation 的正例。

- [ ] **Step 2: 运行工作流测试确认旧 `mode == pgvector` 判断不满足新契约**

Run: `cd python_agent; python -m pytest tests/test_after_sales_workflow.py tests/test_agent_contracts.py -q`

Expected: FAIL 至少一个新断言。

- [ ] **Step 3: 改为消费显式安全字段**

```python
if not isinstance(knowledge, dict):
    return []
if knowledge.get("filter_level") != "strict":
    return []
if knowledge.get("reranker_succeeded") is not True:
    return []

for hit in self._policy_hits(knowledge):
    if hit.get("trusted_policy_eligible") is not True:
        continue
    if not hit.get("citations"):
        continue
```

`tool_registry.retrieve_knowledge` 新增透传 `as_of_time`。工单路径取售后申请时间；历史订单政策解释取订单创建时间；普通 FAQ 不得伪造业务时间。

- [ ] **Step 4: 运行 Agent 回归测试**

Run: `cd python_agent; python -m pytest tests/test_after_sales_workflow.py tests/test_agent_contracts.py tests/test_pgvector_retriever.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add python_agent/after_sales_agent/application/tool_registry.py python_agent/after_sales_agent/application/after_sales_workflow.py python_agent/after_sales_agent/application/knowledge_admin_service.py python_agent/tests/test_after_sales_workflow.py python_agent/tests/test_agent_contracts.py
git commit -m "fix: enforce trusted RAG policy evidence"
```

### Task 8: Vue 文件上传、Draft 确认和发布体验

**Files:**
- Create: `frontend/staff-auth-test-ui/src/api/knowledgeDraft.js`
- Create: `frontend/staff-auth-test-ui/src/components/KnowledgeDraftReviewPanel.vue`
- Create: `frontend/staff-auth-test-ui/tests/knowledgeDraft.test.mjs`
- Modify: `frontend/staff-auth-test-ui/src/api/adminConsole.js:127-176`
- Modify: `frontend/staff-auth-test-ui/src/components/KnowledgeImportModal.vue:1-160`
- Modify: `frontend/staff-auth-test-ui/src/views/AdminKnowledgeView.vue:1-390,450-530`
- Modify: `frontend/staff-auth-test-ui/package.json`

**Interfaces:**
- Consumes: Task 3/4 管理 API，所有 documentId/chunkId 当字符串处理。
- Produces: 第一阶段文件上传；第二阶段 Draft review、文档有效期修改、Chunk 标签确认、发布和失败重试。

- [ ] **Step 1: 写 Draft 纯函数失败测试**

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeDraft, validateDraftForPublish } from '../src/api/knowledgeDraft.js';

test('unconfirmed null metadata blocks publish but confirmed empty arrays pass', () => {
  assert.deepEqual(validateDraftForPublish({ chunks: [{ productCategories: null, scenes: [], intents: [] }] }),
    ['第 1 个切片的商品品类尚未确认']);
  assert.deepEqual(validateDraftForPublish({ chunks: [{ productCategories: [], scenes: [], intents: [] }] }), []);
});

test('knowledge ids remain strings', () => {
  const draft = normalizeDraft({ documentId: '9223372036854775806', revision: 4, chunks: [] });
  assert.equal(draft.documentId, '9223372036854775806');
});
```

- [ ] **Step 2: 运行 Node 测试确认模块不存在**

Run: `cd frontend/staff-auth-test-ui; node --test tests/knowledgeDraft.test.mjs`

Expected: FAIL with module not found。

- [ ] **Step 3: 改造第一阶段上传**

`KnowledgeImportModal.vue` 删除 TEXT/EDIT tab、自由文本、品类、场景、意图、标签和 autoChunk；保留知识类型、scope、merchant、可选标题和文件。文件 input：

```html
<input type="file" accept=".pdf,.md,.txt,application/pdf,text/markdown,text/plain" @change="$emit('file-change', $event)" />
<span>支持文本型 PDF、Markdown 和 TXT；扫描版 PDF 暂不支持 OCR</span>
```

标题为空时不阻止提交。`AdminKnowledgeView.submitImport` 调 `/file-import`，不再提交前端选择的过滤字段。

- [ ] **Step 4: 增加 Draft API 和 Review 组件**

```javascript
// adminConsole.js 的 request 错误分支保留 HTTP 状态和冲突数据。
if (!response.ok || payload.success === false) {
  const error = new Error(payload.message || `管理员接口请求失败（HTTP ${response.status}）`);
  error.status = response.status;
  error.code = payload.code;
  error.data = payload.data || null;
  throw error;
}

export const getKnowledgeIngestionStatus = (id) => request(buildKnowledgePath(id, '/ingestion-status'));
export const getKnowledgeDraft = (id) => request(buildKnowledgePath(id, '/draft'));
export const updateKnowledgeDraft = (id, body) => request(buildKnowledgePath(id, '/draft'), { method: 'PUT', body: JSON.stringify(body) });
export const updateKnowledgeDraftChunk = (id, chunkId, body) => request(buildKnowledgePath(id, `/draft/chunks/${normalizeKnowledgeId(chunkId)}`), { method: 'PUT', body: JSON.stringify(body) });
export const publishKnowledgeDraft = (id, expectedRevision) => request(buildKnowledgePath(id, '/publish'), { method: 'POST', body: JSON.stringify({ expectedRevision }) });
export const retryKnowledgeIngestion = (id) => request(buildKnowledgePath(id, '/retry'), { method: 'POST' });
```

`mapKnowledgeRecord` 将新字段映射为唯一状态来源，兼容旧响应只作为迁移兜底：

```javascript
reviewStatus: item.reviewStatus || item.ingestionStatus || 'PUBLISHED',
revision: Number(item.revision || 0),
publishedRevision: item.publishedRevision == null ? null : Number(item.publishedRevision),
```

`getDisplayStatus` 使用 `reviewStatus` 区分 `PROCESSING/REVIEW_REQUIRED/PUBLISHING/PUBLISHED/*_FAILED`，不再把所有非 PROCESSING 状态默认显示为已启用。

Review 组件逐 Chunk 显示 heading path、页码、摘要、source/confidence/reason 和受控多选。`null` 显示“待确认”，空数组显示“已确认为通用”。政策文档同时编辑 policy version、validFrom、validTo。保存或发布遇到 409 时重新加载 Draft 并提示“内容已被其他管理员更新”。

- [ ] **Step 5: 状态轮询与资源释放**

仅在选中文档状态为 `PROCESSING` 或 `PUBLISHING` 时每 2 秒轮询；组件 unmount、切换选中项或进入终态时 `clearInterval`。终态包含 `REVIEW_REQUIRED/PUBLISHED/PARSE_FAILED/CLASSIFY_FAILED/EMBEDDING_FAILED`。

- [ ] **Step 6: 运行前端测试和构建**

在 `package.json` 设置：

```json
"test:contracts": "node --test tests/merchantCsAdapterContract.test.mjs tests/knowledgeId.test.mjs tests/knowledgeDraft.test.mjs"
```

Run: `cd frontend/staff-auth-test-ui; npm run test:contracts; npm run build`

Expected: tests PASS，Vite build PASS。

- [ ] **Step 7: 提交**

```powershell
git add frontend/staff-auth-test-ui/src/api/adminConsole.js frontend/staff-auth-test-ui/src/api/knowledgeDraft.js frontend/staff-auth-test-ui/src/components/KnowledgeImportModal.vue frontend/staff-auth-test-ui/src/components/KnowledgeDraftReviewPanel.vue frontend/staff-auth-test-ui/src/views/AdminKnowledgeView.vue frontend/staff-auth-test-ui/tests/knowledgeDraft.test.mjs frontend/staff-auth-test-ui/package.json
git commit -m "feat: add knowledge draft review workflow"
```

### Task 9: 离线指标、消融评测和可观测性

**Files:**
- Create: `python_agent/evaluation/rag_retrieval_cases.jsonl`
- Create: `python_agent/after_sales_agent/evaluation/rag_metrics.py`
- Create: `python_agent/tests/test_rag_metrics.py`
- Modify: `tools/evaluate_rag_recall.py`
- Modify: `docs/rag-recall-baseline.md`
- Modify: `python_agent/after_sales_agent/retrieval/pgvector_retriever.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/nightly-smoke.yml`

**Interfaces:**
- Produces: Recall@5/20、MRR@10、NDCG@5、HitRate@5、Filter Violation Rate、No-answer FPR、Rerank Uplift、p50/p95 latency 和单次 Rerank 成本。
- Consumes: JSONL 每行 `case_id/query/filters/relevant_chunk_ids/expect_no_answer/forbidden_merchant_codes/forbidden_policy_versions`。

- [ ] **Step 1: 写指标失败测试**

```python
def test_metrics_separate_recall_from_filter_safety():
    cases = [Case("c1", relevant_chunk_ids={"A"}, forbidden_merchant_codes={"M2"})]
    runs = {"c1": [{"chunk_id": "A", "merchant_code": "M1"}, {"chunk_id": "X", "merchant_code": "M2"}]}
    report = evaluate(cases, runs, k_values=(5, 20))
    assert report["recall_at_5"] == 1.0
    assert report["filter_violation_rate"] > 0

def test_no_answer_false_positive_rate_counts_answered_negative_cases():
    cases = [Case("n1", relevant_chunk_ids=set(), expect_no_answer=True)]
    assert evaluate(cases, {"n1": [{"chunk_id": "X"}]})["no_answer_false_positive_rate"] == 1.0
```

- [ ] **Step 2: 运行指标测试确认模块不存在**

Run: `cd python_agent; python -m pytest tests/test_rag_metrics.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现指标与评测数据契约**

```python
@dataclass(frozen=True)
class Case:
    case_id: str
    relevant_chunk_ids: set[str]
    expect_no_answer: bool = False
    forbidden_merchant_codes: set[str] = field(default_factory=set)
    forbidden_policy_versions: set[str] = field(default_factory=set)

def reciprocal_rank(relevant: set[str], ranked: list[str], cutoff: int) -> float:
    return next((1.0 / rank for rank, item in enumerate(ranked[:cutoff], 1) if item in relevant), 0.0)

def hit_rate(relevant: set[str], ranked: list[str], cutoff: int) -> float:
    return float(bool(relevant.intersection(ranked[:cutoff])))
```

JSONL 至少覆盖政策、凭证、FAQ、无答案、跨商家、过期政策、口语、错别字和同义表达。仓库当前 18 条数据迁移为 `split=smoke`，不当作 Holdout；新 Holdout 只有完成双人标注或争议复核后才用于阈值结论。

- [ ] **Step 4: 输出四组消融与 Trace**

评测脚本接受 `--mode dense|keyword|rrf|rerank|all` 和 `--dataset`，生成 JSON/Markdown，报告样本数量、各类分布、标注方法、运行时间、模型/阈值配置和局限。Retriever Trace 必须记录：

```python
trace = {
    "filter_level": plan.level,
    "dense_candidate_count": len(dense),
    "keyword_candidate_count": len(keyword),
    "rrf_candidate_count": len(fused),
    "rerank_candidate_count": len(reranked),
    "retrieval_mode": mode,
    "stage_latency_ms": stage_latency,
    "fallback_reason": fallback_reason,
}
```

日志可以记录 query_id 和计数，不能把 Query 原文、document ID 或商家自由文本作为 Prometheus label。

- [ ] **Step 5: 增加 CI 纯函数门禁和 nightly 集成评测**

CI 运行 `test_rag_metrics.py`；nightly 只有配置 `PGVECTOR_DSN`、Embedding 和 Rerank 密钥时运行真实检索评测，否则输出明确 skip。安全门禁只对带可靠标注的 Holdout 要求 `filter_violation_rate == 0`；不得把 Recall 阈值硬套到 18 条 smoke 集。

- [ ] **Step 6: 运行评测单元测试和 smoke 数据校验**

Run: `cd python_agent; python -m pytest tests/test_rag_metrics.py tests/test_pgvector_retriever.py -q`

Run: `python tools/evaluate_rag_recall.py --dataset python_agent/evaluation/rag_retrieval_cases.jsonl --mode all --dry-run`

Expected: PASS；dry-run 输出数据分布但不访问模型。

- [ ] **Step 7: 提交**

```powershell
git add python_agent/evaluation/rag_retrieval_cases.jsonl python_agent/after_sales_agent/evaluation/rag_metrics.py python_agent/tests/test_rag_metrics.py python_agent/after_sales_agent/retrieval/pgvector_retriever.py tools/evaluate_rag_recall.py docs/rag-recall-baseline.md .github/workflows/ci.yml .github/workflows/nightly-smoke.yml
git commit -m "test: add layered RAG evaluation metrics"
```

### Task 10: 配置、兼容切换和全链路验收

**Files:**
- Modify: `src/main/resources/application.yml:80-100`
- Modify: `src/main/resources/application-local.example.yml:1-30`
- Modify: `python_agent/.env.example`
- Modify: `compose.yml:60-110`
- Modify: `docs/README.md`

**Interfaces:**
- Produces: `RAG_LAYERED_RETRIEVAL_ENABLED=false` 默认兼容开关；迁移、回填和评测通过后改为 true。
- Produces: 明确的本地启动、迁移、回滚和排查步骤。

- [ ] **Step 1: 增加配置绑定测试**

在 Python config 测试和 Spring context 测试中断言默认值：

```text
RAG_LAYERED_RETRIEVAL_ENABLED=false
RERANK_TIMEOUT_SECONDS=3
RERANK_MAX_RETRIES=1
RERANK_MAX_CANDIDATES=20
KNOWLEDGE_MAX_FILE_BYTES=10485760
```

- [ ] **Step 2: 运行完整自动化测试**

Run: `.\mvnw.cmd test`

Expected: `BUILD SUCCESS`，0 failures/errors。

Run: `cd python_agent; python -m pytest tests -q`

Expected: 全部 PASS；真实 LLM/数据库 smoke 未配置时只 skip，不失败。

Run: `cd frontend/staff-auth-test-ui; npm run test:contracts; npm run build`

Expected: tests 和 build PASS。

- [ ] **Step 3: 启动 Compose 并验证迁移**

Run: `docker compose up -d postgres agent java`

Expected: 三个服务 healthy/running；PostgreSQL 存在 `knowledge_chunk_draft`、`published_revision` 和 `idx_kc_search_text_trgm`。

- [ ] **Step 4: 执行最小全链路验收**

按顺序验证：

```text
上传 MD → PROCESSING → REVIEW_REQUIRED
修改一个低置信度 Chunk → revision 增长
使用旧 expectedRevision 发布 → HTTP 409
使用最新 revision 发布 → PUBLISHING → PUBLISHED
查询命中 chunk.revision = published_revision
重新上传更新版并制造 Embedding 失败 → 旧 published_revision 仍可命中
Reranker 超时 → mode=hybrid_rrf_degraded 且 trusted_policy_eligible=false
跨商家、过期政策、未发布 Draft → 0 命中
```

- [ ] **Step 5: 记录部署和排查文档**

`docs/README.md` 增加：迁移命令、Python 环境变量、DashScope key、Reranker 配置、状态机、常见错误码、如何识别 `lexical_fallback_after_embedding_error`、如何回退 `RAG_LAYERED_RETRIEVAL_ENABLED=false`。不得写“生产召回率 100%”；只引用带样本规模和分布的新离线报告。

- [ ] **Step 6: 最终 diff 和测试证据检查**

Run: `git diff --check`

Expected: 无输出，exit 0。

Run: `git status --short`

Expected: 只显示本任务明确修改的文件；若执行环境原先有用户改动，逐文件核对且不纳入提交。

- [ ] **Step 7: 提交**

```powershell
git add src/main/resources/application.yml src/main/resources/application-local.example.yml python_agent/.env.example compose.yml docs/README.md
git commit -m "docs: finish layered RAG rollout guide"
```

---

## Execution Order and Review Gates

1. Task 1 是所有后续任务的数据库契约，必须先通过。
2. Task 2 与 Task 3 可以在 Task 1 后分别实现，但合并前必须完成 Python parse 与 Java DTO 的契约测试。
3. Task 4 必须在 Task 3 后完成，且原子发布集成测试通过前不得让 Draft 进入正式检索。
4. Task 5 完成后仍保持分层检索开关关闭，先跑 SQL 安全测试。
5. Task 6 和 Task 7 共同构成政策可信边界，必须作为一个发布门禁审查。
6. Task 8 只能消费已稳定的 Task 3/4 API，不在前端复制状态机和 canonical 枚举。
7. Task 9 的过滤违规指标为 0 后，Task 10 才允许在目标环境打开新检索器。

## Rollback

- 关闭 `RAG_LAYERED_RETRIEVAL_ENABLED`，Python 回到旧 Retriever；不删除新表和新列。
- Java 发布接口停止接收新发布，但已发布 `published_revision` 数据保留。
- 前端隐藏 Draft 发布入口，列表和详情继续读取兼容字段。
- 数据库迁移只增加结构；回滚不 DROP 列、不删除 Draft 或历史 Chunk，避免不可逆数据丢失。
