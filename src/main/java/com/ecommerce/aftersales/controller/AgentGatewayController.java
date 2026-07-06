package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.service.AgentGatewayService;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.ecommerce.aftersales.service.KnowledgeRetrievalService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@RequestMapping("/agent")
public class AgentGatewayController {

    private final AgentGatewayService agentGatewayService;
    private final AgentPolicyCatalogService agentPolicyCatalogService;
    private final KnowledgeRetrievalService knowledgeRetrievalService;

    @GetMapping("/health")
    public ApiResponse<AgentGatewayDtos.HealthResponse> health() {
        return ApiResponse.success(agentGatewayService.health());
    }

    @PostMapping("/review-images")
    public ApiResponse<AgentGatewayDtos.ReviewImagesResponse> reviewImages(
            @Valid @RequestBody AgentGatewayDtos.ReviewImagesRequest request
    ) {
        return ApiResponse.success(agentGatewayService.reviewImages(request));
    }

    @PostMapping("/chat")
    public ApiResponse<AgentGatewayDtos.ChatResponse> chat(
            @Valid @RequestBody AgentGatewayDtos.ChatRequest request
    ) {
        return ApiResponse.success(agentGatewayService.chat(request));
    }

    @GetMapping("/policies/catalog")
    public ApiResponse<java.util.Map<String, Object>> policyCatalog() {
        return ApiResponse.success(agentPolicyCatalogService.getCatalog());
    }

    @PostMapping("/policies/resolve")
    public ApiResponse<java.util.Map<String, Object>> resolvePolicy(
            @RequestBody AgentGatewayDtos.PolicyResolveRequest request
    ) {
        return ApiResponse.success(agentPolicyCatalogService.resolvePolicy(request));
    }

    @PostMapping("/knowledge/retrieve")
    public ApiResponse<AgentGatewayDtos.KnowledgeRetrieveResponse> retrieveKnowledge(
            @Valid @RequestBody AgentGatewayDtos.KnowledgeRetrieveRequest request
    ) {
        return ApiResponse.success(knowledgeRetrievalService.retrieve(request));
    }
}
