-- Supports cursor-based chat history pagination: session_id + message id.
ALTER TABLE chat_message
    ADD INDEX idx_chat_message_session_id (session_id, id);
