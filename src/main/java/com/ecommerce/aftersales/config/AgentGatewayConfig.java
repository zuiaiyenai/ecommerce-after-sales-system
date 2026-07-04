package com.ecommerce.aftersales.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;

@Configuration
public class AgentGatewayConfig {

    @Bean
    public RestTemplate agentRestTemplate(RestTemplateBuilder builder, AgentGatewayProperties properties) {
        Duration timeout = Duration.ofMillis(properties.getTimeoutMillis());
        return builder
                .setConnectTimeout(timeout)
                .setReadTimeout(timeout)
                .build();
    }
}
