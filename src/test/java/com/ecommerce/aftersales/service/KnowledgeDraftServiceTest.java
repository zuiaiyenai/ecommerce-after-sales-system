package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.KnowledgeDraftDtos.DraftChunkResponse;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class KnowledgeDraftServiceTest {

    @Test
    void draftChunkResponseKeepsLongIdAsStringAtTheApiBoundary() {
        DraftChunkResponse response = new DraftChunkResponse(
                9007199254740993L, 0, List.of("Refund"), 1, "policy text",
                List.of("headphone"), List.of("quality_issue"), List.of("refund"),
                "RULE", new BigDecimal("0.9500"), "matched policy", false, 1L);

        assertThat(response.chunkId()).isEqualTo(9007199254740993L);
        assertThat(response.reviewRequired()).isFalse();
    }
}
