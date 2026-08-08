ALTER TABLE chat_session
    MODIFY COLUMN emotion_score DECIMAL(3,2) NULL
        COMMENT '用户情绪负面强度分值(0~1，越高越负面)',
    MODIFY COLUMN emotion_confidence DECIMAL(3,2) NULL
        COMMENT '用户情绪判断置信度(0~1)';

ALTER TABLE chat_message
    MODIFY COLUMN emotion_score DECIMAL(3,2) NULL
        COMMENT '该条消息情绪负面强度分值(0~1，越高越负面)',
    MODIFY COLUMN emotion_confidence DECIMAL(3,2) NULL
        COMMENT '该条消息情绪判断置信度(0~1)';
