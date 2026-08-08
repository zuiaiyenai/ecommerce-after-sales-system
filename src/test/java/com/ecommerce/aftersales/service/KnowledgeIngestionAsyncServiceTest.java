package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.config.AgentGatewayProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;
import java.util.Base64;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.when;

class KnowledgeIngestionAsyncServiceTest {

    @TempDir
    Path tempDir;

    @Test
    void fileParseSendsCanonicalAllowedMetadataForDocumentMerchant() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgeMetadataPolicy policy = mock(KnowledgeMetadataPolicy.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent.internal/api");
        when(policy.options("MERCHANT_DEMO")).thenReturn(Map.of(
                "productCategories", List.of(new KnowledgeMetadataPolicy.Option("headphone", "Headphone")),
                "scenes", List.of(new KnowledgeMetadataPolicy.Option("quality_issue", "Quality")),
                "intents", List.of(new KnowledgeMetadataPolicy.Option("refund", "Refund"))));
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                "id", 42L, "source_type", "after_sales_policy", "merchant_code", "MERCHANT_DEMO",
                "revision", 1L, "metadata", "{}")));
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenReturn(Map.of(
                "content", "policy", "chunks", List.of(Map.of("chunk_index", 0, "heading_path", List.of(),
                        "text", "policy", "classification_source", "RULE", "review_required", false))));
        Path file = tempDir.resolve("policy.md");
        Files.writeString(file, "# policy");

        new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, policy, draftService)
                .processFileImport(42L, file.toString(), "policy.md", 1L);

        ArgumentCaptor<HttpEntity> request = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).postForObject(eq("http://agent.internal/api/knowledge/parse"), request.capture(), eq(Map.class));
        Map<String, Object> body = (Map<String, Object>) request.getValue().getBody();
        assertThat(body.get("allowed_metadata")).isEqualTo(Map.of(
                "product_categories", List.of("headphone"), "scenes", List.of("quality_issue"), "intents", List.of("refund")));
        String encodedContent = String.valueOf(body.get("content_base64"));
        long jsonEnvelopeBytes = new ObjectMapper().writeValueAsBytes(body).length - encodedContent.length();
        long maxFileBytes = 10L * 1024 * 1024;
        long maxEncodedBytes = 4L * ((maxFileBytes + 2L) / 3L);
        assertThat(jsonEnvelopeBytes).isLessThanOrEqualTo(1024L * 1024);
        assertThat(maxEncodedBytes + jsonEnvelopeBytes).isLessThanOrEqualTo(15_029_592L);
    }

    @Test
    void textImportUsesPythonParserAndReplacesTheClaimedDraftWithoutDeletingPublishedChunks() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgeMetadataPolicy policy = mock(KnowledgeMetadataPolicy.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent.internal");
        when(policy.options("MERCHANT_DEMO")).thenReturn(Map.of(
                "productCategories", List.of(), "scenes", List.of(), "intents", List.of()));
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                "id", 42L, "source_type", "after_sales_policy", "merchant_code", "MERCHANT_DEMO",
                "revision", 7L, "metadata", "{\"ingestionSourceType\":\"TEXT\"}")));
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenReturn(Map.of(
                "content", "功能异常时提供问题凭证。", "chunks", List.of(Map.of(
                        "chunk_index", 0, "heading_path", List.of(), "text", "功能异常时提供问题凭证。",
                        "classification_source", "RULE", "review_required", false))));
        KnowledgeIngestionAsyncService service = new KnowledgeIngestionAsyncService(
                jdbcTemplate, restTemplate, properties, policy, draftService);

        service.processTextImport(42L, "功能异常时提供问题凭证。", 7L);

        ArgumentCaptor<HttpEntity> request = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).postForObject(eq("http://agent.internal/knowledge/parse"), request.capture(), eq(Map.class));
        Map<String, Object> body = (Map<String, Object>) request.getValue().getBody();
        assertThat(body.get("file_name")).isEqualTo("knowledge-42.txt");
        assertThat(new String(Base64.getDecoder().decode(String.valueOf(body.get("content_base64"))), java.nio.charset.StandardCharsets.UTF_8))
                .isEqualTo("功能异常时提供问题凭证。");
        verify(draftService).replaceParsedDraft(eq(42L), eq(7L), any(Map.class));
        verify(jdbcTemplate, never()).update(argThat(sql -> sql.contains("DELETE FROM knowledge_chunk")), any(Object[].class));
    }

    @Test
    void publishEmbedsDeterministicDocumentContextInsteadOfRawChunkText() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgePublishService publishService = mock(KnowledgePublishService.class);
        @SuppressWarnings("unchecked") ObjectProvider<KnowledgePublishService> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(publishService);
        Map<String, Object> row = new java.util.LinkedHashMap<>();
        row.put("title", "平台售后退款规则");
        row.put("source_code", "POLICY-2026");
        row.put("chunk_text", "body");
        row.put("heading_path", new String[]{"退款政策", "举证要求"});
        row.put("page_number", 3);
        row.put("chunk_metadata", "{\"page_start\":3,\"page_end\":4,\"content_types\":[\"paragraph\",\"list\"]}");
        row.put("document_metadata", "{\"ingestionSourceType\":\"FILE\",\"fileName\":\"policy.pdf\"}");
        when(publishService.targetDraft(42L, 6L)).thenReturn(List.of(row));
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class)))
                .thenReturn(Map.of("embeddings", List.of(java.util.Collections.nCopies(1024, 0.0d))));
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent/api");

        new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, mock(KnowledgeMetadataPolicy.class),
                mock(KnowledgeDraftService.class), provider).publish(42L, 6L);

        ArgumentCaptor<HttpEntity> request = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).postForObject(eq("http://agent/api/embeddings"), request.capture(), eq(Map.class));
        Map<String, Object> requestBody = (Map<String, Object>) request.getValue().getBody();
        List<String> embeddingChunks = (List<String>) requestBody.get("chunks");
        assertThat(embeddingChunks).hasSize(1);
        assertThat(embeddingChunks.getFirst())
                .contains("文档：平台售后退款规则")
                .contains("章节：退款政策 > 举证要求")
                .contains("位置：第 3-4 页")
                .contains("来源：policy.pdf / POLICY-2026")
                .contains("内容类型：paragraph、list")
                .endsWith("body");
    }

    @Test
    void fileWorkerUsesItsExplicitTargetRevisionForDraftReplacement() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgeMetadataPolicy policy = mock(KnowledgeMetadataPolicy.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent.internal/api");
        when(policy.options("MERCHANT_DEMO")).thenReturn(Map.of(
                "productCategories", List.of(), "scenes", List.of(), "intents", List.of()));
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                "id", 42L, "source_type", "after_sales_policy", "merchant_code", "MERCHANT_DEMO",
                "revision", 7L, "metadata", "{}")));
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenReturn(Map.of(
                "content", "policy", "chunks", List.of(Map.of("chunk_index", 0, "heading_path", List.of(),
                        "text", "policy", "classification_source", "RULE", "review_required", false))));
        Path file = tempDir.resolve("target-revision.md");
        Files.writeString(file, "# policy");

        new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, policy, draftService)
                .processFileImport(42L, file.toString(), "target-revision.md", 7L);

        verify(draftService).replaceParsedDraft(eq(42L), eq(7L), any(Map.class));
    }

    @Test
    void reprocessCanonicalizesFileAndTextModesAndRejectsUnknownModes() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgeMetadataPolicy policy = mock(KnowledgeMetadataPolicy.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent.internal/api");
        when(policy.options("MERCHANT_DEMO")).thenReturn(Map.of(
                "productCategories", List.of(), "scenes", List.of(), "intents", List.of()));
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenReturn(Map.of(
                "content", "parsed", "chunks", List.of(Map.of("chunk_index", 0, "heading_path", List.of(),
                        "text", "parsed", "classification_source", "RULE", "review_required", false))));
        Path file = tempDir.resolve("canonical-mode.md");
        Files.writeString(file, "# file body");
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                "id", 42L, "source_type", "faq", "merchant_code", "MERCHANT_DEMO", "content", "text fallback",
                "metadata", Map.of("ingestionSourceType", " file ", "fileStoragePath", file.toString(),
                        "fileName", "canonical-mode.md"))));
        when(jdbcTemplate.queryForList(anyString(), eq(43L))).thenReturn(List.of(Map.of(
                "id", 43L, "source_type", "faq", "merchant_code", "MERCHANT_DEMO", "content", "text body",
                "metadata", Map.of("ingestionSourceType", " text "))));
        when(jdbcTemplate.queryForList(anyString(), eq(44L))).thenReturn(List.of(Map.of(
                "id", 44L, "source_type", "faq", "merchant_code", "MERCHANT_DEMO", "content", "must not parse",
                "metadata", Map.of("ingestionSourceType", "url"))));
        KnowledgeIngestionAsyncService service = new KnowledgeIngestionAsyncService(
                jdbcTemplate, restTemplate, properties, policy, draftService);

        service.reprocessDocument(42L, 8L);
        service.reprocessDocument(43L, 9L);
        service.reprocessDocument(44L, 10L);

        ArgumentCaptor<HttpEntity> requests = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate, times(2)).postForObject(
                eq("http://agent.internal/api/knowledge/parse"), requests.capture(), eq(Map.class));
        List<Map<String, Object>> bodies = requests.getAllValues().stream()
                .map(HttpEntity::getBody)
                .map(body -> (Map<String, Object>) body)
                .toList();
        assertThat(bodies).extracting(body -> body.get("file_name"))
                .containsExactly("canonical-mode.md", "knowledge-43.txt");
        assertThat(new String(Base64.getDecoder().decode(String.valueOf(bodies.get(0).get("content_base64"))),
                java.nio.charset.StandardCharsets.UTF_8)).isEqualTo("# file body");
        assertThat(new String(Base64.getDecoder().decode(String.valueOf(bodies.get(1).get("content_base64"))),
                java.nio.charset.StandardCharsets.UTF_8)).isEqualTo("text body");
        verify(draftService).replaceParsedDraft(eq(42L), eq(8L), any(Map.class));
        verify(draftService).replaceParsedDraft(eq(43L), eq(9L), any(Map.class));
        verify(draftService, never()).replaceParsedDraft(eq(44L), eq(10L), any(Map.class));
        verify(draftService, never()).markParseFailed(eq(44L), eq(10L), anyString(), anyString());
    }

    @Test
    void parseHttpErrorPersistsWhitelistedPythonErrorCodeForTheTargetRevision() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgeMetadataPolicy policy = mock(KnowledgeMetadataPolicy.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent.internal/api");
        when(policy.options("MERCHANT_DEMO")).thenReturn(Map.of(
                "productCategories", List.of(), "scenes", List.of(), "intents", List.of()));
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                "id", 42L, "source_type", "after_sales_policy", "merchant_code", "MERCHANT_DEMO",
                "revision", 7L, "metadata", "{}")));
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenThrow(
                HttpClientErrorException.create(HttpStatus.UNPROCESSABLE_ENTITY, "unprocessable", HttpHeaders.EMPTY,
                        "{\"error\":\"PDF_ENCRYPTED\",\"message\":\"secret path\"}".getBytes(), null));
        Path file = tempDir.resolve("encrypted.pdf");
        Files.writeString(file, "pdf");

        new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, policy, draftService)
                .processFileImport(42L, file.toString(), "encrypted.pdf", 7L);

        verify(draftService).markParseFailed(eq(42L), eq(7L), eq("PDF_ENCRYPTED"), anyString());
    }

    @Test
    void structuredParserErrorsRemainStableAcrossTheJavaBoundary() throws Exception {
        for (String code : List.of("DOCUMENT_CONTENT_EMPTY", "DOCUMENT_CHUNKING_FAILED", "FILE_TOO_LARGE")) {
            JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
            RestTemplate restTemplate = mock(RestTemplate.class);
            KnowledgeMetadataPolicy policy = mock(KnowledgeMetadataPolicy.class);
            KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
            AgentGatewayProperties properties = new AgentGatewayProperties();
            properties.setBaseUrl("http://agent.internal/api");
            when(policy.options("MERCHANT_DEMO")).thenReturn(Map.of(
                    "productCategories", List.of(), "scenes", List.of(), "intents", List.of()));
            when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                    "id", 42L, "source_type", "after_sales_policy", "merchant_code", "MERCHANT_DEMO", "metadata", "{}")));
            HttpStatus status = "FILE_TOO_LARGE".equals(code) ? HttpStatus.PAYLOAD_TOO_LARGE : HttpStatus.UNPROCESSABLE_ENTITY;
            when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenThrow(
                    HttpClientErrorException.create(status, "parse failed", HttpHeaders.EMPTY,
                            ("{\"error\":\"" + code + "\",\"message\":\"parse failed\"}").getBytes(), null));
            Path file = tempDir.resolve(code + ".txt");
            Files.writeString(file, "text");

            new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, policy, draftService)
                    .processFileImport(42L, file.toString(), file.getFileName().toString(), 7L);

            verify(draftService).markParseFailed(eq(42L), eq(7L), eq(code), anyString());
        }
    }

    @Test
    void workersExposeOnlyExplicitRevisionEntryPoints() {
        assertThat(java.util.Arrays.stream(KnowledgeIngestionAsyncService.class.getDeclaredMethods())
                .filter(method -> method.getName().equals("processTextImport"))
                .map(java.lang.reflect.Method::getParameterCount)).containsExactly(3);
        assertThat(java.util.Arrays.stream(KnowledgeIngestionAsyncService.class.getDeclaredMethods())
                .filter(method -> method.getName().equals("reprocessDocument"))
                .map(java.lang.reflect.Method::getParameterCount)).containsExactly(2);
        assertThat(java.util.Arrays.stream(KnowledgeIngestionAsyncService.class.getDeclaredMethods())
                .filter(method -> method.getName().equals("processFileImport"))
                .map(java.lang.reflect.Method::getParameterCount)).containsExactly(4);
    }

    @Test
    void unknownHttpErrorUsesGenericCodeAndScrubsUnixPathsWithinTheMessageLimit() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgeMetadataPolicy policy = mock(KnowledgeMetadataPolicy.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent.internal/api");
        when(policy.options("MERCHANT_DEMO")).thenReturn(Map.of(
                "productCategories", List.of(), "scenes", List.of(), "intents", List.of()));
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                "id", 42L, "source_type", "after_sales_policy", "merchant_code", "MERCHANT_DEMO", "metadata", "{}")));
        String body = "{\"error\":\"UNEXPECTED\",\"message\":\"/srv/secret/customer-upload.txt " + "x".repeat(400) + "\"}";
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenThrow(
                HttpClientErrorException.create(HttpStatus.BAD_REQUEST, "bad request", HttpHeaders.EMPTY, body.getBytes(), null));
        Path file = tempDir.resolve("unknown.txt");
        Files.writeString(file, "text");

        new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, policy, draftService)
                .processFileImport(42L, file.toString(), "unknown.txt", 7L);

        ArgumentCaptor<String> message = ArgumentCaptor.forClass(String.class);
        verify(draftService).markParseFailed(eq(42L), eq(7L), eq("PARSE_FAILED"), message.capture());
        assertThat(message.getValue()).doesNotContain("/srv/secret").hasSizeLessThanOrEqualTo(300);
    }

    @Test
    void embeddingCountAndMalformedElementsFailTheSameTargetWithoutCommit() {
        List<Object> cases = new java.util.ArrayList<>(List.of(
                List.of(), List.of((Object) Map.of("error", "partial")), List.of((Object) "bad"),
                List.of(java.util.Collections.nCopies(1024, 0.0d), java.util.Collections.nCopies(1024, 0.0d))));
        cases.add(java.util.Collections.singletonList(null));
        for (Object embeddings : cases) {
            JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
            RestTemplate restTemplate = mock(RestTemplate.class);
            KnowledgePublishService publishService = mock(KnowledgePublishService.class);
            @SuppressWarnings("unchecked") ObjectProvider<KnowledgePublishService> provider = mock(ObjectProvider.class);
            when(provider.getIfAvailable()).thenReturn(publishService);
            when(publishService.targetDraft(42L, 6L)).thenReturn(List.of(Map.of("chunk_text", "draft")));
            AgentGatewayProperties properties = new AgentGatewayProperties();
            properties.setBaseUrl("http://agent/api");
            when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class))).thenReturn(Map.of("embeddings", embeddings));

            new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, mock(KnowledgeMetadataPolicy.class),
                    mock(KnowledgeDraftService.class), provider).publish(42L, 6L);

            verify(publishService).markEmbeddingFailed(42L, 6L, "EMBEDDING_FAILED");
            verify(publishService, never()).commitPublishedRevision(any(), any(Long.class), any());
        }
    }

    @Test
    void embeddingDimensionMustBeExactly1024BeforeCommit() {
        for (int size : List.of(1023, 1025)) {
            JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
            RestTemplate restTemplate = mock(RestTemplate.class);
            KnowledgePublishService publishService = mock(KnowledgePublishService.class);
            @SuppressWarnings("unchecked") ObjectProvider<KnowledgePublishService> provider = mock(ObjectProvider.class);
            when(provider.getIfAvailable()).thenReturn(publishService);
            when(publishService.targetDraft(42L, 6L)).thenReturn(List.of(Map.of("chunk_text", "draft")));
            AgentGatewayProperties properties = new AgentGatewayProperties();
            properties.setBaseUrl("http://agent/api");
            when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class)))
                    .thenReturn(Map.of("embeddings", List.of(java.util.Collections.nCopies(size, 0.0d))));

            new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, mock(KnowledgeMetadataPolicy.class),
                    mock(KnowledgeDraftService.class), provider).publish(42L, 6L);

            verify(publishService).markEmbeddingFailed(42L, 6L, "EMBEDDING_FAILED");
            verify(publishService, never()).commitPublishedRevision(any(), any(Long.class), any());
        }
    }

    @Test
    void exactly1024EmbeddingValuesCommitTheFrozenTargetRevision() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgePublishService publishService = mock(KnowledgePublishService.class);
        @SuppressWarnings("unchecked") ObjectProvider<KnowledgePublishService> provider = mock(ObjectProvider.class);
        when(provider.getIfAvailable()).thenReturn(publishService);
        when(publishService.targetDraft(42L, 6L)).thenReturn(List.of(Map.of("chunk_text", "draft")));
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent/api");
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class)))
                .thenReturn(Map.of("embeddings", List.of(java.util.Collections.nCopies(1024, 0.0d))));

        new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties, mock(KnowledgeMetadataPolicy.class),
                mock(KnowledgeDraftService.class), provider).publish(42L, 6L);

        verify(publishService).commitPublishedRevision(eq(42L), eq(6L), any());
        verify(publishService, never()).markEmbeddingFailed(any(), any(Long.class), anyString());
    }

}
