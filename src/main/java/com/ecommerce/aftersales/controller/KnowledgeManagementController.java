package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import com.ecommerce.aftersales.service.KnowledgeService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 知识库管理接口
 * 用于管理员上传、编辑、删除售后政策知识库
 */
@RestController
@RequestMapping("/admin/knowledge")
@RequiredArgsConstructor
public class KnowledgeManagementController {

    private final KnowledgeService knowledgeService;

    /**
     * 上传新的知识库文档
     * 会自动切片并生成向量embeddings
     */
    @PostMapping("/upload")
    public ApiResponse<Map<String, Object>> uploadKnowledge(@RequestBody KnowledgeUploadDto.UploadRequest request) {
        Map<String, Object> result = knowledgeService.uploadKnowledge(request);
        return ApiResponse.success("知识库上传成功", result);
    }

    /**
     * 批量上传知识库文档
     */
    @PostMapping("/batch-upload")
    public ApiResponse<Map<String, Object>> batchUploadKnowledge(@RequestBody List<KnowledgeUploadDto.UploadRequest> requests) {
        Map<String, Object> result = knowledgeService.batchUploadKnowledge(requests);
        return ApiResponse.success("批量上传成功", result);
    }

    /**
     * 查询知识库列表
     */
    @GetMapping("/list")
    public ApiResponse<List<KnowledgeUploadDto.KnowledgeInfo>> listKnowledge(
            @RequestParam(required = false) String sourceType,
            @RequestParam(required = false) String merchantCode,
            @RequestParam(defaultValue = "1") Integer page,
            @RequestParam(defaultValue = "20") Integer pageSize
    ) {
        List<KnowledgeUploadDto.KnowledgeInfo> list = knowledgeService.listKnowledge(sourceType, merchantCode, page, pageSize);
        return ApiResponse.success("查询成功", list);
    }

    /**
     * 更新知识库文档
     */
    @PutMapping("/{id}")
    public ApiResponse<Map<String, Object>> updateKnowledge(
            @PathVariable Long id,
            @RequestBody KnowledgeUploadDto.UpdateRequest request
    ) {
        Map<String, Object> result = knowledgeService.updateKnowledge(id, request);
        return ApiResponse.success("更新成功", result);
    }

    /**
     * 删除知识库文档
     */
    @DeleteMapping("/{id}")
    public ApiResponse<Void> deleteKnowledge(@PathVariable Long id) {
        knowledgeService.deleteKnowledge(id);
        return ApiResponse.success("删除成功", null);
    }

    /**
     * 重新生成向量embeddings（当embedding模型更换时）
     */
    @PostMapping("/reindex")
    public ApiResponse<Map<String, Object>> reindexAll() {
        Map<String, Object> result = knowledgeService.reindexAll();
        return ApiResponse.success("重建索引成功", result);
    }

    /**
     * 测试知识库检索
     */
    @GetMapping("/test-retrieval")
    public ApiResponse<List<Map<String, Object>>> testRetrieval(
            @RequestParam String query,
            @RequestParam(required = false) String merchantCode,
            @RequestParam(defaultValue = "5") Integer topK
    ) {
        List<Map<String, Object>> results = knowledgeService.testRetrieval(query, merchantCode, topK);
        return ApiResponse.success("检索成功", results);
    }
}
