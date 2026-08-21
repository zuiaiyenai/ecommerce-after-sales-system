ALTER TABLE after_sales_ticket
    ADD COLUMN ai_review_status VARCHAR(32) NOT NULL DEFAULT 'RUNNING'
        COMMENT 'AI审批运行阶段：RUNNING/WAITING_EVIDENCE/RESUME_PENDING/COMPLETED/MANUAL_REQUIRED'
        AFTER ai_review_request_id,
    ADD COLUMN evidence_revision INT NOT NULL DEFAULT 0
        COMMENT '审核上下文凭证版本，每次有效补充原子递增'
        AFTER ai_review_status;

ALTER TABLE chat_message
    ADD COLUMN business_key VARCHAR(191) NULL COMMENT '重要业务通知幂等键' AFTER file_url,
    ADD UNIQUE KEY uk_chat_message_business_key (business_key);

UPDATE after_sales_ticket
SET ai_review_status = CASE
    WHEN ai_review_result = 'APPROVE' THEN 'COMPLETED'
    WHEN ai_review_result IN ('MANUAL_REVIEW', 'MANUAL_REVIEW_REQUIRED') OR manual_review_required = 1
        THEN 'MANUAL_REQUIRED'
    ELSE 'RUNNING'
END;

-- 历史活动工单是否已有存活的 LangGraph 无法仅靠 MySQL 判断。
-- 本迁移不为 ai_review_request_id 为空的历史工单补发 Start，避免重复审批；上线前应单独核对并受控恢复或转人工。
