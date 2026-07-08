package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.AgentGatewayDtos;

public interface AgentGatewayService {

    AgentGatewayDtos.HealthResponse health();

    AgentGatewayDtos.ReviewImagesResponse reviewImages(AgentGatewayDtos.ReviewImagesRequest request);

    AgentGatewayDtos.ChatResponse chat(AgentGatewayDtos.ChatRequest request);

    AgentGatewayDtos.EmotionAnalyzeResponse analyzeEmotion(AgentGatewayDtos.EmotionAnalyzeRequest request);
}
