package com.ecommerce.aftersales.common;

import com.ecommerce.aftersales.common.enums.ErrorCode;
import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.Map;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(KnowledgeRevisionConflictException.class)
    public ResponseEntity<ApiResponse<Map<String, String>>> handleKnowledgeRevisionConflict(KnowledgeRevisionConflictException exception) {
        Map<String, String> data = Map.of(
                "currentRevision", String.valueOf(exception.getCurrentRevision()),
                "reviewStatus", exception.getReviewStatus());
        return ResponseEntity.status(HttpStatus.CONFLICT)
                .body(new ApiResponse<>(false, HttpStatus.CONFLICT.value(),
                        "当前数据已被更新，请刷新后重试", data));
    }

    @ExceptionHandler(BizException.class)
    public ResponseEntity<ApiResponse<Void>> handleBizException(BizException exception) {
        log.warn("business exception: code={}, message={}", exception.getCode(), exception.getMessage());
        HttpStatus status = resolveHttpStatus(exception.getCode(), HttpStatus.BAD_REQUEST);
        ResponseEntity.BodyBuilder response = ResponseEntity.status(status);
        if (status == HttpStatus.TOO_MANY_REQUESTS) {
            response.header("Retry-After", "1");
        }
        return response.body(ApiResponse.fail(exception.getCode(), publicMessage(status)));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodArgumentNotValidException(MethodArgumentNotValidException exception) {
        String message = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .orElse(ErrorCode.BAD_REQUEST.getMessage());
        log.warn("request validation failed: {}", message);
        return ResponseEntity.badRequest().body(ApiResponse.fail(
                ErrorCode.BAD_REQUEST, "请求参数不正确，请检查后重试"));
    }

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleConstraintViolationException(ConstraintViolationException exception) {
        log.warn("constraint violation: {}", exception.getMessage());
        return ResponseEntity.badRequest().body(ApiResponse.fail(
                ErrorCode.BAD_REQUEST, "请求参数不正确，请检查后重试"));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiResponse<Void>> handleHttpMessageNotReadableException(HttpMessageNotReadableException exception) {
        log.warn("request body parse failed: {}", exception.getMessage());
        return ResponseEntity.badRequest().body(ApiResponse.fail(ErrorCode.BAD_REQUEST, "请求体格式不正确，请检查 JSON 参数"));
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodArgumentTypeMismatchException(
            MethodArgumentTypeMismatchException exception) {
        String message = "请求参数 " + exception.getName() + " 格式不正确";
        log.warn("request argument type mismatch: name={}, value={}", exception.getName(), exception.getValue());
        return ResponseEntity.badRequest().body(ApiResponse.fail(ErrorCode.BAD_REQUEST, message));
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<ApiResponse<Void>> handleMaxUploadSizeExceededException(MaxUploadSizeExceededException exception) {
        log.warn("uploaded file exceeds limit: {}", exception.getMessage());
        return ResponseEntity.badRequest().body(ApiResponse.fail(ErrorCode.BAD_REQUEST, "文件大小不能超过10MB"));
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ApiResponse<Void>> handleNoResourceFoundException(NoResourceFoundException exception) {
        log.debug("resource not found: {}", exception.getResourcePath());
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(ApiResponse.fail(ErrorCode.NOT_FOUND, "请求的接口或资源不存在"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleException(Exception exception) {
        log.error("system exception", exception);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiResponse.fail(ErrorCode.INTERNAL_ERROR));
    }

    private HttpStatus resolveHttpStatus(Integer code, HttpStatus fallback) {
        if (code == null) {
            return fallback;
        }
        HttpStatus status = HttpStatus.resolve(code);
        if (status == null) {
            return fallback;
        }
        return status;
    }

    private String publicMessage(HttpStatus status) {
        return switch (status) {
            case BAD_REQUEST -> "请求参数不正确，请检查后重试";
            case UNAUTHORIZED -> "登录状态已失效，请重新登录";
            case FORBIDDEN -> "当前账号无权执行此操作";
            case NOT_FOUND -> "请求的业务记录不存在或已失效";
            case CONFLICT -> "当前状态已变化，请刷新后重试";
            case TOO_MANY_REQUESTS -> "请求较多，请稍后重试";
            default -> "服务暂时不可用，请稍后重试";
        };
    }
}
