USE ecommerce_aftersales;

ALTER TABLE sys_user
    ADD COLUMN merchant_code VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码' AFTER password,
    ADD INDEX idx_sys_user_merchant (merchant_code);

ALTER TABLE sys_user
    DROP INDEX uk_sys_user_username,
    ADD UNIQUE KEY uk_sys_user_merchant_username (merchant_code, username);

ALTER TABLE product_info
    ADD COLUMN merchant_id BIGINT NULL COMMENT '所属商家/客服主体ID(sys_user)' AFTER product_code,
    ADD COLUMN merchant_code VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码' AFTER merchant_id,
    ADD INDEX idx_product_info_merchant (merchant_code);

ALTER TABLE order_info
    ADD COLUMN merchant_id BIGINT NULL COMMENT '所属商家/客服主体ID(sys_user)' AFTER user_id,
    ADD COLUMN merchant_code VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码' AFTER merchant_id,
    ADD INDEX idx_order_info_merchant (merchant_code);

ALTER TABLE after_sales_ticket
    ADD COLUMN merchant_id BIGINT NULL COMMENT '所属商家/客服主体ID(sys_user)' AFTER user_id,
    ADD COLUMN merchant_code VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码' AFTER merchant_id,
    ADD INDEX idx_after_sales_ticket_merchant (merchant_code);

ALTER TABLE chat_session
    ADD COLUMN merchant_id BIGINT NULL COMMENT '所属商家/客服主体ID(sys_user)' AFTER user_id,
    ADD COLUMN merchant_code VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码' AFTER merchant_id,
    ADD INDEX idx_chat_session_merchant (merchant_code);

UPDATE product_info SET merchant_id = 1, merchant_code = 'MERCHANT_DEMO' WHERE merchant_code IS NULL OR merchant_code = '';
UPDATE order_info SET merchant_id = 1, merchant_code = 'MERCHANT_DEMO' WHERE merchant_code IS NULL OR merchant_code = '';
UPDATE after_sales_ticket SET merchant_id = 1, merchant_code = 'MERCHANT_DEMO' WHERE merchant_code IS NULL OR merchant_code = '';
UPDATE chat_session SET merchant_id = 1, merchant_code = 'MERCHANT_DEMO' WHERE merchant_code IS NULL OR merchant_code = '';
