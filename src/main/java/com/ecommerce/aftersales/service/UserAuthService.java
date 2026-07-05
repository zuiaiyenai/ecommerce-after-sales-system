package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.LoginRequest;
import com.ecommerce.aftersales.dto.RegisterRequest;
import com.ecommerce.aftersales.dto.ResetPasswordRequest;
import com.ecommerce.aftersales.vo.LoginResponse;
import com.ecommerce.aftersales.vo.UserProfileResponse;

public interface UserAuthService {

    UserProfileResponse register(RegisterRequest request);

    LoginResponse login(LoginRequest request);

    void resetPassword(ResetPasswordRequest request);
}
