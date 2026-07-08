package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.AdminConsoleDtos.*;
import com.ecommerce.aftersales.service.AdminConsoleService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
@RequestMapping("/admin")
public class AdminConsoleController {

    private final AdminConsoleService adminConsoleService;

    @PostMapping("/auth/login")
    public ApiResponse<AdminLoginResponse> login(@RequestBody AdminLoginRequest request) {
        return ApiResponse.success("登录成功", adminConsoleService.login(request));
    }

    @PostMapping("/auth/logout")
    public ApiResponse<Void> logout() {
        adminConsoleService.logout();
        return ApiResponse.success("退出成功", null);
    }

    @GetMapping("/auth/me")
    public ApiResponse<AdminProfile> me() {
        return ApiResponse.success("获取成功", adminConsoleService.getCurrentAdmin());
    }

    @GetMapping("/overview")
    public ApiResponse<AdminOverview> overview() {
        return ApiResponse.success("获取成功", adminConsoleService.getOverview());
    }

    @GetMapping("/service-accounts")
    public ApiResponse<PageResult<ServiceAccountView>> listServiceAccounts(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "100") long size
    ) {
        return ApiResponse.success("获取成功", adminConsoleService.listServiceAccounts(page, size));
    }

    @PostMapping("/service-accounts")
    public ApiResponse<ServiceAccountView> createServiceAccount(@RequestBody ServiceAccountUpsertRequest request) {
        return ApiResponse.success("创建成功", adminConsoleService.createServiceAccount(request));
    }

    @PutMapping("/service-accounts/{accountId}")
    public ApiResponse<ServiceAccountView> updateServiceAccount(
            @PathVariable Long accountId,
            @RequestBody ServiceAccountUpsertRequest request
    ) {
        return ApiResponse.success("更新成功", adminConsoleService.updateServiceAccount(accountId, request));
    }

    @PostMapping("/service-accounts/{accountId}/reset-password")
    public ApiResponse<PasswordResetView> resetServiceAccountPassword(@PathVariable Long accountId) {
        return ApiResponse.success("重置成功", adminConsoleService.resetServiceAccountPassword(accountId));
    }
}
