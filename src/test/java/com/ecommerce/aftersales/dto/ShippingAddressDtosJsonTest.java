package com.ecommerce.aftersales.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ShippingAddressDtosJsonTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void keepsIsDefaultAsThePublicJsonContract() throws Exception {
        ShippingAddressDtos.UpsertRequest request = objectMapper.readValue("""
                {"name":"张三","phone":"13800138001","province":"北京市","city":"北京市",
                 "district":"朝阳区","detail":"三里屯路19号院","isDefault":true}
                """, ShippingAddressDtos.UpsertRequest.class);
        ShippingAddressDtos.Response response = ShippingAddressDtos.Response.builder()
                .id(1234567890123456789L)
                .isDefault(request.isDefault())
                .build();

        String json = objectMapper.writeValueAsString(response);

        assertThat(request.isDefault()).isTrue();
        assertThat(json).contains("\"id\":\"1234567890123456789\"");
        assertThat(json).contains("\"isDefault\":true");
        assertThat(json).doesNotContain("\"default\"");
    }
}
