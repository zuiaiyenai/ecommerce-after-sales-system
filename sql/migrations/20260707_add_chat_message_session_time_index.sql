ALTER TABLE chat_message
    ADD INDEX idx_chat_message_session_time (session_id, create_time);
