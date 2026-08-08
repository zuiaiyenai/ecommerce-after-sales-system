package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.MiniappUserProfileDtos;
import com.ecommerce.aftersales.vo.UserProfileResponse;

public interface MiniappUserProfileService {
    UserProfileResponse getProfile(Long userId);
    UserProfileResponse updateProfile(Long userId, MiniappUserProfileDtos.UpdateRequest request);
    UserProfileResponse updateAvatar(Long userId, String avatarUrl);
}
