package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.service.AgentGatewayService;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.ecommerce.aftersales.service.KnowledgeRetrievalService;
import com.ecommerce.aftersales.service.RedisRateLimiterService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.http.MediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequiredArgsConstructor
@RequestMapping("/agent")
public class AgentGatewayController {

    private final AgentGatewayService agentGatewayService;
    private final AgentPolicyCatalogService agentPolicyCatalogService;
    private final KnowledgeRetrievalService knowledgeRetrievalService;
    private final RedisRateLimiterService redisRateLimiterService;

    @Value("${app.rate-limit.ai-chat.enabled:true}")
    private boolean aiChatRateLimitEnabled;

    @Value("${app.rate-limit.ai-chat.limit:30}")
    private int aiChatRateLimit;

    @Value("${app.rate-limit.ai-chat.window-seconds:60}")
    private long aiChatRateLimitWindowSeconds;

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
            @CurrentUserId Long userId,
            @Valid @RequestBody AgentGatewayDtos.ChatRequest request
    ) {
        if (request.getUser_id() != null && !String.valueOf(userId).equals(request.getUser_id())) {
            throw new BizException(403, "不可使用其他用户身份发起 Agent 会话");
        }
        request.setUser_id(String.valueOf(userId));
        if (request.getSelected_order() != null) {
            request.getSelected_order().setUser_id(String.valueOf(userId));
        }
        enforceAiChatRateLimit(userId);
        return ApiResponse.success(agentGatewayService.chat(request));
    }

    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamChat(
            @CurrentUserId Long userId,
            @Valid @RequestBody AgentGatewayDtos.ChatRequest request
    ) {
        if (request.getUser_id() != null && !String.valueOf(userId).equals(request.getUser_id())) {
            throw new BizException(403, "不可使用其他用户身份发起 Agent 会话");
        }
        request.setUser_id(String.valueOf(userId));
        if (request.getSelected_order() != null) {
            request.getSelected_order().setUser_id(String.valueOf(userId));
        }
        enforceAiChatRateLimit(userId);
        return agentGatewayService.streamChat(request);
    }

    private void enforceAiChatRateLimit(Long userId) {
        if (aiChatRateLimitEnabled
                && !redisRateLimiterService.tryAcquire("rate:user:" + userId + ":ai_chat", aiChatRateLimit, aiChatRateLimitWindowSeconds)) {
            throw new BizException(429, "AI咨询过于频繁，请稍后再试");
        }
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
