package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/internal/agent-metrics")
public class InternalAgentMetricsController {
    private final AgentGatewayMetrics metrics;

    @GetMapping
    public ApiResponse<Map<String, Object>> snapshot() {
        return ApiResponse.success(metrics.snapshot());
    }
}
