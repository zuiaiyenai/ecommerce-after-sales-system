package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.BizException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

@Service
public class AvatarStorageService {
    private static final Set<String> ALLOWED_EXTENSIONS = Set.of(".jpg", ".jpeg", ".png", ".webp", ".gif");
    private final Path avatarRoot;

    public AvatarStorageService(@Value("${app.upload.dir:./uploads}") String uploadDir) throws IOException {
        this.avatarRoot = Paths.get(uploadDir).toAbsolutePath().normalize().resolve("avatars");
        Files.createDirectories(avatarRoot);
    }

    public String store(byte[] content, String originalFilename, String contentType) {
        if (content.length == 0) throw new BizException(400, "头像文件不能为空");
        if (content.length > 10 * 1024 * 1024) throw new BizException(400, "头像大小不能超过10MB");
        if (contentType == null || !contentType.toLowerCase(Locale.ROOT).startsWith("image/")) {
            throw new BizException(400, "只支持图片格式的头像");
        }
        String extension = extensionOf(originalFilename);
        if (!ALLOWED_EXTENSIONS.contains(extension)) throw new BizException(400, "不支持的头像文件格式");
        String dateDir = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
        Path directory = avatarRoot.resolve(dateDir).normalize();
        if (!directory.startsWith(avatarRoot)) throw new BizException(400, "头像存储路径无效");
        try {
            Files.createDirectories(directory);
            String filename = UUID.randomUUID() + extension;
            Files.write(directory.resolve(filename), content);
            return "/uploads/avatars/" + dateDir + "/" + filename;
        } catch (IOException exception) {
            throw new BizException(500, "头像上传失败");
        }
    }

    private static String extensionOf(String filename) {
        if (filename == null) return "";
        int index = filename.lastIndexOf('.');
        return index < 0 ? "" : filename.substring(index).toLowerCase(Locale.ROOT);
    }
}
