package com.ecommerce.aftersales.service;

public interface RedisRateLimiterService {

    boolean tryAcquire(String key, int limit, long windowSeconds);
}
