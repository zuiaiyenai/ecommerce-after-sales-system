package com.ecommerce.aftersales.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
class AiReviewStatusCacheRedisTest {
    @Container static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379);
    static LettuceConnectionFactory connectionFactory;
    static AiReviewStatusCacheServiceImpl cache;

    @BeforeAll static void setup() {
        connectionFactory = new LettuceConnectionFactory(REDIS.getHost(), REDIS.getMappedPort(6379));
        connectionFactory.afterPropertiesSet();
        StringRedisTemplate template = new StringRedisTemplate(connectionFactory);
        template.afterPropertiesSet();
        cache = new AiReviewStatusCacheServiceImpl(template, new ObjectMapper());
        ReflectionTestUtils.setField(cache, "ttlSeconds", 1800L);
    }

    @AfterAll static void close() { if (connectionFactory != null) connectionFactory.destroy(); }

    @Test void storesOnlyAnExplicitlyConfirmedStatusAndReadsItBack() {
        assertThat(cache.getStatus(100L)).isEmpty();
        cache.cacheStatus(100L, "MANUAL_REQUIRED");
        assertThat(cache.getStatus(100L)).contains("MANUAL_REQUIRED");
    }
}
