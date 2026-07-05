package com.ecommerce.aftersales.dto;

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
    public static class AttachmentDto {
        private String kind;
        private String name;
        private String source;
    }

    @Data
    public static class SelectedOrderDto {
        private String order_id;
        private String user_id;
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
    public static class ChatRequest {
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
        private SelectedOrderDto selected_order;
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
        private String ticket_no;
        private Long ticket_log_id;
        private Long notice_id;
    }

    @Data
    public static class ChatResponse {
        private String assistant_reply;
        private String intent;
        private String suggested_action;
        private List<String> evidence_needed;
        private String fallback_decision;
        private String fallback_progress_hint;
        private Boolean fallback_need_human;
        private String session_mode;
        private TicketDto ticket;
        private Map<String, Object> handoff_summary;
        private ImageReviewDto image_review;
        private PersistenceDto persistence;
        private Map<String, Object> emotion;
        private Map<String, Object> raw;
        private Map<String, Object> trace;
    }
}
