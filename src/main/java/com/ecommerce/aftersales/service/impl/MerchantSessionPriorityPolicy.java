package com.ecommerce.aftersales.service.impl;

import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

final class MerchantSessionPriorityPolicy {

    static final String REPLY_STATUS_REPLIED = "REPLIED";
    static final String REPLY_STATUS_UNREPLIED = "UNREPLIED";
    static final String TREND_UP = "UP";
    static final String TREND_DOWN = "DOWN";
    static final String TREND_FLAT = "FLAT";
    static final String RISK_HIGH = "HIGH";
    static final String RISK_MEDIUM = "MEDIUM";
    static final String RISK_LOW = "LOW";

    private MerchantSessionPriorityPolicy() {
    }

    static String normalizeSender(String role) {
        String normalized = String.valueOf(role == null ? "" : role).trim().toUpperCase(Locale.ROOT);
        if ("USER".equals(normalized)) {
            return "USER";
        }
        if (List.of("SERVICE", "ASSISTANT", "SYSTEM").contains(normalized)) {
            return normalized;
        }
        return StringUtils.hasText(normalized) ? normalized : "SYSTEM";
    }

    static String replyStatus(String lastMessageSender) {
        String normalized = String.valueOf(lastMessageSender == null ? "" : lastMessageSender).trim().toUpperCase(Locale.ROOT);
        return "SERVICE".equals(normalized) ? REPLY_STATUS_REPLIED : REPLY_STATUS_UNREPLIED;
    }

    static int emotionScore100(BigDecimal rawScore) {
        if (rawScore == null) {
            return 0;
        }
        BigDecimal normalized = rawScore.compareTo(BigDecimal.ONE) <= 0
                ? rawScore.multiply(BigDecimal.valueOf(100))
                : rawScore;
        return Math.max(0, Math.min(100, normalized.setScale(0, java.math.RoundingMode.HALF_UP).intValue()));
    }

    static int priorityScore(String replyStatus, BigDecimal emotionScore, LocalDateTime lastMessageTime, LocalDateTime now) {
        int replyWeight = REPLY_STATUS_UNREPLIED.equals(replyStatus) ? 100 : 0;
        int emotionWeight = emotionScore100(emotionScore) * 2;
        long waitMinutes = 0;
        if (REPLY_STATUS_UNREPLIED.equals(replyStatus)
                && lastMessageTime != null && now != null && lastMessageTime.isBefore(now)) {
            waitMinutes = Math.min(Duration.between(lastMessageTime, now).toMinutes(), 120);
        }
        return replyWeight + emotionWeight + (int) waitMinutes;
    }

    static String riskLevel(BigDecimal emotionScore) {
        int score = emotionScore100(emotionScore);
        if (score >= 80) {
            return RISK_HIGH;
        }
        if (score >= 50) {
            return RISK_MEDIUM;
        }
        return RISK_LOW;
    }

    static String emotionTrend(List<BigDecimal> scores) {
        if (scores == null || scores.size() < 2) {
            return TREND_FLAT;
        }
        int first = emotionScore100(scores.get(0));
        int last = emotionScore100(scores.get(scores.size() - 1));
        if (last - first >= 20) {
            return TREND_UP;
        }
        if (first - last >= 20) {
            return TREND_DOWN;
        }
        return TREND_FLAT;
    }

    static Comparator<com.ecommerce.aftersales.dto.MerchantCsDtos.SessionView> sessionComparator() {
        return Comparator
                .comparing(
                        com.ecommerce.aftersales.dto.MerchantCsDtos.SessionView::getPriorityScore,
                        Comparator.nullsLast(Comparator.reverseOrder())
                )
                .thenComparing(
                        com.ecommerce.aftersales.dto.MerchantCsDtos.SessionView::getLastMessageTime,
                        Comparator.nullsLast(Comparator.reverseOrder())
                )
                .thenComparing(
                        com.ecommerce.aftersales.dto.MerchantCsDtos.SessionView::getSessionId,
                        Comparator.nullsLast(Comparator.reverseOrder())
                );
    }
}
