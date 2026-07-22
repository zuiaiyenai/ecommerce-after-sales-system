package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.nio.file.Path;
import java.nio.file.Files;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatIllegalArgumentException;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
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
    @SuppressWarnings("unchecked")
    void listMapsAuthoritativeReviewLifecycleFieldsFromKnowledgeDocument() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        ResultSet resultSet = mock(ResultSet.class);
        LocalDateTime validFrom = LocalDateTime.of(2026, 7, 22, 8, 0);
        LocalDateTime validTo = LocalDateTime.of(2026, 8, 22, 8, 0);
        when(resultSet.getLong("id")).thenReturn(9007199254740993L);
        when(resultSet.getString("source_type")).thenReturn("after_sales_policy");
        when(resultSet.getString("source_code")).thenReturn("POLICY-1");
        when(resultSet.getString("merchant_code")).thenReturn("MERCHANT_DEMO");
        when(resultSet.getString("title")).thenReturn("售后政策");
        when(resultSet.getString("tags")).thenReturn("[]");
        when(resultSet.getString("metadata")).thenReturn("{}");
        when(resultSet.getInt("status")).thenReturn(1);
        when(resultSet.getTimestamp("created_at")).thenReturn(Timestamp.valueOf(validFrom));
        when(resultSet.getTimestamp("updated_at")).thenReturn(Timestamp.valueOf(validFrom));
        when(resultSet.getInt("chunk_count")).thenReturn(2);
        when(resultSet.getString("review_status")).thenReturn("REVIEW_REQUIRED");
        when(resultSet.getLong("revision")).thenReturn(8L);
        when(resultSet.getObject("published_revision")).thenReturn(6L);
        when(resultSet.getTimestamp("valid_from")).thenReturn(Timestamp.valueOf(validFrom));
        when(resultSet.getTimestamp("valid_to")).thenReturn(Timestamp.valueOf(validTo));
        when(jdbcTemplate.query(anyString(), any(Object[].class), any(RowMapper.class))).thenAnswer(invocation -> {
            RowMapper<KnowledgeUploadDto.KnowledgeInfo> mapper = invocation.getArgument(2);
            return List.of(mapper.mapRow(resultSet, 0));
        });
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, mock(KnowledgeIngestionAsyncService.class), metadataPolicy("v2.0"), tempDir.toString());

        var records = service.listKnowledge(null, null, 1, 20);

        assertThat(records).hasSize(1);
        var info = records.getFirst();
        assertThat(info.getReviewStatus()).isEqualTo("REVIEW_REQUIRED");
        assertThat(info.getRevision()).isEqualTo(8L);
        assertThat(info.getPublishedRevision()).isEqualTo(6L);
        assertThat(info.getValidFrom()).isEqualTo(validFrom);
        assertThat(info.getValidTo()).isEqualTo(validTo);
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).query(sql.capture(), any(Object[].class), any(RowMapper.class));
        assertThat(sql.getValue()).contains("d.review_status", "d.revision", "d.published_revision", "d.valid_from", "d.valid_to");
    }

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
            verify(asyncService).processTextImport(42L, request.getContent(), 1L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
        ArgumentCaptor<String> insertSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(insertSql.capture(), eq(Long.class), any(Object[].class));
        assertThat(insertSql.getValue())
                .contains("review_status", "revision", "published_revision")
                .contains("'PROCESSING'", "1", "NULL");
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
        request.setMetadata(Map.of(
                "owner", "after-sales",
                "ingestionStatus", "SUCCESS",
                "fileName", "camel-forged.pdf",
                "file_name", "snake-forged.pdf"));

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
                .contains("\"ingestionStatus\":\"PROCESSING\"")
                .doesNotContain("camel-forged.pdf", "snake-forged.pdf", "\"fileName\"", "\"file_name\"");
        verify(asyncService).processTextImport(77L, request.getContent(), 1L);
    }

    @Test
    void compatibilityFileImportInitializesProcessingRevisionAndDispatchesRevisionOneAfterCommit() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(43L);
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString());
        MockMultipartFile file = new MockMultipartFile("file", "policy.md", "text/markdown", "# policy".getBytes());

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.createFileImport("Policy", "faq", "MERCHANT", "MERCHANT_DEMO", "ENABLED",
                    "FAQ-43", null, null, null, List.of(), file);
            verifyNoInteractions(asyncService);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).processFileImport(eq(43L), anyString(), eq("policy.md"), eq(1L));
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }

        ArgumentCaptor<String> insertSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(insertSql.capture(), eq(Long.class), any(Object[].class));
        assertThat(insertSql.getValue())
                .contains("review_status", "revision", "published_revision")
                .contains("'PROCESSING'", "1", "NULL");
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
    void contentUpdateAtomicallyClaimsRevisionAndDispatchesOnlyAfterCommit() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = spy(new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v3.0"), tempDir.toString()));
        KnowledgeUploadDto.KnowledgeInfo current = currentKnowledge(4L, "PUBLISHED");
        doReturn(current).when(service).getKnowledgeById(42L);
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class))).thenReturn(5L);
        KnowledgeUploadDto.UpdateRequest request = new KnowledgeUploadDto.UpdateRequest();
        request.setContent("new body");

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.updateKnowledge(42L, request);
            verifyNoInteractions(asyncService);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).processTextImport(42L, "new body", 5L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }

        ArgumentCaptor<String> claimSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(claimSql.capture(), eq(Long.class), any(Object[].class));
        assertThat(claimSql.getValue())
                .contains("revision = revision + 1", "review_status = 'PROCESSING'", "content = ?", "RETURNING revision")
                .contains("review_status IN", "- 'errorCode' - 'errorMessage'")
                .doesNotContain("published_revision =");
    }

    @Test
    void contentUpdateClaimFailureReturnsConflictWithoutDispatchingWorker() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = spy(new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v3.0"), tempDir.toString()));
        doReturn(currentKnowledge(4L, "PUBLISHED")).when(service).getKnowledgeById(42L);
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class)))
                .thenThrow(new org.springframework.dao.EmptyResultDataAccessException(1));
        KnowledgeUploadDto.UpdateRequest request = new KnowledgeUploadDto.UpdateRequest();
        request.setContent("new body");

        assertThatThrownBy(() -> service.updateKnowledge(42L, request))
                .isInstanceOf(com.ecommerce.aftersales.common.KnowledgeRevisionConflictException.class);
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
        try (var storedFiles = Files.walk(tempDir)) {
            assertThat(storedFiles.filter(Files::isRegularFile)).isEmpty();
        }
        ArgumentCaptor<String> insertSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(insertSql.capture(), eq(Long.class), any(Object[].class));
        assertThat(insertSql.getValue()).contains("ON CONFLICT (merchant_code, source_type, content_hash)")
                .contains("DO NOTHING RETURNING id")
                .contains("COALESCE(metadata ->> 'deleted', 'false') <> 'true'");
        verify(jdbcTemplate, org.mockito.Mockito.times(2)).queryForList(anyString(), any(Object[].class));
        verifyNoInteractions(asyncService);
    }

    @Test
    void conflictWithNoLongerActiveDuplicateStillCleansItsStoredFileBeforeFailing() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        when(jdbcTemplate.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(), List.of());
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), any(Object[].class)))
                .thenThrow(new org.springframework.dao.EmptyResultDataAccessException(1));
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), draftService, tempDir.toString());
        MockMultipartFile file = new MockMultipartFile("file", "policy.txt", "text/plain", "draft".getBytes());

        org.assertj.core.api.Assertions.assertThatThrownBy(() -> service.createFileImport(
                new com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand(
                        null, "faq", "MERCHANT", "MERCHANT_DEMO", file)))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("Duplicate knowledge import was not found after conflict");

        try (var storedFiles = Files.walk(tempDir)) {
            assertThat(storedFiles.filter(Files::isRegularFile)).isEmpty();
        }
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
        KnowledgeIngestionAsyncService boundaryAsyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService boundaryService = new KnowledgeService(
                jdbcTemplate, boundaryAsyncService, metadataPolicy("v2.0"), tempDir.toString());
        MockMultipartFile boundary = new MockMultipartFile("file", "policy.txt", "text/plain", new byte[10 * 1024 * 1024]);

        var duplicate = boundaryService.createFileImport(new com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand(
                null, "faq", "MERCHANT", "MERCHANT_DEMO", boundary));
        assertThat(duplicate.duplicate()).isTrue();
        assertThat(duplicate.reviewStatus()).isEqualTo("PROCESSING");
        verifyNoInteractions(boundaryAsyncService);
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
    void reindexClaimsTextRevisionAndDispatchesTheExplicitRevisionAfterCommit() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = new KnowledgeService(jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString());
        when(jdbcTemplate.queryForList(anyString(), eq(Long.class))).thenReturn(List.of(43L));
        when(jdbcTemplate.queryForList(startsWith("SELECT COALESCE"), eq(String.class), eq(43L))).thenReturn(List.of("TEXT"));
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), eq(43L))).thenReturn(10L);

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.reindexAll();
            verifyNoInteractions(asyncService);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).reprocessDocument(43L, 10L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
        ArgumentCaptor<String> claimSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(claimSql.capture(), eq(Long.class), eq(43L));
        assertThat(claimSql.getValue()).contains("revision = revision + 1", "review_status = 'PROCESSING'")
                .contains("ingestionSourceType", "'FILE'", "'TEXT'")
                .doesNotContain("published_revision =");
    }

    @Test
    void syncTextDocumentClaimsRevisionBeforeDispatchingTheWorker() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = spy(new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString()));
        doReturn(currentKnowledge(10L, "PUBLISHED")).when(service).getKnowledgeById(43L);
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), eq(43L))).thenReturn(11L);

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.syncKnowledge(43L);
            verifyNoInteractions(asyncService);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).reprocessDocument(43L, 11L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }
    }

    @Test
    void reindexTreatsMissingOrBlankSourceMarkerAsLegacyTextWhenClaimingRevision() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), tempDir.toString());
        when(jdbcTemplate.queryForList(anyString(), eq(Long.class))).thenReturn(List.of(44L));
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), eq(44L))).thenReturn(12L);

        TransactionSynchronizationManager.initSynchronization();
        TransactionSynchronizationManager.setActualTransactionActive(true);
        try {
            service.reindexAll();
            verifyNoInteractions(asyncService);
            TransactionSynchronizationManager.getSynchronizations().getFirst().afterCommit();
            verify(asyncService).reprocessDocument(44L, 12L);
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
            TransactionSynchronizationManager.setActualTransactionActive(false);
        }

        ArgumentCaptor<String> claimSql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(claimSql.capture(), eq(Long.class), eq(44L));
        assertThat(claimSql.getValue())
                .contains("COALESCE(NULLIF(metadata ->> 'ingestionSourceType', ''), 'TEXT')")
                .contains("IN ('FILE', 'TEXT')");
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

    @Test
    void retrySqlRetainsDeletedGuardAndDoesNotDispatchWhenTheDocumentIsDeleted() throws Exception {
        JdbcTemplate jdbcTemplate = mock(JdbcTemplate.class);
        KnowledgeIngestionAsyncService asyncService = mock(KnowledgeIngestionAsyncService.class);
        KnowledgeDraftService draftService = mock(KnowledgeDraftService.class);
        when(jdbcTemplate.queryForObject(anyString(), eq(Long.class), eq(42L)))
                .thenThrow(new org.springframework.dao.EmptyResultDataAccessException(1));
        KnowledgeService service = new KnowledgeService(
                jdbcTemplate, asyncService, metadataPolicy("v2.0"), draftService, tempDir.toString());

        org.assertj.core.api.Assertions.assertThatThrownBy(() -> service.retryFileImport(42L))
                .isInstanceOf(com.ecommerce.aftersales.common.BizException.class);

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForObject(sql.capture(), eq(Long.class), eq(42L));
        assertThat(sql.getValue()).contains("COALESCE(metadata ->> 'deleted', 'false') <> 'true'");
        verifyNoInteractions(asyncService, draftService);
    }

    private KnowledgeMetadataPolicy metadataPolicy(String policyVersion) {
        AgentPolicyCatalogService policyCatalogService = mock(AgentPolicyCatalogService.class);
        when(policyCatalogService.getCatalog()).thenReturn(Map.of(
                "merchants", Map.of("MERCHANT_DEMO", Map.of(), "MERCHANT_001", Map.of())
        ));
        when(policyCatalogService.getMerchantPolicy(any()))
                .thenReturn(Map.of("service_policy", Map.of(
                        "policy_code", "AFTER_SALES_POLICY", "policy_version", policyVersion)));
        return new KnowledgeMetadataPolicy(policyCatalogService);
    }

    private KnowledgeUploadDto.KnowledgeInfo currentKnowledge(long revision, String reviewStatus) {
        KnowledgeUploadDto.KnowledgeInfo current = new KnowledgeUploadDto.KnowledgeInfo();
        current.setSourceType("faq");
        current.setMerchantCode("MERCHANT_DEMO");
        current.setMetadata(Map.of("scope", "MERCHANT", "errorCode", "OLD", "errorMessage", "old"));
        current.setRevision(revision);
        current.setReviewStatus(reviewStatus);
        return current;
    }

}
