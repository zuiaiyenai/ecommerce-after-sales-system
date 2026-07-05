package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.dto.LoginRequest;
import com.ecommerce.aftersales.dto.RegisterRequest;
import com.ecommerce.aftersales.dto.ResetPasswordRequest;
import com.ecommerce.aftersales.dto.SendCodeRequest;
import com.ecommerce.aftersales.service.UserAuthService;
import com.ecommerce.aftersales.service.VerificationCodeService;
import com.ecommerce.aftersales.vo.LoginResponse;
import com.ecommerce.aftersales.vo.UserProfileResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/miniapp/auth")
public class UserAuthController {

    private final UserAuthService userAuthService;
    private final VerificationCodeService verificationCodeService;

    @PostMapping("/code")
    public ApiResponse<Map<String, String>> sendCode(@Valid @RequestBody SendCodeRequest request) {
        String code = verificationCodeService.sendCode(request.getPhone(), request.getScene());
        return ApiResponse.success("验证码发送成功", Map.of("code", code));
    }

    @PostMapping("/register")
    public ApiResponse<UserProfileResponse> register(@Valid @RequestBody RegisterRequest request) {
        return ApiResponse.success("注册成功", userAuthService.register(request));
    }

    @PostMapping("/login")
    public ApiResponse<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        return ApiResponse.success("登录成功", userAuthService.login(request));
    }

    @PostMapping("/password/reset")
    public ApiResponse<Void> resetPassword(@Valid @RequestBody ResetPasswordRequest request) {
        userAuthService.resetPassword(request);
        return ApiResponse.success("密码重置成功", null);
    }
}
