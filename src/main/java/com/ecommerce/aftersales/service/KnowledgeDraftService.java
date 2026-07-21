package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.enums.ErrorCode;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.DraftChunkResponse;
import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.IngestionStatusResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Array;
import java.util.Arrays;
import java.util.List;

@Service
@RequiredArgsConstructor
public class KnowledgeDraftService {
    @Qualifier("pgJdbcTemplate") private final JdbcTemplate pgJdbcTemplate;
    public IngestionStatusResponse ingestionStatus(Long documentId) {
        List<IngestionStatusResponse> rows = pgJdbcTemplate.query("SELECT id, review_status, metadata ->> 'errorCode' error_code, metadata ->> 'errorMessage' error_message, revision, published_revision FROM knowledge_document WHERE id = ?", (rs, rowNum) -> new IngestionStatusResponse(rs.getLong("id"), rs.getString("review_status"), rs.getString("error_code"), rs.getString("error_message"), rs.getLong("revision"), (Long) rs.getObject("published_revision")), documentId);
        if (rows.isEmpty()) throw new BizException(ErrorCode.NOT_FOUND, "Knowledge document not found");
        return rows.getFirst();
    }
    public List<DraftChunkResponse> draft(Long documentId) {
        return pgJdbcTemplate.query("SELECT id, chunk_index, heading_path, page_number, chunk_text, product_categories, scenes, intents, classification_source, classification_confidence, classification_reason, review_required, revision FROM knowledge_chunk_draft WHERE document_id = ? ORDER BY chunk_index", (rs, rowNum) -> new DraftChunkResponse(rs.getLong("id"), rs.getInt("chunk_index"), strings(rs.getArray("heading_path")), (Integer) rs.getObject("page_number"), rs.getString("chunk_text"), strings(rs.getArray("product_categories")), strings(rs.getArray("scenes")), strings(rs.getArray("intents")), rs.getString("classification_source"), rs.getBigDecimal("classification_confidence"), rs.getString("classification_reason"), rs.getBoolean("review_required"), rs.getLong("revision")), documentId);
    }
    private static List<String> strings(Array array) throws java.sql.SQLException { return array == null ? null : Arrays.stream((Object[]) array.getArray()).map(String::valueOf).toList(); }
}
