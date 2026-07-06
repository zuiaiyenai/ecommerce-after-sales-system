ALTER TABLE after_sales_ticket
    ADD COLUMN policy_code VARCHAR(64) NULL COMMENT '命中的商家策略编码' AFTER merchant_code,
    ADD COLUMN policy_version VARCHAR(32) NULL COMMENT '命中的商家策略版本' AFTER policy_code;

ALTER TABLE chat_session
    ADD COLUMN policy_code VARCHAR(64) NULL COMMENT '命中的商家策略编码' AFTER merchant_code,
    ADD COLUMN policy_version VARCHAR(32) NULL COMMENT '命中的商家策略版本' AFTER policy_code,
    ADD COLUMN emotion_confidence DECIMAL(3,2) NULL COMMENT '用户情绪判断置信度(0~1)' AFTER emotion_score;

ALTER TABLE chat_message
    ADD COLUMN emotion_confidence DECIMAL(3,2) NULL COMMENT '该条消息情绪判断置信度(0~1)' AFTER emotion_score;
