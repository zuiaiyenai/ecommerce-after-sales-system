package com.ecommerce.aftersales.service;

public interface VerificationCodeService {

    String sendCode(String phone, String scene);

    void verifyCode(String phone, String scene, String code);
}
