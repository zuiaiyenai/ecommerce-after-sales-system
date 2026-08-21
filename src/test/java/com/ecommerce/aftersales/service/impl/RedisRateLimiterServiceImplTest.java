package com.ecommerce.aftersales.service.impl;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@Testcontainers(disabledWithoutDocker = true)
class RedisRateLimiterServiceImplTest {

    @Container
    static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine").withExposedPorts(6379);

    static LettuceConnectionFactory connectionFactory;
    static StringRedisTemplate redisTemplate;
    static RedisRateLimiterServiceImpl rateLimiter;

    @BeforeAll
    static void setup() {
        connectionFactory = new LettuceConnectionFactory(REDIS.getHost(), REDIS.getMappedPort(6379));
        connectionFactory.afterPropertiesSet();
        redisTemplate = new StringRedisTemplate(connectionFactory);
        redisTemplate.afterPropertiesSet();
        rateLimiter = new RedisRateLimiterServiceImpl(redisTemplate);
    }

    @AfterEach
    void cleanup() {
        redisTemplate.getConnectionFactory().getConnection().serverCommands().flushDb();
    }

    @AfterAll
    static void close() {
        if (connectionFactory != null) {
            connectionFactory.destroy();
        }
    }

    @Test
    void firstRequestIsAllowedAndSetsTtl() {
        String key = "rate:test:first";

        assertThat(rateLimiter.tryAcquire(key, 2, 5)).isTrue();

        assertThat(redisTemplate.opsForValue().get(key)).isEqualTo("1");
        assertThat(redisTemplate.getExpire(key, TimeUnit.SECONDS)).isBetween(1L, 5L);
    }

    @Test
    void allowsRequestsWithinLimitAndRejectsLimitPlusOne() {
        String key = "rate:test:limit";

        assertThat(rateLimiter.tryAcquire(key, 3, 10)).isTrue();
        assertThat(rateLimiter.tryAcquire(key, 3, 10)).isTrue();
        assertThat(rateLimiter.tryAcquire(key, 3, 10)).isTrue();
        assertThat(rateLimiter.tryAcquire(key, 3, 10)).isFalse();
    }

    @Test
    void allowsAgainAfterWindowExpires() throws InterruptedException {
        String key = "rate:test:expire";

        assertThat(rateLimiter.tryAcquire(key, 1, 1)).isTrue();
        assertThat(rateLimiter.tryAcquire(key, 1, 1)).isFalse();

        Thread.sleep(1500L);

        assertThat(rateLimiter.tryAcquire(key, 1, 1)).isTrue();
    }

    @Test
    void subsequentRequestsDoNotRefreshFixedWindowTtl() throws InterruptedException {
        String key = "rate:test:fixed-window";

        assertThat(rateLimiter.tryAcquire(key, 5, 10)).isTrue();
        Long firstTtlMillis = redisTemplate.getExpire(key, TimeUnit.MILLISECONDS);

        Thread.sleep(1200L);

        assertThat(rateLimiter.tryAcquire(key, 5, 10)).isTrue();
        Long secondTtlMillis = redisTemplate.getExpire(key, TimeUnit.MILLISECONDS);

        assertThat(firstTtlMillis).isNotNull();
        assertThat(secondTtlMillis).isNotNull();
        assertThat(secondTtlMillis).isLessThan(firstTtlMillis - 500L);
    }

    @Test
    void existingKeyWithoutTtlGetsWindowTtl() {
        String key = "rate:test:no-ttl";
        redisTemplate.opsForValue().set(key, "3");
        assertThat(redisTemplate.getExpire(key, TimeUnit.SECONDS)).isEqualTo(-1L);

        assertThat(rateLimiter.tryAcquire(key, 5, 7)).isTrue();

        assertThat(redisTemplate.opsForValue().get(key)).isEqualTo("4");
        assertThat(redisTemplate.getExpire(key, TimeUnit.SECONDS)).isBetween(1L, 7L);
    }

    @Test
    @SuppressWarnings({"unchecked", "rawtypes"})
    void redisExceptionFailsOpen() {
        StringRedisTemplate unavailableRedis = mock(StringRedisTemplate.class);
        when(unavailableRedis.execute(any(), anyList(), any(Object[].class)))
                .thenThrow(new RedisConnectionFailureException("redis down"));
        RedisRateLimiterServiceImpl unavailableRateLimiter = new RedisRateLimiterServiceImpl(unavailableRedis);

        assertThat(unavailableRateLimiter.tryAcquire("rate:test:down", 1, 60)).isTrue();
    }

    @Test
    void invalidLimitOrWindowFailsOpenWithoutRedis() {
        StringRedisTemplate unavailableRedis = mock(StringRedisTemplate.class);
        RedisRateLimiterServiceImpl unavailableRateLimiter = new RedisRateLimiterServiceImpl(unavailableRedis);

        assertThat(unavailableRateLimiter.tryAcquire("rate:test:invalid-limit", 0, 60)).isTrue();
        assertThat(unavailableRateLimiter.tryAcquire("rate:test:invalid-window", 1, 0)).isTrue();
    }
}
