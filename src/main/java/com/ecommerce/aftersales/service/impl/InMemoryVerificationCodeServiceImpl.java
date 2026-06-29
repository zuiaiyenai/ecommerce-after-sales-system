package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.service.VerificationCodeService;
import org.springframework.stereotype.Service;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class InMemoryVerificationCodeServiceImpl implements VerificationCodeService {

    private static final int EXPIRE_MINUTES = 5;
    private static final int SEND_INTERVAL_SECONDS = 60;
    private static final SecureRandom RANDOM = new SecureRandom();

    private final Map<String, CodeRecord> codeStore = new ConcurrentHashMap<>();

    @Override
    public String sendCode(String phone, String scene) {
        String key = buildKey(phone, scene);
        CodeRecord oldRecord = codeStore.get(key);
        LocalDateTime now = LocalDateTime.now();
        if (oldRecord != null && oldRecord.sendTime.plusSeconds(SEND_INTERVAL_SECONDS).isAfter(now)) {
            throw new BizException("验证码发送过于频繁，请稍后再试");
        }

        String code = String.format("%06d", RANDOM.nextInt(1_000_000));
        codeStore.put(key, new CodeRecord(code, now, now.plusMinutes(EXPIRE_MINUTES)));
        return code;
    }

    @Override
    public void verifyCode(String phone, String scene, String code) {
        String key = buildKey(phone, scene);
        CodeRecord record = codeStore.get(key);
        if (record == null) {
            throw new BizException("请先获取验证码");
        }
        if (record.expireTime.isBefore(LocalDateTime.now())) {
            codeStore.remove(key);
            throw new BizException("验证码已过期，请重新获取");
        }
        if (!record.code.equals(code)) {
            throw new BizException("验证码错误");
        }
        codeStore.remove(key);
    }

    private String buildKey(String phone, String scene) {
        return scene + ":" + phone;
    }

    private record CodeRecord(String code, LocalDateTime sendTime, LocalDateTime expireTime) {
    }
}
