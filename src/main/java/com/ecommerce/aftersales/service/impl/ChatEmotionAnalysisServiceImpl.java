package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.service.AgentGatewayService;
import com.ecommerce.aftersales.service.ChatEmotionAnalysisService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class ChatEmotionAnalysisServiceImpl implements ChatEmotionAnalysisService {

    private final AgentGatewayService agentGatewayService;
    private final ChatMessageMapper chatMessageMapper;
    private final ChatSessionMapper chatSessionMapper;

    @Override
    public void analyzeAndPersist(ChatMessage message, ChatSession session) {
        if (message == null || session == null) {
            return;
        }
        if (!"USER".equalsIgnoreCase(message.getRole())) {
            return;
        }
        if (!StringUtils.hasText(message.getContent())) {
            return;
        }
        if ("IMAGE".equalsIgnoreCase(message.getMessageType())) {
            return;
        }
        if (StringUtils.hasText(message.getEmotionLabel())) {
            return;
        }

        AgentGatewayDtos.EmotionAnalyzeResponse response = analyze(message.getContent(), session.getId());
        if (response == null || !StringUtils.hasText(response.getEmotion_label())) {
            return;
        }

        message.setEmotionLabel(normalizeEmotionLabel(response.getEmotion_label()));
        message.setEmotionScore(toDecimal(response.getEmotion_score()));
        message.setEmotionConfidence(toDecimal(response.getEmotion_confidence()));
        chatMessageMapper.updateById(message);

        session.setEmotionLabel(message.getEmotionLabel());
        session.setEmotionScore(message.getEmotionScore());
        session.setEmotionConfidence(message.getEmotionConfidence());
        chatSessionMapper.updateById(session);
    }

    @Override
    public void backfillMissingEmotions(Long sessionId, List<ChatMessage> messages) {
        if (sessionId == null || messages == null || messages.isEmpty()) {
            return;
        }
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null) {
            return;
        }
        int processed = 0;
        for (ChatMessage message : messages) {
            if (processed >= 12) {
                break;
            }
            if (!"USER".equalsIgnoreCase(message.getRole())) {
                continue;
            }
            if (StringUtils.hasText(message.getEmotionLabel())) {
                continue;
            }
            if (!StringUtils.hasText(message.getContent()) || "IMAGE".equalsIgnoreCase(message.getMessageType())) {
                continue;
            }
            try {
                analyzeAndPersist(message, session);
                processed++;
            } catch (Exception exception) {
                log.warn("Emotion backfill failed for message {} in session {}", message.getId(), sessionId, exception);
            }
        }
    }

    private AgentGatewayDtos.EmotionAnalyzeResponse analyze(String message, Long sessionId) {
        List<ChatMessage> recentMessages = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .orderByDesc(ChatMessage::getCreateTime)
                .last("limit 12"));
        recentMessages = recentMessages.reversed();

        AgentGatewayDtos.EmotionAnalyzeRequest request = new AgentGatewayDtos.EmotionAnalyzeRequest();
        request.setMessage(message);
        request.setSession_id(sessionId);
        request.setRecent_history(recentMessages.stream()
                .map(item -> {
                    AgentGatewayDtos.ConversationMessageDto dto = new AgentGatewayDtos.ConversationMessageDto();
                    dto.setRole("USER".equalsIgnoreCase(item.getRole()) ? "user" : "assistant");
                    dto.setContent(item.getContent());
                    return dto;
                })
                .toList());
        return agentGatewayService.analyzeEmotion(request);
    }

    private String normalizeEmotionLabel(String label) {
        if (!StringUtils.hasText(label)) {
            return "CALM";
        }
        return label.trim().toUpperCase();
    }

    private BigDecimal toDecimal(Double value) {
        if (value == null) {
            return null;
        }
        double normalized = value > 1 ? value / 100.0 : value;
        return BigDecimal.valueOf(normalized).setScale(2, RoundingMode.HALF_UP);
    }
}
