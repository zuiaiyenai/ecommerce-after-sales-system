# Structured Knowledge Final Fixes Report

## Status

- Base: `0460245`
- Implementation commit: `ef04f29` (`fix: harden structured knowledge ingestion boundaries`)
- Finding 1: fixed and verified.
- Finding 2: fixed and verified.
- No migration, reindex, real provider call, or application database operation was run.

## Finding 1: Knowledge Parse Request Size

Root cause: `AgentApiHandler.do_POST` read every request through the global 2 MiB limit before route dispatch. A Java-accepted 10 MiB file expands to 13,981,016 Base64 bytes before the JSON envelope and was rejected before `/api/knowledge/parse` could decode it.

Fix:

- Added `KNOWLEDGE_PARSE_MAX_REQUEST_BYTES` exclusively for `/api/knowledge/parse`.
- Default is 15,029,592 bytes: exact 10 MiB Base64 upper bound plus a documented 1 MiB JSON envelope.
- Other Agent endpoints retain `AGENT_MAX_REQUEST_BYTES=2097152`.
- Knowledge parse request overflow returns HTTP 413 with stable code `FILE_TOO_LARGE`.
- Java now preserves `FILE_TOO_LARGE` when persisting parse failure instead of degrading it to `PARSE_FAILED`.
- Added the setting to root and Agent environment examples and bound it explicitly in `compose.yml`.
- Java's configured raw-file upload limit remains authoritative; the Agent limit applies only to the encoded HTTP envelope.

TDD evidence:

- RED: four Python contract tests failed because the dedicated constants/route behavior did not exist.
- RED: Java persisted `PARSE_FAILED` instead of expected `FILE_TOO_LARGE` for a 413 response.
- GREEN: all new route, default-calculation, Java envelope, and error mapping assertions pass.

## Finding 2: Mixed PDF Missing Text Layers

Root cause: `extract_pdf_pages` converted every blank `extract_text()` result to an empty string and only rejected the document when all pages were empty. A text page followed by an image-only page and another text page therefore silently omitted the middle page.

Fix:

- Empty-text pages now fail closed with `PDF_TEXT_LAYER_MISSING` when they have a non-empty content stream or image XObject.
- A genuinely blank page with no content stream or image resource remains valid inside an otherwise textual PDF.
- A per-page `extract_text` exception remains a stable `FILE_DECODE_FAILED` rather than being ignored.
- Added a fixture proving repeated header text in the body keeps the body occurrence while only edge occurrences are removed.
- No OCR or PDF layout dependency was added; parsing continues to use `pypdf`.

TDD evidence:

- RED: mixed text/image/text fixture completed without raising.
- GREEN: mixed image page rejects, genuine blank middle page succeeds, extraction exception is stable, and edge-only header removal passes.

## Verification

- Python ingestion and HTTP suite: 80 passed (76 tracked tests plus 4 pre-existing untracked HTTP-body tests), 1 existing dependency warning.
- Java planned regression: 62 passed, including 6 `KnowledgePublishIntegrationTest` Testcontainers tests.
- Additional `KnowledgeDraftLifecycleIntegrationTest`: 2 passed with Testcontainers.
- Total executed: 144 passed, 0 failed.
- `python -m compileall -q after_sales_agent`: passed.
- Obsolete splitter search: no matches.
- `docker compose config --quiet`: exit 0; emitted only the local Docker config permission warning.
- Task-scoped and staged `git diff --check`: passed.
- Whole-worktree `git diff --check`: blocked only by the user's pre-existing `python_agent/README.md:181` blank line at EOF; that unrelated file was not modified.

## File Scope

- Configuration: `.env.example`, `python_agent/.env.example`, `compose.yml`
- Python runtime: `python_agent/after_sales_agent/api/http_server.py`
- Python PDF parser: `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/pdf.py`
- Python tests: `python_agent/tests/test_knowledge_ingestion_service.py`, `python_agent/tests/test_structured_document_parsers.py`
- Java runtime: `src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java`
- Java tests: `src/test/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncServiceTest.java`

The pre-existing untracked `python_agent/tests/test_http_request_body.py` was read and executed only. It was not modified, staged, or committed.

## Residual Considerations

- If `KNOWLEDGE_MAX_FILE_BYTES` is raised above 10 MiB, operators must also raise `KNOWLEDGE_PARSE_MAX_REQUEST_BYTES` to cover the new Base64 upper bound and JSON envelope. Keeping separate limits is intentional so non-knowledge Agent endpoints remain at 2 MiB.
- Fail-closed PDF handling rejects vector/image-only pages in mixed documents. OCR remains explicitly out of scope, so such documents require a text layer before ingestion.
