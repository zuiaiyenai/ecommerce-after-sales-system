package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.DraftChunkResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportCommand;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.FileImportResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.IngestionStatusResponse;
import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import com.ecommerce.aftersales.service.KnowledgeService;
import com.ecommerce.aftersales.service.KnowledgeDraftService;
import com.ecommerce.aftersales.service.KnowledgePublishService;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Locale;
import java.util.Map;

@RestController
@RequestMapping("/admin/knowledge")
public class KnowledgeManagementController {
    private final KnowledgeService knowledgeService;
    private final KnowledgeDraftService draftService;
    private final KnowledgePublishService publishService;

    @Autowired
    public KnowledgeManagementController(KnowledgeService knowledgeService, KnowledgeDraftService draftService,
                                         KnowledgePublishService publishService) {
        this.knowledgeService = knowledgeService;
        this.draftService = draftService;
        this.publishService = publishService;
    }

    public KnowledgeManagementController(KnowledgeService knowledgeService) {
        this(knowledgeService, null, null);
    }

    @PostMapping(value = "/file-import", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<FileImportResponse> fileImport(
            @RequestParam String knowledgeType,
            @RequestParam(defaultValue = "MERCHANT") String scope,
            @RequestParam(required = false) String merchantCode,
            @RequestParam(required = false) String title,
            @RequestPart MultipartFile file
    ) {
        String name = file.getOriginalFilename() == null ? "" : file.getOriginalFilename().toLowerCase(Locale.ROOT);
        if (!(name.endsWith(".pdf") || name.endsWith(".md") || name.endsWith(".txt"))) {
            throw new BizException("Unsupported file type");
        }
        return ApiResponse.success("File import created", knowledgeService.createFileImport(
                new FileImportCommand(title, knowledgeType, scope, merchantCode, file)));
    }

    @GetMapping("/{id:\\d+}/ingestion-status")
    public ApiResponse<IngestionStatusResponse> ingestionStatus(@PathVariable Long id) {
        return ApiResponse.success("Query successful", knowledgeService.ingestionStatus(id));
    }

    @GetMapping("/{id:\\d+}/draft")
    public ApiResponse<List<DraftChunkResponse>> draft(@PathVariable Long id) {
        return ApiResponse.success("Query successful", knowledgeService.draft(id));
    }

    @PutMapping("/{id:\\d+}/draft")
    public ApiResponse<Map<String, String>> updateDraft(@PathVariable Long id, @RequestBody Map<String, Object> request) {
        long revision = draftService.updateDraftDocument(id, longValue(request, "expectedRevision"), request);
        return ApiResponse.success("Draft updated", Map.of("documentId", String.valueOf(id), "revision", String.valueOf(revision)));
    }

    @PutMapping("/{id:\\d+}/draft/chunks/{chunkId:\\d+}")
    public ApiResponse<Map<String, String>> updateDraftChunk(@PathVariable Long id, @PathVariable Long chunkId,
                                                               @RequestBody Map<String, Object> request) {
        long revision = draftService.updateDraftChunk(id, chunkId, longValue(request, "expectedRevision"), request);
        return ApiResponse.success("Draft chunk updated", Map.of("documentId", String.valueOf(id), "revision", String.valueOf(revision)));
    }

    @PostMapping("/{id:\\d+}/publish")
    public ApiResponse<Map<String, String>> publish(@PathVariable Long id, @RequestBody PublishRequest request) {
        if (request == null || request.expectedRevision() == null) throw new BizException("expectedRevision is required");
        long revision = publishService.startPublishing(id, request.expectedRevision());
        return ApiResponse.success("Publishing started", Map.of("documentId", String.valueOf(id), "targetRevision", String.valueOf(revision)));
    }

    @PostMapping("/{id:\\d+}/retry")
    public ApiResponse<IngestionStatusResponse> retry(@PathVariable Long id) {
        return ApiResponse.success("Retry created", knowledgeService.retryFileImport(id));
    }

    @GetMapping("/metadata-options")
    public ApiResponse<Map<String, Object>> getMetadataOptions(@RequestParam(required = false) String merchantCode) {
        return ApiResponse.success("Query successful", knowledgeService.getMetadataOptions(merchantCode));
    }

    @GetMapping("/list")
    public ApiResponse<List<KnowledgeUploadDto.KnowledgeInfo>> listKnowledge(
            @RequestParam(required = false) String sourceType,
            @RequestParam(required = false) String merchantCode,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "20") Integer pageSize
    ) {
        return ApiResponse.success("Query successful", knowledgeService.listKnowledge(sourceType, merchantCode, page, pageSize));
    }

    @GetMapping("/{id:\\d+}")
    public ApiResponse<KnowledgeUploadDto.KnowledgeInfo> getKnowledge(@PathVariable Long id) {
        return ApiResponse.success("Query successful", knowledgeService.getKnowledgeById(id));
    }

    @PutMapping("/{id:\\d+}")
    public ApiResponse<Map<String, Object>> updateKnowledge(@PathVariable Long id, @RequestBody KnowledgeUploadDto.UpdateRequest request) {
        return ApiResponse.success("Updated", knowledgeService.updateKnowledge(id, request));
    }

    @DeleteMapping("/{id:\\d+}")
    public ApiResponse<Void> deleteKnowledge(@PathVariable Long id) {
        knowledgeService.deleteKnowledge(id);
        return ApiResponse.success("Deleted", null);
    }

    @PostMapping("/reindex")
    public ApiResponse<Map<String, Object>> reindexAll() {
        return ApiResponse.success("Reindex started", knowledgeService.reindexAll());
    }

    @PostMapping("/{id:\\d+}/sync")
    public ApiResponse<Map<String, Object>> syncKnowledge(@PathVariable Long id) {
        return ApiResponse.success("Sync started", knowledgeService.syncKnowledge(id));
    }

    @GetMapping("/test-retrieval")
    public ApiResponse<List<Map<String, Object>>> testRetrieval(
            @RequestParam String query, @RequestParam(required = false) String merchantCode,
            @RequestParam(defaultValue = "5") Integer topK
    ) {
        return ApiResponse.success("Retrieved", knowledgeService.testRetrieval(query, merchantCode, topK));
    }

    private static long longValue(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long) return ((Number) value).longValue();
        if (value == null) throw new BizException(field + " is required");
        try { return Long.parseLong(String.valueOf(value)); }
        catch (NumberFormatException exception) { throw new BizException(field + " must be an integer"); }
    }

    public record PublishRequest(Long expectedRevision) {
        @JsonCreator
        public PublishRequest(@JsonProperty("expectedRevision") JsonNode value) {
            this(parseRevision(value));
        }

        private static Long parseRevision(JsonNode value) {
            if (value == null || value.isNull()) return null;
            if (value.isIntegralNumber() && value.canConvertToLong()) return value.longValue();
            if (value.isTextual() && value.textValue().matches("-?\\d+")) {
                try { return Long.parseLong(value.textValue()); }
                catch (NumberFormatException ignored) { return null; }
            }
            throw new BizException("expectedRevision must be an integer");
        }
    }
}
