ALTER TABLE after_sales_ticket
    CHANGE COLUMN ai_classify_result ai_review_audit_json TEXT NULL
        COMMENT 'AI初审审计JSON，包含视觉证据、RAG命中、风险原因与策略引用',
    CHANGE COLUMN ai_confidence ai_review_confidence DECIMAL(3,2) NULL
        COMMENT 'AI初审置信度(0~1，表示本次审核结论把握度)',
    CHANGE COLUMN ai_recommend_type ai_suggested_after_sale_type VARCHAR(30) NULL
        COMMENT 'AI建议售后类型：REFUND_ONLY/REFUND_RETURN/EXCHANGE/REPAIR',
    CHANGE COLUMN need_human_review manual_review_required TINYINT NOT NULL DEFAULT 0
        COMMENT 'AI初审是否要求人工复核：0否，1是',
    MODIFY COLUMN ai_review_request_id VARCHAR(64) NULL
        COMMENT 'AI初审幂等请求ID',
    MODIFY COLUMN ai_review_result VARCHAR(30) NULL
        COMMENT 'AI初审结论：APPROVE/MANUAL_REVIEW_REQUIRED',
    MODIFY COLUMN ai_review_reason VARCHAR(500) NULL
        COMMENT 'AI初审原因',
    MODIFY COLUMN ai_review_time DATETIME NULL
        COMMENT 'AI初审时间',
    MODIFY COLUMN status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        COMMENT '状态：PENDING/PENDING_REVIEW待审核，PROCESSING处理中，MANUAL_REVIEW_REQUIRED待人工复核，APPROVED/REJECTED/COMPLETED/CLOSED终态',
    MODIFY COLUMN active_scope_key VARCHAR(128)
        GENERATED ALWAYS AS (
            CASE
                WHEN deleted = 0 AND status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING')
                    THEN CONCAT(user_id, ':', order_id)
                ELSE NULL
            END
        ) STORED COMMENT '活动工单幂等作用域键：同一用户同一订单仅允许一张打开中的售后单';
