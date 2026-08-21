package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.dto.MiniappUserProfileDtos;
import com.ecommerce.aftersales.service.AvatarStorageService;
import com.ecommerce.aftersales.service.MiniappUserProfileService;
import com.ecommerce.aftersales.vo.UserProfileResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/miniapp/user")
public class MiniappUserProfileController {
    private final MiniappUserProfileService profileService;
    private final AvatarStorageService avatarStorageService;

    @GetMapping("/profile")
    public ApiResponse<UserProfileResponse> profile(@CurrentUserId Long userId) {
        return ApiResponse.success(profileService.getProfile(userId));
    }

    @PutMapping("/profile")
    public ApiResponse<UserProfileResponse> updateProfile(
            @CurrentUserId Long userId,
            @Valid @RequestBody MiniappUserProfileDtos.UpdateRequest request
    ) {
        return ApiResponse.success(profileService.updateProfile(userId, request));
    }

    @org.springframework.web.bind.annotation.PostMapping("/avatar")
    public ApiResponse<Map<String, String>> uploadAvatar(
            @CurrentUserId Long userId,
            @RequestParam("file") MultipartFile file
    ) throws IOException {
        String url = avatarStorageService.store(file.getBytes(), file.getOriginalFilename(), file.getContentType());
        profileService.updateAvatar(userId, url);
        return ApiResponse.success(Map.of("url", url));
    }
}
