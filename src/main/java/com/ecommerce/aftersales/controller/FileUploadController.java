package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;
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
@RequestMapping("/upload")
public class FileUploadController {

    private final Path uploadRoot;

    public FileUploadController(@Value("${app.upload.dir:./uploads}") String uploadDir) throws IOException {
        this.uploadRoot = Paths.get(uploadDir).toAbsolutePath().normalize();
        Files.createDirectories(this.uploadRoot);
    }

    @PostMapping("/image")
    public ApiResponse<Map<String, String>> uploadImage(@RequestParam("file") MultipartFile file) {
        try {
            if (file.isEmpty()) {
                return ApiResponse.fail(400, "文件不能为空");
            }
            String contentType = file.getContentType();
            if (contentType == null || !contentType.startsWith("image/")) {
                return ApiResponse.fail(400, "只支持图片上传");
            }
            if (file.getSize() > 10 * 1024 * 1024) {
                return ApiResponse.fail(400, "文件大小不能超过10MB");
            }

            String dateDir = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
            Path targetDir = uploadRoot.resolve(dateDir);
            Files.createDirectories(targetDir);

            String originalFilename = file.getOriginalFilename();
            String ext = "";
            if (originalFilename != null && originalFilename.contains(".")) {
                ext = originalFilename.substring(originalFilename.lastIndexOf("."));
            }
            String storedFilename = UUID.randomUUID().toString() + ext;
            Path targetPath = targetDir.resolve(storedFilename);
            file.transferTo(targetPath.toFile());

            String fileUrl = "/uploads/" + dateDir + "/" + storedFilename;
            log.info("File uploaded: {} -> {}", originalFilename, fileUrl);
            return ApiResponse.success("上传成功", Map.of("fileUrl", fileUrl));
        } catch (IOException e) {
            log.error("File upload failed", e);
            return ApiResponse.fail(500, "文件上传失败");
        }
    }
}
