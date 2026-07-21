package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class KnowledgeServiceTest {

    @TempDir
    Path tempDir;

    @Test
    void textImportStartsAsyncIngestionOnlyAfterThePgTransactionCommits() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString()
        );
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(42L);

        KnowledgeUploadDto.TextImportRequest request = new KnowledgeUploadDto.TextImportRequest();
        request.setTitle("退款规则");
        request.setKnowledgeType("refund_policy");
        request.setMerchantCode("MERCHANT_DEMO");
        request.setContent("退款审核通过后原路退回。");

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.createTextImport(request);

            verifyNoInteractions(asyncService);
            List<TransactionSynchronization> synchronizations =
                    TransactionSynchronizationManager.getSynchronizations();
            assertThat(synchronizations).hasSize(1);

            synchronizations.getFirst().afterCommit();
            verify(asyncService).processTextImport(42L, request.getContent());
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
    }

    @Test
    void compatibilityUploadPersistsStructuredRagMetadataAndKeepsInternalMetadataProtected() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString()
        );
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(77L);

        KnowledgeUploadDto.UploadRequest request = new KnowledgeUploadDto.UploadRequest();
        request.setSourceType("after_sales_policy");
        request.setSourceCode("POLICY-QUALITY-001");
        request.setMerchantCode("MERCHANT_001");
        request.setTitle("质量问题换货政策");
        request.setContent("功能异常且证据完整时可申请换货。");
        request.setProductCategory("headphone");
        request.setScene("quality_issue");
        request.setIntent("exchange");
        request.setPolicyVersion("v2.0");
        request.setTags(List.of(" 质量问题 ", "换货", "换货"));
        request.setMetadata(Map.of("owner", "after-sales", "ingestionStatus", "SUCCESS"));

        service.uploadKnowledge(request);

        org.mockito.ArgumentCaptor<Object[]> arguments = org.mockito.ArgumentCaptor.forClass(Object[].class);
        verify(jdbcTemplate).queryForObject(anyString(), eq(Long.class), arguments.capture());
        Object[] values = arguments.getValue();
        assertThat(values[0]).isEqualTo("after_sales_policy");
        assertThat(values[1]).isEqualTo("POLICY-QUALITY-001");
        assertThat(values[2]).isEqualTo("MERCHANT_001");
        assertThat(values[5]).isEqualTo("headphone");
        assertThat(values[6]).isEqualTo("quality_issue");
        assertThat(values[7]).isEqualTo("exchange");
        assertThat(values[8]).isEqualTo("v2.0");
        assertThat(String.valueOf(values[9])).isEqualTo("[\"质量问题\",\"换货\"]");
        assertThat(String.valueOf(values[10]))
                .contains("\"owner\":\"after-sales\"")
                .contains("\"ingestionStatus\":\"PROCESSING\"");
        verify(asyncService).processTextImport(77L, request.getContent());
    }

    @Test
    void metadataOnlyUpdatePersistsFiltersAndSynchronizesExistingChunkMetadataWithoutReembedding() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = spy(new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v3.0"), tempDir.toString()
        ));
        KnowledgeUploadDto.KnowledgeInfo current = new KnowledgeUploadDto.KnowledgeInfo();
        current.setSourceType("after_sales_policy");
        current.setMerchantCode("MERCHANT_DEMO");
        current.setMetadata(Map.of("scope", "MERCHANT", "owner", "old"));
        doReturn(current).when(service).getKnowledgeById(42L);

        KnowledgeUploadDto.UpdateRequest request = new KnowledgeUploadDto.UpdateRequest();
        request.setProductCategory(" phone ");
        request.setScene("");
        request.setIntent("refund");
        request.setPolicyVersion("v3.0");
        request.setTags(List.of("手机", "退款"));
        request.setMetadata(Map.of("owner", "new", "deleted", true));

        service.updateKnowledge(42L, request);

        org.mockito.ArgumentCaptor<String> sql = org.mockito.ArgumentCaptor.forClass(String.class);
        org.mockito.ArgumentCaptor<Object[]> arguments = org.mockito.ArgumentCaptor.forClass(Object[].class);
        verify(jdbcTemplate, atLeastOnce()).update(sql.capture(), arguments.capture());
        int documentUpdateIndex = -1;
        for (int i = 0; i < sql.getAllValues().size(); i++) {
            if (sql.getAllValues().get(i).contains("product_category = CASE")) {
                documentUpdateIndex = i;
                break;
            }
        }
        assertThat(documentUpdateIndex).isGreaterThanOrEqualTo(0);
        Object[] values = arguments.getAllValues().get(documentUpdateIndex);
        assertThat(values[4]).isEqualTo("phone");
        assertThat(values[6]).isNull();
        assertThat(values[8]).isEqualTo("refund");
        assertThat(values[10]).isEqualTo("v3.0");
        assertThat(String.valueOf(values[12])).isEqualTo("[\"手机\",\"退款\"]");
        assertThat(String.valueOf(values[13]))
                .contains("\"owner\":\"new\"")
                .doesNotContain("\"deleted\":true");
        assertThat(sql.getAllValues()).anyMatch(value -> value.contains("UPDATE knowledge_chunk kc"));
        verifyNoInteractions(asyncService);
    }

    @Test
    void globalKnowledgeCanLoadControlledMetadataOptionsWithoutMerchantValidation() throws Exception {
        KnowledgeService service = new KnowledgeService(
                mock(JdbcTemplate.class),
                mock(KnowledgeIngestionAsyncService.class),
                metadataPolicy("v4.0"),
                tempDir.toString()
        );

        Map<String, Object> options = service.getMetadataOptions("GLOBAL");

        assertThat(options.get("currentPolicyVersion")).isEqualTo("v4.0");
        assertThat(options.get("productCategories")).isNotNull();
        assertThat(options.get("scenes")).isNotNull();
        assertThat(options.get("intents")).isNotNull();
    }

    @Test
    void retryAtomicallyIncrementsRevisionOnlyFromFailureAndDispatchesThatRevisionAfterCommit() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(2L);
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), draftService, tempDir.toString()
        );

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.retryFileImport(42L);
            verifyNoInteractions(asyncService);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).reprocessDocument(42L, 2L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(sql.capture(), eq(Long.class), any(Object[].class));
        assertThat(sql.getValue()).contains("revision = revision + 1").contains("review_status IN");
    }

    @Test
    void newFileImportDispatchesInitialRevisionOneAfterCommit() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(42L);
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), draftService, tempDir.toString()
        );
        MockMultipartFile file = new MockMultipartFile("file", "policy.txt", "text/plain", "draft".getBytes());

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.createFileImport(new com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand(
                    null, "faq", "MERCHANT", "MERCHANT_DEMO", file));
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).processFileImport(eq(42L), anyString(), eq("policy.txt"), eq(1L));
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
    }

    @Test
    void concurrentFileDuplicateUsesConflictReturningCleansOnlyItsStoredFileAndDoesNotDispatchAgain() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class))).thenReturn(
                List.of(), List.of(Map.of("id", 77L, "review_status", "REVIEW_REQUIRED")));
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class)))
                .thenThrow(new org.springframework.dao.EmptyResultDataAccessException(1));
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), draftService, tempDir.toString());
        MockMultipartFile file = new MockMultipartFile("file", "policy.txt", "text/plain", "draft".getBytes());

        var response = service.createFileImport(new com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand(
                null, "faq", "MERCHANT", "MERCHANT_DEMO", file));

        assertThat(response.documentId()).isEqualTo(77L);
        assertThat(response.reviewStatus()).isEqualTo("REVIEW_REQUIRED");
        assertThat(response.duplicate()).isTrue();
        ArgumentCaptor<String> insertSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(insertSql.capture(), eq(Long.class), any(Object[].class));
        assertThat(insertSql.getValue()).contains("ON CONFLICT (merchant_code, source_type, content_hash)")
                .contains("DO NOTHING RETURNING id")
                .contains("COALESCE(metadata ->> 'deleted', 'false') <> 'true'");
        verify(jdbcTemplate, org.mockito.Mockito.times(2)).queryForList(anyString(), any(Object[].class));
        verifyNoInteractions(asyncService);
    }

    @Test
    void fileImportRejectsMissingBlankAndMismatchedMimeWhileAcceptingTheTenMegabyteBoundary() throws Exception {
        KnowledgeService validationService = new KnowledgeService(
                mock(JdbcTemplate.class), mock(KnowledgeIngestionAsyncService.class), metadataPolicy("v2.0"), tempDir.toString());
        for (MockMultipartFile invalid : List.of(
                new MockMultipartFile("file", "policy.pdf", null, "x".getBytes()),
                new MockMultipartFile("file", "policy.pdf", " ", "x".getBytes()),
                new MockMultipartFile("file", "policy.pdf", "text/plain", "x".getBytes()))) {
            assertThatIllegalArgumentException().isThrownBy(() -> validationService.createFileImport(
                    new com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand(null, "faq", "MERCHANT", "MERCHANT_DEMO", invalid)));
        }
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(Map.of("id", 1L, "review_status", "PROCESSING")));
        KnowledgeService boundaryService = new KnowledgeService(
                jdbcTemplate, mock(KnowledgeIngestionAsyncService.class), metadataPolicy("v2.0"), tempDir.toString());
        MockMultipartFile boundary = new MockMultipartFile("file", "policy.txt", "text/plain", new byte[10 * 1024 * 1024]);

        assertThat(boundaryService.createFileImport(new com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand(
                null, "faq", "MERCHANT", "MERCHANT_DEMO", boundary)).duplicate()).isTrue();
    }

    @Test
    void reindexClaimsFileRevisionWithoutChangingPublishedPointerAndDispatchesTheClaimedRevisionAfterCommit() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = new KnowledgeService(jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString());
        when(jdbcTemplate.queryForList(anyString(), eq(Long.class))).thenReturn(List.of(42L));
        when(jdbcTemplate.queryForList(startsWith("SELECT COALESCE"), eq(String.class), eq(42L))).thenReturn(List.of("FILE"));
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), eq(42L))).thenReturn(9L);

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.reindexAll();
            verifyNoInteractions(asyncService);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).reprocessDocument(42L, 9L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
        ArgumentCaptor<String> claimSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(claimSql.capture(), eq(Long.class), eq(42L));
        assertThat(claimSql.getValue()).contains("revision = revision + 1").contains("'PUBLISHED'")
                .doesNotContain("published_revision =");
    }

    @Test
    void reindexDoesNotDispatchWhenAFileClaimIsStaleOrDeleted() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = new KnowledgeService(jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString());
        when(jdbcTemplate.queryForList(anyString(), eq(Long.class))).thenReturn(List.of(42L));
        when(jdbcTemplate.queryForList(startsWith("SELECT COALESCE"), eq(String.class), eq(42L))).thenReturn(List.of("FILE"));
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), eq(42L)))
                .thenThrow(new org.springframework.dao.EmptyResultDataAccessException(1));

        service.reindexAll();

        verifyNoInteractions(asyncService);
    }

    private KnowledgeMetadataPolicy metadataPolicy(String policyVersion) {
        AgentPolicyCatalogService policyCatalogService = mock(AgentPolicyCatalogService.class);
        when(policyCatalogService.getCatalog()).thenReturn(Map.of(
                "merchants", Map.of("MERCHANT_DEMO", Map.of(), "MERCHANT_001", Map.of())
        ));
        when(policyCatalogService.getMerchantPolicy(any()))
                .thenReturn(Map.of("service_policy", Map.of("policy_version", policyVersion)));
        return new KnowledgeMetadataPolicy(policyCatalogService);
    }
}
