package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.config.AgentGatewayProperties;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.service.KnowledgeRetrievalService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeRetrievalServiceImpl implements KnowledgeRetrievalService {

    private final RestTemplate agentRestTemplate;
    private final AgentGatewayProperties properties;

    @Override
    public AgentGatewayDtos.KnowledgeRetrieveResponse retrieve(AgentGatewayDtos.KnowledgeRetrieveRequest request) {
        String url = buildUrl("/knowledge/retrieve");
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(java.util.List.of(MediaType.APPLICATION_JSON));
        try {
            AgentGatewayDtos.KnowledgeRetrieveResponse response = agentRestTemplate.postForObject(
                    url,
                    new HttpEntity<>(request, headers),
                    AgentGatewayDtos.KnowledgeRetrieveResponse.class
            );
            if (response == null) {
                throw new BizException(502, "Agent knowledge service returned empty response");
            }
            return response;
        } catch (ResourceAccessException exception) {
            log.warn("Agent knowledge service unavailable: {}", url, exception);
            throw new BizException(502, "Agent knowledge service is unavailable");
        } catch (RestClientException exception) {
            log.error("Failed to call Agent knowledge service: {}", url, exception);
            throw new BizException(502, "Failed to call Agent knowledge service: " + exception.getMessage());
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
