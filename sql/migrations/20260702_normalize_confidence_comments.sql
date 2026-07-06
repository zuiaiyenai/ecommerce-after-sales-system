ALTER TABLE after_sales_ticket
    MODIFY COLUMN ai_confidence DECIMAL(3,2) NULL COMMENT 'AI工单分类置信度(0~1，表示售后类型/处理路由分类把握度)';

ALTER TABLE chat_message
    MODIFY COLUMN confidence DECIMAL(3,2) NULL COMMENT 'AI回复置信度(0~1，表示回复生成/选用把握度)';

ALTER TABLE chat_session
    MODIFY COLUMN emotion_confidence DECIMAL(3,2) NULL COMMENT '用户情绪判断置信度(0~1)';

ALTER TABLE chat_message
    MODIFY COLUMN emotion_confidence DECIMAL(3,2) NULL COMMENT '该条消息情绪判断置信度(0~1)';
