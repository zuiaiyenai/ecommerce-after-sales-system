package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.AgentGatewayDtos;

import java.util.Map;

public interface AgentPolicyCatalogService {

    Map<String, Object> getCatalog();

    Map<String, Object> resolvePolicy(AgentGatewayDtos.PolicyResolveRequest request);

    Map<String, Object> getMerchantPolicy(String merchantCode);

    Map<String, Object> updateMerchantPolicy(String merchantCode, AgentGatewayDtos.PolicyConfigUpdateRequest request);
}
