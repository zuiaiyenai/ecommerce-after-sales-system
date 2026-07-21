package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.GlobalExceptionHandler;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.DraftChunkResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.IngestionStatusResponse;
import com.ecommerce.aftersales.service.KnowledgeService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class KnowledgeManagementControllerTest {
    private KnowledgeService knowledgeService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        knowledgeService = mock(KnowledgeService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new KnowledgeManagementController(knowledgeService))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
    }

    @Test
    void fileImportOnlyAcceptsPdfMarkdownAndTextAndReturnsStringId() throws Exception {
        when(knowledgeService.createFileImport(any())).thenReturn(new FileImportResponse(42L, "PROCESSING", false));
        mockMvc.perform(multipart("/admin/knowledge/file-import")
                        .file(new MockMultipartFile("file", "policy.pdf", "application/pdf", "%PDF".getBytes()))
                        .param("knowledgeType", "after_sales_policy").param("scope", "MERCHANT")
                        .param("merchantCode", "MERCHANT_DEMO"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.documentId").value("42"));
    }

    @Test
    void fileImportRejectsUnsupportedFileType() throws Exception {
        mockMvc.perform(multipart("/admin/knowledge/file-import")
                        .file(new MockMultipartFile("file", "policy.docx", "application/octet-stream", "x".getBytes()))
                        .param("knowledgeType", "after_sales_policy"))
                .andExpect(status().isBadRequest());
        verifyNoInteractions(knowledgeService);
    }

    @Test
    void legacyImportEndpointsAreNotMapped() throws Exception {
        MockMvc noMappingMvc = MockMvcBuilders.standaloneSetup(new KnowledgeManagementController(knowledgeService)).build();
        for (String path : List.of("/admin/knowledge/import/text", "/admin/knowledge/upload", "/admin/knowledge/batch-upload")) {
            noMappingMvc.perform(post(path).contentType("application/json").content("{}"))
                    .andExpect(status().isNotFound());
        }
        verifyNoInteractions(knowledgeService);
    }

    @Test
    void lifecycleLongIdsAreSerializedAsStrings() throws Exception {
        long id = 9007199254740993L;
        ObjectMapper mapper = new ObjectMapper();

        var fileNode = mapper.readTree(mapper.writeValueAsString(new FileImportResponse(id, "PROCESSING", false)));
        String statusJson = mapper.writeValueAsString(new IngestionStatusResponse(id, "PUBLISHED", null, null, 3L, id));
        String chunkJson = mapper.writeValueAsString(new DraftChunkResponse(
                id, 0, List.of(), null, "draft", List.of(), List.of(), List.of(), "AGENT",
                BigDecimal.ONE, null, false, 3L));
        var statusNode = mapper.readTree(statusJson);
        var chunkNode = mapper.readTree(chunkJson);

        assertThat(fileNode.path("documentId").isTextual()).isTrue();
        assertThat(fileNode.path("documentId").textValue()).isEqualTo("9007199254740993");
        assertThat(statusNode.path("documentId").isTextual()).isTrue();
        assertThat(statusNode.path("documentId").textValue()).isEqualTo("9007199254740993");
        assertThat(statusNode.path("publishedRevision").isTextual()).isTrue();
        assertThat(statusNode.path("publishedRevision").textValue()).isEqualTo("9007199254740993");
        assertThat(chunkNode.path("chunkId").isTextual()).isTrue();
        assertThat(chunkNode.path("chunkId").textValue()).isEqualTo("9007199254740993");
    }
}
