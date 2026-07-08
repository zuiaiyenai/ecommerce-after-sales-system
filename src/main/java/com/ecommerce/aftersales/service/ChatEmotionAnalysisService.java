package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;

import java.util.List;

public interface ChatEmotionAnalysisService {

    void analyzeAndPersist(ChatMessage message, ChatSession session);

    void backfillMissingEmotions(Long sessionId, List<ChatMessage> messages);
}
