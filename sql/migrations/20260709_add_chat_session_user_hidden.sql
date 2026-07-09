SET @chat_session_user_hidden_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'chat_session'
      AND COLUMN_NAME = 'user_hidden'
);

SET @chat_session_user_hidden_sql = IF(
    @chat_session_user_hidden_exists = 0,
    'ALTER TABLE chat_session ADD COLUMN user_hidden TINYINT NOT NULL DEFAULT 0 COMMENT ''User-side hidden from recent list'' AFTER satisfaction',
    'SELECT ''chat_session.user_hidden already exists'' AS migration_message'
);

PREPARE chat_session_user_hidden_stmt FROM @chat_session_user_hidden_sql;
EXECUTE chat_session_user_hidden_stmt;
DEALLOCATE PREPARE chat_session_user_hidden_stmt;
