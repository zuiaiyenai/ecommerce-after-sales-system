ALTER TABLE chat_message
    ADD COLUMN file_url VARCHAR(500) NULL COMMENT '图片/文件消息访问地址' AFTER message_type;
