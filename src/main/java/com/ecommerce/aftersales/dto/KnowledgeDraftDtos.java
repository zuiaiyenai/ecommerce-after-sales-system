package com.ecommerce.aftersales.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import org.springframework.web.multipart.MultipartFile;

import java.math.BigDecimal;
import java.util.List;

public final class KnowledgeDraftDtos {
    private KnowledgeDraftDtos() { }
    public record FileImportResponse(@JsonSerialize(using = ToStringSerializer.class) Long documentId, String reviewStatus, boolean duplicate) { }
    public record FileImportCommand(String title, String knowledgeType, String scope, String merchantCode, MultipartFile file) { }
    public record IngestionStatusResponse(@JsonSerialize(using = ToStringSerializer.class) Long documentId, String reviewStatus, String errorCode, String errorMessage, long revision, @JsonSerialize(using = ToStringSerializer.class) Long publishedRevision) { }
    public record DraftChunkResponse(@JsonSerialize(using = ToStringSerializer.class) Long chunkId, int chunkIndex, List<String> headingPath, Integer pageNumber, String text, List<String> productCategories, List<String> scenes, List<String> intents, String classificationSource, BigDecimal confidence, String reason, boolean reviewRequired, long revision) { }
}
