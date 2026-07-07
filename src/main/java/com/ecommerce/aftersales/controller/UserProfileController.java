package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.dto.UpdateUserProfileRequest;
import com.ecommerce.aftersales.service.UserAuthService;
import com.ecommerce.aftersales.vo.UserProfileResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.UUID;

@Slf4j
@RestController
@RequestMapping("/miniapp/user")
public class UserProfileController {

    private final UserAuthService userAuthService;
    private final Path uploadRoot;

    public UserProfileController(UserAuthService userAuthService,
                                 @Value("${app.upload.dir:./uploads}") String uploadDir) throws IOException {
        this.userAuthService = userAuthService;
        this.uploadRoot = Paths.get(uploadDir).toAbsolutePath().normalize();
        Files.createDirectories(this.uploadRoot);
    }

    @GetMapping("/profile")
    public ApiResponse<UserProfileResponse> getProfile(@CurrentUserId Long userId) {
        return ApiResponse.success(userAuthService.getProfile(userId));
    }

    @PutMapping("/profile")
    public ApiResponse<UserProfileResponse> updateProfile(@CurrentUserId Long userId,
                                                          @RequestBody UpdateUserProfileRequest request) {
        return ApiResponse.success("更新成功", userAuthService.updateProfile(userId, request));
    }

    @PostMapping("/avatar")
    public ApiResponse<Map<String, String>> uploadAvatar(@CurrentUserId Long userId,
                                                         @RequestParam("file") MultipartFile file) {
        try {
            String fileUrl = storeImage(file);
            UpdateUserProfileRequest request = new UpdateUserProfileRequest();
            request.setAvatarUrl(fileUrl);
            userAuthService.updateProfile(userId, request);
            log.info("Avatar uploaded for user {} -> {}", userId, fileUrl);
            return ApiResponse.success("头像更新成功", Map.of("url", fileUrl));
        } catch (IllegalArgumentException exception) {
            return ApiResponse.fail(400, exception.getMessage());
        } catch (IOException exception) {
            log.error("Avatar upload failed", exception);
            return ApiResponse.fail(500, "头像上传失败");
        }
    }

    private String storeImage(MultipartFile file) throws IOException {
        if (file.isEmpty()) {
            throw new IllegalArgumentException("文件不能为空");
        }
        String contentType = file.getContentType();
        if (contentType == null || !contentType.startsWith("image/")) {
            throw new IllegalArgumentException("只支持图片上传");
        }
        if (file.getSize() > 10 * 1024 * 1024) {
            throw new IllegalArgumentException("文件大小不能超过10MB");
        }

        String dateDir = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
        Path targetDir = uploadRoot.resolve(dateDir);
        Files.createDirectories(targetDir);

        String originalFilename = file.getOriginalFilename();
        String ext = "";
        if (originalFilename != null && originalFilename.contains(".")) {
            ext = originalFilename.substring(originalFilename.lastIndexOf("."));
        }
        String storedFilename = UUID.randomUUID() + ext;
        Path targetPath = targetDir.resolve(storedFilename);
        file.transferTo(targetPath.toFile());

        return "/uploads/" + dateDir + "/" + storedFilename;
    }
}
