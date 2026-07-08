package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.config.AgentGatewayProperties;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.service.AgentGatewayService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class AgentGatewayServiceImpl implements AgentGatewayService {

    private final RestTemplate agentRestTemplate;
    private final AgentGatewayProperties properties;
    private final ObjectMapper objectMapper;

    @Override
    public AgentGatewayDtos.HealthResponse health() {
        return exchange("/health", HttpMethod.GET, null, AgentGatewayDtos.HealthResponse.class);
    }

    @Override
    public AgentGatewayDtos.ReviewImagesResponse reviewImages(AgentGatewayDtos.ReviewImagesRequest request) {
        String url = buildUrl("/review-images");
        try {
            return postJson(url, request, AgentGatewayDtos.ReviewImagesResponse.class);
        } catch (IOException exception) {
            log.warn("Image review fallback triggered for {}", url, exception);
            return buildImageReviewFallback(exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            log.warn("Image review interrupted, fallback triggered for {}", url, exception);
            return buildImageReviewFallback(exception);
        }
    }

    @Override
    public AgentGatewayDtos.ChatResponse chat(AgentGatewayDtos.ChatRequest request) {
        return exchange("/chat", HttpMethod.POST, request, AgentGatewayDtos.ChatResponse.class);
    }

    @Override
    public AgentGatewayDtos.EmotionAnalyzeResponse analyzeEmotion(AgentGatewayDtos.EmotionAnalyzeRequest request) {
        return exchange("/analyze/emotion", HttpMethod.POST, request, AgentGatewayDtos.EmotionAnalyzeResponse.class);
    }

    private <T> T exchange(String path, HttpMethod method, Object body, Class<T> responseType) {
        String url = buildUrl(path);
        try {
            if (body != null && method != HttpMethod.GET) {
                return postJson(url, body, responseType);
            }
            return getJson(url, responseType);
        } catch (ResourceAccessException exception) {
            log.warn("Agent service unavailable: {}", url, exception);
            throw new BizException(502, "Agent 服务暂时不可用，请稍后重试");
        } catch (RestClientException exception) {
            log.error("Failed to call Agent service: {}", url, exception);
            throw new BizException(502, "调用 Agent 服务失败: " + exception.getMessage());
        } catch (IOException exception) {
            log.error("IO error while calling Agent service: {}", url, exception);
            throw new BizException(502, "Agent 服务响应异常，请稍后重试");
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            log.error("Interrupted while calling Agent service: {}", url, exception);
            throw new BizException(502, "Agent 服务处理被中断，请稍后重试");
        }
    }

    private <T> T getJson(String url, Class<T> responseType) {
        T payload = agentRestTemplate.getForObject(url, responseType);
        if (payload == null) {
            throw new BizException(502, "Agent 服务返回了空响应");
        }
        return payload;
    }

    private <T> T postJson(String url, Object body, Class<T> responseType) throws IOException, InterruptedException {
        String requestBody = toJson(body);
        HttpClient httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(properties.getTimeoutMillis()))
                .build();
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .header("Content-Type", "application/json; charset=utf-8")
                .header("Accept", "application/json; charset=utf-8")
                .timeout(Duration.ofMillis(properties.getTimeoutMillis()))
                .POST(HttpRequest.BodyPublishers.ofString(requestBody, StandardCharsets.UTF_8))
                .build();
        HttpResponse<String> response = httpClient.send(
                request,
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8)
        );
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            log.error("Agent service returned HTTP {} from {}: {}", response.statusCode(), url, response.body());
            throw new BizException(502, "Agent 服务调用失败，HTTP 状态码: " + response.statusCode());
        }
        T payload = objectMapper.readValue(response.body(), responseType);
        if (payload == null) {
            throw new BizException(502, "Agent 服务返回了空响应");
        }
        return payload;
    }

    private AgentGatewayDtos.ReviewImagesResponse buildImageReviewFallback(Exception exception) {
        AgentGatewayDtos.ImageReviewDto review = new AgentGatewayDtos.ImageReviewDto();
        review.setSuccess(false);
        review.setAll_clear(false);
        review.setHas_damage_area(false);
        review.setHas_outer_package(false);
        review.setHas_logistics_label(false);
        review.setLogistics_matches_order(false);
        review.setCourier_company("");
        review.setTracking_number("");
        review.setSender_name("");
        review.setReceiver_name("");
        review.setMissing_visual_evidence(List.of("图片分析结果待补充"));
        review.setSummary("图片分析暂时异常，我会先根据您的描述继续处理，稍后补充图片分析结果。");
        review.setItems(List.of());
        review.setRaw(Map.of(
                "mode", "gateway_fallback",
                "error", exception.getClass().getSimpleName(),
                "message", String.valueOf(exception.getMessage())
        ));

        AgentGatewayDtos.ReviewImagesResponse response = new AgentGatewayDtos.ReviewImagesResponse();
        response.setImage_review(review);
        response.setTrace(Map.of(
                "request_type", "review_images",
                "fallback", true
        ));
        return response;
    }

    private String toJson(Object body) {
        try {
            return objectMapper.writeValueAsString(body);
        } catch (JsonProcessingException exception) {
            throw new BizException(500, "Agent 请求序列化失败");
        }
    }

    private String buildUrl(String path) {
        String baseUrl = properties.getBaseUrl();
        if (baseUrl.endsWith("/")) {
            baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
        }
        return baseUrl + path;
    }
}
