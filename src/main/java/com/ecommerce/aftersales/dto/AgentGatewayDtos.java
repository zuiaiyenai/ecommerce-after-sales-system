package com.ecommerce.aftersales.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.List;
import java.util.Map;

public class AgentGatewayDtos {

    @Data
    public static class HealthResponse {
        private Boolean ok;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class AttachmentDto {
        private String kind;
        private String name;
        private String source;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class SelectedOrderDto {
        private String order_id;
        private String user_id;
        private String merchant_code;
        private String product_name;
        private String category;
        private String status;
        private String after_sales_status;
        private Double amount;
        private String refund_status;
        private String logistics_status;
        private Boolean has_open_after_sales;
        private List<String> uploaded_evidence;
        private Boolean merchant_rejected_before;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ImageReviewDto {
        private Boolean success;
        private Boolean all_clear;
        private Boolean has_damage_area;
        private Boolean has_outer_package;
        private Boolean has_logistics_label;
        private Boolean logistics_matches_order;
        private String courier_company;
        private String tracking_number;
        private String sender_name;
        private String receiver_name;
        private List<String> missing_visual_evidence;
        private String summary;
        private List<Map<String, Object>> items;
        private Map<String, Object> raw;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ReviewImagesRequest {
        @Valid
        private List<AttachmentDto> attachments;
        private String order_hint;
    }

    @Data
    public static class ReviewImagesResponse {
        private ImageReviewDto image_review;
        private Map<String, Object> trace;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ConversationMessageDto {
        private String role;
        private String content;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class ChatRequest {
        private String user_id;
        private String order_id;
        private Long session_id;

        @NotBlank(message = "message不能为空")
        private String message;

        private String description;
        private Boolean item_opened;
        private Integer human_request_count;
        private Boolean skip_image_review;

        @Valid
        private List<AttachmentDto> attachments;

        @Valid
        private ImageReviewDto image_review;

        @Valid
        private List<ConversationMessageDto> recent_history;

        private Map<String, Object> history_summary;
        private Boolean force_after_sales_apply;

        @Valid
        private SelectedOrderDto selected_order;
    }

    @Data
    public static class PolicyResolveRequest {
        private String merchantCode;
        private String productCategory;
        private String orderStatus;
        private String afterSalesStatus;
        private String messageScene;
    }

    @Data
    public static class PolicyConfigUpdateRequest {
        private String productCode;
        private Double autoRefundLimit;
        private String emotionHandoffMinLevel;
    }

    @Data
    public static class KnowledgeRetrieveRequest {
        @NotBlank(message = "query不能为空")
        private String query;
        private String merchantCode;
        private String productCategory;
        private String scene;
        private String intent;
        private Integer topK;
        private List<String> sources;
    }

    @Data
    public static class KnowledgeHitDto {
        private String source_type;
        private String source_code;
        private String title;
        private String summary;
        private String snippet;
        private Double score;
        private List<String> tags;
        private Map<String, Object> metadata;
    }

    @Data
    public static class KnowledgeRetrieveResponse {
        private String query;
        private String retrieval_mode;
        private Integer total_hits;
        private List<KnowledgeHitDto> hits;
        private Map<String, Object> trace;
    }

    @Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class EmotionAnalyzeRequest {
        private String user_id;
        private Long session_id;
        private String message;

        @Valid
        private List<ConversationMessageDto> recent_history;
    }

    @Data
    public static class EmotionAnalyzeResponse {
        private String emotion_label;
        private Double emotion_score;
        private Double emotion_confidence;
        private Map<String, Object> trace;
    }

    @Data
    public static class TicketDto {
        private String ticket_id;
        private String status;
        private Integer expected_hours;
    }

    @Data
    public static class PersistenceDto {
        private Long session_id;
        private String session_no;
        private Long user_message_id;
        private Long assistant_message_id;
        private Long ticket_log_id;
        private Long notice_id;
    }

    @Data
    public static class ChatResponse {
        private String assistant_reply;
        private String intent;
        private String suggested_action;
        private List<String> evidence_needed;
        private Boolean need_human;
        private String session_mode;
        private List<Map<String, Object>> tool_trace;
        private Map<String, Object> confidence;
        private String fallback_decision;
        private String fallback_progress_hint;
        private Boolean fallback_need_human;
        private TicketDto ticket;
        private Map<String, Object> handoff_summary;
        private ImageReviewDto image_review;
        private PersistenceDto persistence;
        private Map<String, Object> emotion;
        private Map<String, Object> service_policy;
        private Map<String, Object> raw;
        private Map<String, Object> trace;
    }
}
