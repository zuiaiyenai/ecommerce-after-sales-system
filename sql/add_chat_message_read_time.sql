ALTER TABLE chat_message
    ADD COLUMN read_time DATETIME NULL COMMENT '客服端阅读时间，NULL表示未读'
    AFTER token_usage;
