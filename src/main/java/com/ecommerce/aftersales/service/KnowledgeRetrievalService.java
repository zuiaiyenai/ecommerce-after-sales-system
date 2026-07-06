package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.AgentGatewayDtos;

public interface KnowledgeRetrievalService {

    AgentGatewayDtos.KnowledgeRetrieveResponse retrieve(AgentGatewayDtos.KnowledgeRetrieveRequest request);
}
