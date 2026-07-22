package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.config.AgentGatewayProperties;
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
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.never;
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
                .processFileImport(42L, file.toString(), "policy.md");

        ArgumentCaptor<HttpEntity> request = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).postForObject(eq("http://agent.internal/api/knowledge/parse"), request.capture(), eq(Map.class));
        Map<String, Object> body = (Map<String, Object>) request.getValue().getBody();
        assertThat(body.get("allowed_metadata")).isEqualTo(Map.of(
                "product_categories", List.of("headphone"), "scenes", List.of("quality_issue"), "intents", List.of("refund")));
    }

    @Test
    void generatedChunkMetadataContainsAllStructuredRetrievalFields() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setBaseUrl("http://agent.internal");
        KnowledgeIngestionAsyncService service =
                new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, properties);

        Map<String, Object> document = Map.ofEntries(
                Map.entry("id", 42L),
                Map.entry("source_type", "after_sales_policy"),
                Map.entry("source_code", "POLICY-001"),
                Map.entry("merchant_code", "MERCHANT_DEMO"),
                Map.entry("title", "耳机质量问题政策"),
                Map.entry("content", "功能异常时提供问题凭证。"),
                Map.entry("product_category", "headphone"),
                Map.entry("scene", "quality_issue"),
                Map.entry("intent", "exchange"),
                Map.entry("policy_version", "v2.0"),
                Map.entry("tags", "[\"耳机\",\"换货\"]"),
                Map.entry("metadata", "{}"),
                Map.entry("status", 1)
        );
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(document));
        when(restTemplate.postForObject(anyString(), any(HttpEntity.class), eq(Map.class)))
                .thenReturn(Map.of("embeddings", List.of(List.of(0.1D, 0.2D))));

        service.processTextImport(42L, "功能异常时提供问题凭证。");

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object[]> arguments = ArgumentCaptor.forClass(Object[].class);
        verify(jdbcTemplate, atLeastOnce()).update(sql.capture(), arguments.capture());
        int chunkInsertIndex = -1;
        for (int i = 0; i < sql.getAllValues().size(); i++) {
            if (sql.getAllValues().get(i).contains("INSERT INTO knowledge_chunk")) {
                chunkInsertIndex = i;
                break;
            }
        }
        assertThat(chunkInsertIndex).isGreaterThanOrEqualTo(0);
        String metadata = String.valueOf(arguments.getAllValues().get(chunkInsertIndex)[5]);
        assertThat(metadata)
                .contains("\"product_category\":\"headphone\"")
                .contains("\"scene\":\"quality_issue\"")
                .contains("\"intent\":\"exchange\"")
                .contains("\"policy_version\":\"v2.0\"")
                .contains("\"tags\":[\"耳机\",\"换货\"]");
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
    void legacyNoRevisionEntryPointDoesNotReprocessFileDocuments() {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        RestTemplate restTemplate = mock(RestTemplate.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        when(jdbcTemplate.queryForList(anyString(), eq(42L))).thenReturn(List.of(Map.of(
                "id", 42L, "content", "", "metadata", "{\"ingestionSourceType\":\"FILE\"}")));

        new KnowledgeIngestionAsyncService(jdbcTemplate, restTemplate, new AgentGatewayProperties(), mock(KnowledgeMetadataPolicy.class), draftService)
                .reprocessDocument(42L);

        verifyNoInteractions(restTemplate, draftService);
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
