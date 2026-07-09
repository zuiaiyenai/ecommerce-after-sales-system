package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import com.ecommerce.aftersales.service.KnowledgeService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/admin/knowledge")
@RequiredArgsConstructor
public class KnowledgeManagementController {

    private final KnowledgeService knowledgeService;

    @PostMapping("/import/text")
    public ApiResponse<Map<String, Object>> importTextKnowledge(
            @RequestBody KnowledgeUploadDto.TextImportRequest request
    ) {
        return ApiResponse.success("知识导入任务已创建", knowledgeService.createTextImport(request));
    }

    @PostMapping(value = "/import/file", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<Map<String, Object>> importFileKnowledge(
            @RequestParam("title") String title,
            @RequestParam("knowledgeType") String knowledgeType,
            @RequestParam(value = "scope", defaultValue = "MERCHANT") String scope,
            @RequestParam(value = "merchantCode", required = false) String merchantCode,
            @RequestParam(value = "status", defaultValue = "ENABLED") String status,
            @RequestParam("file") MultipartFile file
    ) {
        return ApiResponse.success(
                "文件导入任务已创建",
                knowledgeService.createFileImport(title, knowledgeType, scope, merchantCode, status, file)
        );
    }

    @PostMapping("/upload")
    public ApiResponse<Map<String, Object>> uploadKnowledge(@RequestBody KnowledgeUploadDto.UploadRequest request) {
        return ApiResponse.success("兼容导入任务已创建", knowledgeService.uploadKnowledge(request));
    }

    @PostMapping("/batch-upload")
    public ApiResponse<Map<String, Object>> batchUploadKnowledge(@RequestBody List<KnowledgeUploadDto.UploadRequest> requests) {
        return ApiResponse.success("批量导入任务已创建", knowledgeService.batchUploadKnowledge(requests));
    }

    @GetMapping("/list")
    public ApiResponse<List<KnowledgeUploadDto.KnowledgeInfo>> listKnowledge(
            @RequestParam(required = false) String sourceType,
            @RequestParam(required = false) String merchantCode,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "20") Integer pageSize
    ) {
        return ApiResponse.success("查询成功", knowledgeService.listKnowledge(sourceType, merchantCode, page, pageSize));
    }

    @GetMapping("/{id}")
    public ApiResponse<KnowledgeUploadDto.KnowledgeInfo> getKnowledge(@PathVariable Long id) {
        return ApiResponse.success("查询成功", knowledgeService.getKnowledgeById(id));
    }

    @PutMapping("/{id}")
    public ApiResponse<Map<String, Object>> updateKnowledge(
            @PathVariable Long id,
            @RequestBody KnowledgeUploadDto.UpdateRequest request
    ) {
        return ApiResponse.success("更新成功", knowledgeService.updateKnowledge(id, request));
    }

    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteKnowledge(@PathVariable Long id) {
        knowledgeService.deleteKnowledge(id);
        return ApiResponse.success("删除成功", null);
    }

    @PostMapping("/reindex")
    public ApiResponse<Map<String, Object>> reindexAll() {
        return ApiResponse.success("已触发全量重建", knowledgeService.reindexAll());
    }

    @PostMapping("/{id}/sync")
    public ApiResponse<Map<String, Object>> syncKnowledge(@PathVariable Long id) {
        return ApiResponse.success("已触发重新处理", knowledgeService.syncKnowledge(id));
    }

    @GetMapping("/test-retrieval")
    public ApiResponse<List<Map<String, Object>>> testRetrieval(
            @RequestParam String query,
            @RequestParam(required = false) String merchantCode,
            @RequestParam(defaultValue = "5") Integer topK
    ) {
        return ApiResponse.success("检索成功", knowledgeService.testRetrieval(query, merchantCode, topK));
    }
}
