package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.dto.EmotionPolicyDtos.*;
import com.ecommerce.aftersales.service.EmotionPolicyService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/merchant-cs/emotion-policy")
public class EmotionPolicyController {

    private final EmotionPolicyService emotionPolicyService;

    @GetMapping("/workspace")
    public ApiResponse<EmotionPolicyWorkspace> workspace() {
        return ApiResponse.success("OK", emotionPolicyService.getWorkspace());
    }

    @GetMapping("/versions")
    public ApiResponse<List<EmotionPolicyVersionItem>> versions() {
        return ApiResponse.success("OK", emotionPolicyService.listVersions());
    }

    @PutMapping("/draft")
    public ApiResponse<EmotionPolicyWorkspace> saveDraft(@Valid @RequestBody EmotionPolicySaveRequest request) {
        return ApiResponse.success("Draft saved", emotionPolicyService.saveDraft(request));
    }

    @PostMapping("/publish")
    public ApiResponse<EmotionPolicyWorkspace> publish(@RequestBody EmotionPolicyPublishRequest request) {
        return ApiResponse.success("Published", emotionPolicyService.publish(request));
    }

    @PostMapping("/rollback")
    public ApiResponse<EmotionPolicyWorkspace> rollback(@RequestBody EmotionPolicyRollbackRequest request) {
        return ApiResponse.success("Rolled back", emotionPolicyService.rollback(request));
    }

    @PostMapping("/test")
    public ApiResponse<EmotionPolicyTestResponse> test(@Valid @RequestBody EmotionPolicyTestRequest request) {
        return ApiResponse.success("Test completed", emotionPolicyService.testPolicy(request));
    }
}
