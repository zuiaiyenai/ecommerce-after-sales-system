package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.config.AgentGatewayProperties;
import com.ecommerce.aftersales.config.TraceContext;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.MessageNotice;
import com.ecommerce.aftersales.entity.TicketLog;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.MessageNoticeMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AgentGatewayService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.ecommerce.aftersales.service.AgentConversationContextService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
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
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.Resource;
import org.springframework.http.MediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.concurrent.Executor;

@Slf4j
@Service
@RequiredArgsConstructor
public class AgentGatewayServiceImpl implements AgentGatewayService {

    private final RestTemplate agentRestTemplate;
    private final AgentGatewayProperties properties;
    private final ObjectMapper objectMapper;
    private final HttpClient agentHttpClient;
    private final AgentGatewayMetrics metrics;
    private final AgentConversationContextService conversationContextService;
    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final MessageNoticeMapper messageNoticeMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final TicketLogMapper ticketLogMapper;
    private Semaphore agentRequestPermits;
    private List<String> agentBaseUrls;
    private final AtomicInteger endpointCursor = new AtomicInteger();
    @Resource(name = "agentSseExecutor")
    private Executor agentSseExecutor;

    @PostConstruct
    void initializeConcurrencyGuard() {
        agentBaseUrls = Stream.concat(properties.getBaseUrls().stream(), Stream.of(properties.getBaseUrl()))
                .filter(url -> url != null && !url.isBlank())
                .map(String::trim)
                .distinct()
                .toList();
        if (agentBaseUrls.isEmpty()) {
            throw new IllegalStateException("At least one Agent base URL must be configured");
        }
        int configuredCapacity = properties.getMaxConcurrentRequests();
        int derivedCapacity = agentBaseUrls.size() * Math.max(1, properties.getPerInstanceMaxConcurrentRequests());
        int gatewayCapacity = configuredCapacity > 0 ? configuredCapacity : derivedCapacity;
        agentRequestPermits = new Semaphore(gatewayCapacity, true);
        log.info("Agent gateway initialized replicas={}, gatewayCapacity={}", agentBaseUrls, gatewayCapacity);
    }

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
        conversationContextService.hydrateTrustedContext(request);
        conversationContextService.persistCurrentUserMessage(request);
        try {
            AgentGatewayDtos.ChatResponse response = exchange("/chat", HttpMethod.POST, request, AgentGatewayDtos.ChatResponse.class);
            metrics.recordChat(response.getNeed_human(), extractKnowledgeHitCount(response));
            return response;
        } catch (BizException exception) {
            if (!shouldFallbackChat(exception)) {
                throw exception;
            }
            log.warn("Agent chat fallback triggered code={} message={}", exception.getCode(), exception.getMessage());
            AgentGatewayDtos.ChatResponse response = buildChatFallback(request, exception);
            metrics.recordChat(true, null);
            return response;
        }
    }

    @Override
    public SseEmitter streamChat(AgentGatewayDtos.ChatRequest request) {
        conversationContextService.hydrateTrustedContext(request);
        conversationContextService.persistCurrentUserMessage(request);
        SseEmitter emitter = new SseEmitter((long) properties.getTimeoutMillis());
        agentSseExecutor.execute(() -> forwardAgentStream(request, emitter));
        return emitter;
    }

    private void forwardAgentStream(AgentGatewayDtos.ChatRequest body, SseEmitter emitter) {
        String url = buildUrl("/chat/stream");
        try {
            HttpRequest request = withAgentAuth(HttpRequest.newBuilder(URI.create(url)))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .header("Accept", MediaType.TEXT_EVENT_STREAM_VALUE)
                    .timeout(Duration.ofMillis(properties.getTimeoutMillis()))
                    .POST(HttpRequest.BodyPublishers.ofString(toJson(body), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<java.io.InputStream> response = agentHttpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                response.body().close();
                throw new IOException("Agent stream returned HTTP " + response.statusCode());
            }
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(response.body(), StandardCharsets.UTF_8))) {
                String eventName = "message";
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.startsWith("event:")) {
                        eventName = line.substring(6).trim();
                    } else if (line.startsWith("data:")) {
                        String data = line.substring(5).trim();
                        emitter.send(SseEmitter.event().name(eventName).data(data, MediaType.APPLICATION_JSON));
                    }
                }
            }
            emitter.complete();
        } catch (Exception exception) {
            log.info("Agent SSE stream ended url={} reason={}", url, exception.getClass().getSimpleName());
            emitter.completeWithError(exception);
        }
    }

    @Override
    public AgentGatewayDtos.EmotionAnalyzeResponse analyzeEmotion(AgentGatewayDtos.EmotionAnalyzeRequest request) {
        return exchange("/analyze/emotion", HttpMethod.POST, request, AgentGatewayDtos.EmotionAnalyzeResponse.class);
    }

    private <T> T exchange(String path, HttpMethod method, Object body, Class<T> responseType) {
        String url = buildUrl(path);
        boolean permitAcquired = false;
        String outcome = "failure";
        long startedAt = System.nanoTime();
        try {
            permitAcquired = agentRequestPermits.tryAcquire(
                    Math.max(0, properties.getQueueWaitMillis()), TimeUnit.MILLISECONDS);
            if (!permitAcquired) {
                outcome = "rejected";
                throw new BizException(429, "Agent 服务繁忙，请稍后重试");
            }
            if (body != null && method != HttpMethod.GET) {
                T response = postJson(url, body, responseType);
                outcome = "success";
                return response;
            }
            T response = getJson(url, responseType);
            outcome = "success";
            return response;
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
        } finally {
            metrics.record(outcome, System.nanoTime() - startedAt);
            if (permitAcquired) {
                agentRequestPermits.release();
            }
        }
    }

    @SuppressWarnings("unchecked")
    private Integer extractKnowledgeHitCount(AgentGatewayDtos.ChatResponse response) {
        if (response.getRaw() == null) {
            return null;
        }
        Object retrieval = response.getRaw().get("retrieved_knowledge");
        if (!(retrieval instanceof Map<?, ?> payload)) {
            return null;
        }
        Object count = payload.get("total_hits");
        if (count instanceof Number number) {
            return number.intValue();
        }
        try {
            return count == null ? null : Integer.valueOf(String.valueOf(count));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private <T> T getJson(String url, Class<T> responseType) {
        HttpHeaders headers = new HttpHeaders();
        if (properties.getInternalToken() != null && !properties.getInternalToken().isBlank()) {
            headers.set("X-Agent-Internal-Token", properties.getInternalToken());
        }
        TraceContext.putHeader(headers);
        ResponseEntity<T> response = agentRestTemplate.exchange(
                url,
                HttpMethod.GET,
                new HttpEntity<>(headers),
                responseType
        );
        T payload = response.getBody();
        if (payload == null) {
            throw new BizException(502, "Agent 服务返回了空响应");
        }
        return payload;
    }

    private <T> T postJson(String url, Object body, Class<T> responseType) throws IOException, InterruptedException {
        String requestBody = toJson(body);
        HttpRequest request = withAgentAuth(HttpRequest.newBuilder(URI.create(url)))
                .header("Content-Type", "application/json; charset=utf-8")
                .header("Accept", "application/json; charset=utf-8")
                .timeout(Duration.ofMillis(properties.getTimeoutMillis()))
                .POST(HttpRequest.BodyPublishers.ofString(requestBody, StandardCharsets.UTF_8))
                .build();
        HttpResponse<String> response = agentHttpClient.send(
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

    private HttpRequest.Builder withAgentAuth(HttpRequest.Builder builder) {
        String token = properties.getInternalToken();
        if (token != null && !token.isBlank()) {
            builder.header("X-Agent-Internal-Token", token);
        }
        String traceId = TraceContext.currentTraceId();
        if (traceId != null) {
            builder.header(TraceContext.HEADER, traceId);
        }
        return builder;
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

    private boolean shouldFallbackChat(BizException exception) {
        Integer code = exception.getCode();
        return code != null && List.of(429, 502, 503, 504).contains(code);
    }

    private AgentGatewayDtos.ChatResponse buildChatFallback(AgentGatewayDtos.ChatRequest request, BizException exception) {
        String reply = "已收到您的售后问题和凭证。当前智能审核服务响应超时，我已先为您转入人工优先处理队列，客服会继续核对订单、图片凭证和商家政策；在人工确认前，系统不会自动通过、拒绝或退款。";
        ChatFallbackPersistence fallbackPersistence = markSessionWaitingForHuman(request, reply, exception);

        AgentGatewayDtos.ChatResponse response = new AgentGatewayDtos.ChatResponse();
        response.setAssistant_reply(reply);
        response.setIntent("agent_timeout_fallback");
        response.setSuggested_action("handoff_to_human");
        response.setEvidence_needed(List.of());
        response.setNeed_human(true);
        response.setSession_mode("HUMAN");
        response.setFallback_decision("AGENT_TIMEOUT_HANDOFF");
        response.setFallback_progress_hint("agent_timeout_handoff_to_human");
        response.setFallback_need_human(true);
        response.setRaw(Map.of(
                "fallback", true,
                "fallback_reason", "agent_timeout_or_unavailable",
                "agent_error_code", exception.getCode(),
                "agent_error_message", String.valueOf(exception.getMessage()),
                "auto_review_stopped", true,
                "auto_refund_stopped", true,
                "existing_pending_ticket", fallbackPersistence.ticket() != null
        ));
        response.setTrace(Map.of(
                "request_type", "chat",
                "fallback", true,
                "fallback_reason", exception.getClass().getSimpleName()
        ));
        if (fallbackPersistence.ticket() != null) {
            response.setTicket(toFallbackTicketDto(fallbackPersistence.ticket()));
        }
        if (fallbackPersistence.session() != null) {
            AgentGatewayDtos.PersistenceDto persistence = new AgentGatewayDtos.PersistenceDto();
            persistence.setSession_id(fallbackPersistence.session().getId());
            persistence.setSession_no(fallbackPersistence.session().getSessionNo());
            persistence.setTicket_log_id(fallbackPersistence.ticketLogId());
            persistence.setNotice_id(fallbackPersistence.noticeId());
            response.setPersistence(persistence);
        }
        return response;
    }

    private ChatFallbackPersistence markSessionWaitingForHuman(
            AgentGatewayDtos.ChatRequest request,
            String assistantReply,
            BizException exception
    ) {
        if (request == null || request.getSession_id() == null) {
            return ChatFallbackPersistence.empty();
        }
        ChatSession session = chatSessionMapper.selectById(request.getSession_id());
        if (session == null) {
            return ChatFallbackPersistence.empty();
        }
        AfterSalesTicket ticket = resolveExistingOpenTicket(session, request);
        Long ticketLogId = markTicketManualReview(ticket, exception);
        if (ticket != null && session.getTicketId() == null) {
            session.setTicketId(ticket.getId());
        }
        session.setMode("HUMAN");
        session.setStatus("WAITING");
        session.setResolved(0);
        session.setUserQuery(shortText(firstNonBlank(request.getMessage(), "Agent 服务超时，等待人工处理"), 500));
        session.setUpdateTime(LocalDateTime.now());
        chatSessionMapper.updateById(session);

        appendAssistantFallbackMessage(session.getId(), assistantReply);
        Long noticeId = createAgentFallbackNotice(session, ticket, request, exception);
        return new ChatFallbackPersistence(session, ticket, ticketLogId, noticeId);
    }

    private AfterSalesTicket resolveExistingOpenTicket(ChatSession session, AgentGatewayDtos.ChatRequest request) {
        if (session.getTicketId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(session.getTicketId());
            if (ticket != null) {
                return ticket;
            }
        }
        Long orderId = parseLong(firstNonBlank(
                request == null ? null : request.getOrder_id(),
                session.getOrderId() == null ? null : String.valueOf(session.getOrderId())
        ));
        Long userId = parseLong(firstNonBlank(
                request == null ? null : request.getUser_id(),
                session.getUserId() == null ? null : String.valueOf(session.getUserId())
        ));
        if (orderId == null) {
            return null;
        }
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getOrderId, orderId)
                .in(AfterSalesTicket::getStatus, List.of("PENDING", "PENDING_REVIEW", "PROCESSING"))
                .orderByDesc(AfterSalesTicket::getCreateTime)
                .last("LIMIT 1");
        if (userId != null) {
            wrapper.eq(AfterSalesTicket::getUserId, userId);
        }
        return afterSalesTicketMapper.selectOne(wrapper);
    }

    private Long markTicketManualReview(AfterSalesTicket ticket, BizException exception) {
        if (ticket == null) {
            return null;
        }
        String previousStatus = ticket.getStatus();
        ticket.setPriority(1);
        ticket.setAuditOpinion(shortText(
                "智能审核服务超时或不可用，已停止自动审核/自动退款，保留当前售后单并转人工复核。原因："
                        + exception.getMessage(),
                500
        ));
        ticket.setUpdateTime(LocalDateTime.now());
        afterSalesTicketMapper.updateById(ticket);

        TicketLog log = new TicketLog();
        log.setTicketId(ticket.getId());
        log.setOperatorType("SYSTEM");
        log.setFromStatus(previousStatus);
        log.setToStatus(previousStatus);
        log.setAction("AGENT_TIMEOUT_HANDOFF");
        log.setContent("智能审核服务超时或不可用，已停止自动审核/自动退款，保留当前售后单并转人工复核。");
        ticketLogMapper.insert(log);
        return log.getId();
    }

    private AgentGatewayDtos.TicketDto toFallbackTicketDto(AfterSalesTicket ticket) {
        AgentGatewayDtos.TicketDto dto = new AgentGatewayDtos.TicketDto();
        dto.setTicket_id(String.valueOf(ticket.getId()));
        dto.setStatus(toExternalTicketStatus(ticket.getStatus()));
        dto.setExpected_hours(24);
        return dto;
    }

    private String toExternalTicketStatus(String status) {
        if ("PENDING".equals(status)) {
            return "PENDING_REVIEW";
        }
        return status;
    }

    private void appendAssistantFallbackMessage(Long sessionId, String content) {
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole("ASSISTANT");
        message.setContent(content);
        message.setMessageType("TEXT");
        chatMessageMapper.insert(message);
    }

    private Long createAgentFallbackNotice(
            ChatSession session,
            AfterSalesTicket ticket,
            AgentGatewayDtos.ChatRequest request,
            BizException exception
    ) {
        if (session.getMerchantId() == null) {
            return null;
        }
        MessageNotice notice = new MessageNotice();
        notice.setUserId(session.getMerchantId());
        notice.setTitle("Agent 超时转人工");
        notice.setContent(shortText(
                "用户售后请求已转人工。问题：" + firstNonBlank(request.getMessage(), session.getUserQuery())
                        + "；原因：" + exception.getMessage(),
                500
        ));
        notice.setNoticeType("CHAT");
        notice.setRefType(ticket == null ? "CHAT_SESSION" : "AFTER_SALES_TICKET");
        notice.setRefId(ticket == null ? session.getId() : ticket.getId());
        notice.setIsRead(0);
        messageNoticeMapper.insert(notice);
        return notice.getId();
    }

    private Long parseLong(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Long.valueOf(value.trim());
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    private String shortText(String value, int limit) {
        if (value == null) {
            return "";
        }
        return value.length() <= limit ? value : value.substring(0, limit);
    }

    private String toJson(Object body) {
        try {
            return objectMapper.writeValueAsString(body);
        } catch (JsonProcessingException exception) {
            throw new BizException(500, "Agent 请求序列化失败");
        }
    }

    private String buildUrl(String path) {
        int index = Math.floorMod(endpointCursor.getAndIncrement(), agentBaseUrls.size());
        String baseUrl = agentBaseUrls.get(index);
        if (baseUrl.endsWith("/")) {
            baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
        }
        return baseUrl + path;
    }

    private record ChatFallbackPersistence(
            ChatSession session,
            AfterSalesTicket ticket,
            Long ticketLogId,
            Long noticeId
    ) {
        static ChatFallbackPersistence empty() {
            return new ChatFallbackPersistence(null, null, null, null);
        }
    }
}
