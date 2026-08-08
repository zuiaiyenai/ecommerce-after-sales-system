package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.service.RedisRateLimiterService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.util.Collections;

@Slf4j
@Service
@RequiredArgsConstructor
public class RedisRateLimiterServiceImpl implements RedisRateLimiterService {

    private static final DefaultRedisScript<Long> RATE_LIMITER_SCRIPT = rateLimiterScript();

    private final StringRedisTemplate redisTemplate;

    @Override
    public boolean tryAcquire(String key, int limit, long windowSeconds) {
        if (limit <= 0 || windowSeconds <= 0) {
            return true;
        }
        try {
            Long allowed = redisTemplate.execute(
                    RATE_LIMITER_SCRIPT,
                    Collections.singletonList(key),
                    String.valueOf(limit),
                    String.valueOf(windowSeconds)
            );
            return allowed == null || allowed == 1L;
        } catch (Exception exception) {
            log.warn("Redis rate limiter unavailable key={}", key, exception);
            return true;
        }
    }

    private static DefaultRedisScript<Long> rateLimiterScript() {
        DefaultRedisScript<Long> script = new DefaultRedisScript<>();
        script.setLocation(new ClassPathResource("scripts/rate_limiter.lua"));
        script.setResultType(Long.class);
        return script;
    }
}
