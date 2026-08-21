package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.LoginRequest;
import com.ecommerce.aftersales.dto.RegisterRequest;
import com.ecommerce.aftersales.dto.ResetPasswordRequest;
import com.ecommerce.aftersales.entity.User;
import com.ecommerce.aftersales.mapper.UserMapper;
import com.ecommerce.aftersales.service.UserAuthService;
import com.ecommerce.aftersales.service.VerificationCodeService;
import com.ecommerce.aftersales.util.JwtTokenUtil;
import com.ecommerce.aftersales.vo.LoginResponse;
import com.ecommerce.aftersales.vo.UserProfileResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

@Service
@RequiredArgsConstructor
public class UserAuthServiceImpl implements UserAuthService {

    private static final int USER_STATUS_NORMAL = 1;
    private static final int BIND_STATUS_UNBOUND = 0;
    private static final String ROLE_TYPE_USER = "USER";
    private static final String REGISTER_SCENE = "REGISTER";
    private static final String RESET_PASSWORD_SCENE = "RESET_PASSWORD";

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final VerificationCodeService verificationCodeService;
    private final JwtTokenUtil jwtTokenUtil;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserProfileResponse register(RegisterRequest request) {
        verificationCodeService.verifyCode(request.getPhone(), REGISTER_SCENE, request.getCode());
        if (findByPhone(request.getPhone()) != null) {
            throw new BizException("手机号已注册");
        }
        if (StringUtils.hasText(request.getOpenid()) && findByOpenid(request.getOpenid()) != null) {
            throw new BizException("微信账号已绑定其他用户");
        }

        User user = new User();
        user.setUserAccount(request.getPhone());
        user.setPhone(request.getPhone());
        user.setPassword(passwordEncoder.encode(request.getPassword()));
        user.setOpenid(request.getOpenid());
        user.setNickname(StringUtils.hasText(request.getNickname()) ? request.getNickname() : "微信用户");
        user.setAvatarUrl(request.getAvatarUrl());
        user.setBindStatus(BIND_STATUS_UNBOUND);
        user.setRoleType(ROLE_TYPE_USER);
        user.setStatus(USER_STATUS_NORMAL);
        user.setDeleted(0);
        userMapper.insert(user);
        return toProfile(user);
    }

    @Override
    public LoginResponse login(LoginRequest request) {
        User user = findByPhone(request.getPhone());
        if (user == null || !passwordEncoder.matches(request.getPassword(), user.getPassword())) {
            throw new BizException("手机号或密码错误");
        }
        if (!Integer.valueOf(USER_STATUS_NORMAL).equals(user.getStatus())) {
            throw new BizException(403, "账号已被禁用，请联系客服");
        }
        user.setLastLoginTime(java.time.LocalDateTime.now());
        userMapper.updateById(user);
        return LoginResponse.builder()
                .token(jwtTokenUtil.generateToken(user.getId(), user.getPhone()))
                .userId(user.getId())
                .userAccount(user.getUserAccount())
                .phone(user.getPhone())
                .nickname(user.getNickname())
                .avatarUrl(user.getAvatarUrl())
                .bindStatus(user.getBindStatus())
                .build();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void resetPassword(ResetPasswordRequest request) {
        if (!request.getNewPassword().equals(request.getConfirmPassword())) {
            throw new BizException("两次输入密码不同");
        }
        verificationCodeService.verifyCode(request.getPhone(), RESET_PASSWORD_SCENE, request.getCode());
        User user = findByPhone(request.getPhone());
        if (user == null) {
            throw new BizException("用户不存在");
        }
        user.setPassword(passwordEncoder.encode(request.getNewPassword()));
        userMapper.updateById(user);
    }

    private User findByPhone(String phone) {
        return userMapper.selectOne(new LambdaQueryWrapper<User>()
                .eq(User::getPhone, phone)
                .last("limit 1"));
    }

    private User findByOpenid(String openid) {
        return userMapper.selectOne(new LambdaQueryWrapper<User>()
                .eq(User::getOpenid, openid)
                .last("limit 1"));
    }

    private UserProfileResponse toProfile(User user) {
        return UserProfileResponse.builder()
                .userId(String.valueOf(user.getId()))
                .userAccount(user.getUserAccount())
                .phone(user.getPhone())
                .nickname(user.getNickname())
                .avatarUrl(user.getAvatarUrl())
                .bindStatus(user.getBindStatus())
                .build();
    }
}
