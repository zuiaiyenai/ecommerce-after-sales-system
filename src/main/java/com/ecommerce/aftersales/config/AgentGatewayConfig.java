package com.ecommerce.aftersales.config;

import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.web.client.RestTemplate;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.net.http.HttpClient;

@Configuration
public class AgentGatewayConfig {

    @Bean
    public HttpClient agentHttpClient(AgentGatewayProperties properties) {
        return HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(properties.getTimeoutMillis()))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    @Bean
    public RestTemplate agentRestTemplate(RestTemplateBuilder builder, AgentGatewayProperties properties) {
        Duration timeout = Duration.ofMillis(properties.getTimeoutMillis());
        return builder
                .setConnectTimeout(timeout)
                .setReadTimeout(timeout)
                .additionalMessageConverters(new StringHttpMessageConverter(StandardCharsets.UTF_8))
                .build();
    }
}
