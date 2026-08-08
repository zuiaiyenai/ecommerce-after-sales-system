package com.ecommerce.aftersales.contract;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.controller.FileUploadController;
import com.ecommerce.aftersales.controller.InternalAgentToolsController;
import com.ecommerce.aftersales.controller.UserChatController;
import com.ecommerce.aftersales.service.impl.MerchantCsServiceImpl;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Constructor;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class MessageContractTest {

    @TempDir
    Path tempDir;

    @Test
    void imageUploadResponseUsesOnlyFileUrl() throws Exception {
        FileUploadController controller = new FileUploadController(tempDir.toString());
        MockMultipartFile file = new MockMultipartFile(
                "file", "evidence.png", "image/png", new byte[]{1, 2, 3});

        var response = controller.uploadImage(file);

        assertThat(response.getSuccess()).isTrue();
        assertThat(response.getData()).containsKey("fileUrl");
        assertThat(response.getData()).doesNotContainKeys("url", "path", "src");
    }

    @Test
    void imageAndFileMessagesRequireExplicitFileUrlAtEveryWriteBoundary() {
        Object[] boundaries = {
                instantiate(InternalAgentToolsController.class),
                instantiate(UserChatController.class),
                instantiate(MerchantCsServiceImpl.class)
        };

        for (Object boundary : boundaries) {
            assertThatThrownBy(() -> ReflectionTestUtils.invokeMethod(
                    boundary, "resolveMessageFileUrl", "IMAGE", null))
                    .isInstanceOf(BizException.class)
                    .hasMessageContaining("fileUrl");
            assertThatThrownBy(() -> ReflectionTestUtils.invokeMethod(
                    boundary, "resolveMessageFileUrl", "FILE", " "))
                    .isInstanceOf(BizException.class)
                    .hasMessageContaining("fileUrl");
            assertThat((String) ReflectionTestUtils.invokeMethod(
                    boundary, "resolveMessageFileUrl", "IMAGE", "/uploads/evidence.png"))
                    .isEqualTo("/uploads/evidence.png");
            assertThat((String) ReflectionTestUtils.invokeMethod(
                    boundary, "resolveMessageFileUrl", "TEXT", "/uploads/not-a-text-attachment.png"))
                    .isNull();
        }
    }

    @Test
    void messageContentNeverActsAsAnImplicitFileUrl() {
        Object[] boundaries = {
                instantiate(InternalAgentToolsController.class),
                instantiate(UserChatController.class),
                instantiate(MerchantCsServiceImpl.class)
        };

        for (Object boundary : boundaries) {
            assertThat((String) ReflectionTestUtils.invokeMethod(
                    boundary, "resolveMessageContent", "IMAGE", "商品破损位置"))
                    .isEqualTo("商品破损位置");
            assertThat((String) ReflectionTestUtils.invokeMethod(
                    boundary, "resolveMessageContent", "IMAGE", ""))
                    .isEqualTo("[图片]");
        }
    }

    @Test
    void chatResponseTimesUseIso8601WithOffset() {
        LocalDateTime value = LocalDateTime.of(2026, 7, 14, 12, 30, 45);
        String userTime = ReflectionTestUtils.invokeMethod(
                instantiate(UserChatController.class), "formatTime", value);
        String merchantTime = ReflectionTestUtils.invokeMethod(
                instantiate(MerchantCsServiceImpl.class), "format", value);

        assertThat(OffsetDateTime.parse(userTime)).isNotNull();
        assertThat(OffsetDateTime.parse(merchantTime)).isNotNull();
    }

    private static <T> T instantiate(Class<T> type) {
        try {
            Constructor<?> constructor = type.getDeclaredConstructors()[0];
            constructor.setAccessible(true);
            return type.cast(constructor.newInstance(new Object[constructor.getParameterCount()]));
        } catch (ReflectiveOperationException exception) {
            throw new AssertionError("Cannot instantiate " + type.getName(), exception);
        }
    }
}
