package com.ecommerce.aftersales.request;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.List;

@Data
public class SupplementAfterSalesRequest {

    @NotBlank
    @Size(max = 64)
    private String requestId;

    @NotNull
    private Long sessionId;

    @Size(max = 1000)
    private String message;

    @Size(max = 9)
    private List<@Size(max = 255) String> attachmentUrls;
}
