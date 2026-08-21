package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class AiReviewStatusCacheServiceImpl implements AiReviewStatusCacheService {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    @Value("${app.after-sales.review-status-cache.ttl-seconds:1800}")
    private long ttlSeconds;

    @Override
    public void cacheStatus(Long ticketId, String status) {
        if (ticketId == null || !StringUtils.hasText(status)) {
            return;
        }
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("ticket_id", String.valueOf(ticketId));
            payload.put("status", status);
            payload.put("updated_at", LocalDateTime.now().toString());
            redisTemplate.opsForValue().set(key(ticketId), objectMapper.writeValueAsString(payload), Duration.ofSeconds(Math.max(60, ttlSeconds)));
        } catch (Exception exception) {
            log.warn("Failed to cache AI review status ticketId={}", ticketId, exception);
        }
    }

    @Override
    public Optional<String> getStatus(Long ticketId) {
        if (ticketId == null) {
            return Optional.empty();
        }
        try {
            String raw = redisTemplate.opsForValue().get(key(ticketId));
            if (!StringUtils.hasText(raw)) {
                return Optional.empty();
            }
            Map<?, ?> payload = objectMapper.readValue(raw, Map.class);
            Object status = payload.get("status");
            return status == null || !StringUtils.hasText(String.valueOf(status))
                    ? Optional.empty()
                    : Optional.of(String.valueOf(status));
        } catch (JsonProcessingException exception) {
            log.warn("Invalid AI review status cache ticketId={}", ticketId, exception);
            return Optional.empty();
        } catch (Exception exception) {
            log.warn("Failed to read AI review status cache ticketId={}", ticketId, exception);
            return Optional.empty();
        }
    }

    @Override
    public String resolveStatus(AfterSalesTicket ticket) {
        if (ticket == null) {
            return "PENDING";
        }
        return getStatus(ticket.getId()).orElseGet(() -> fallbackStatus(ticket));
    }

    private String fallbackStatus(AfterSalesTicket ticket) {
        if (StringUtils.hasText(ticket.getAiReviewStatus())) {
            return switch (ticket.getAiReviewStatus().trim().toUpperCase()) {
                case "RUNNING", "RESUME_PENDING" -> "AI_REVIEWING";
                case "WAITING_EVIDENCE" -> "WAITING_EVIDENCE";
                case "MANUAL_REQUIRED" -> "MANUAL_REQUIRED";
                case "COMPLETED" -> "PROCESSING";
                default -> ticket.getAiReviewStatus();
            };
        }
        String verdict = Optional.ofNullable(ticket.getAiReviewResult()).orElse("").trim().toUpperCase();
        if ("MANUAL_REVIEW_REQUIRED".equals(verdict) || "MANUAL_REVIEW".equals(verdict)) {
            return "MANUAL_REQUIRED";
        }
        if ("APPROVE".equals(verdict) || "PROCESSING".equalsIgnoreCase(ticket.getStatus())) {
            return "PROCESSING";
        }
        if ("PENDING_REVIEW".equalsIgnoreCase(ticket.getStatus())) {
            return "AI_REVIEWING";
        }
        return "PENDING";
    }

    private String key(Long ticketId) {
        return "review:status:" + ticketId;
    }
}
