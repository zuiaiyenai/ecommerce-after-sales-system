package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.MiniappUserProfileDtos;
import com.ecommerce.aftersales.entity.User;
import com.ecommerce.aftersales.mapper.UserMapper;
import com.ecommerce.aftersales.service.MiniappUserProfileService;
import com.ecommerce.aftersales.vo.UserProfileResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class MiniappUserProfileServiceImpl implements MiniappUserProfileService {
    private final UserMapper userMapper;

    @Override
    public UserProfileResponse getProfile(Long userId) {
        return toResponse(requireUser(userId));
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserProfileResponse updateProfile(Long userId, MiniappUserProfileDtos.UpdateRequest request) {
        User user = requireUser(userId);
        user.setNickname(request.getNickname().trim());
        user.setAvatarUrl(normalizeNullable(request.getAvatarUrl()));
        userMapper.updateById(user);
        return toResponse(user);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserProfileResponse updateAvatar(Long userId, String avatarUrl) {
        User user = requireUser(userId);
        user.setAvatarUrl(avatarUrl);
        userMapper.updateById(user);
        return toResponse(user);
    }

    private User requireUser(Long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) throw new BizException(404, "用户不存在");
        return user;
    }

    private static String normalizeNullable(String value) {
        if (value == null || value.isBlank()) return null;
        return value.trim();
    }

    private static UserProfileResponse toResponse(User user) {
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
