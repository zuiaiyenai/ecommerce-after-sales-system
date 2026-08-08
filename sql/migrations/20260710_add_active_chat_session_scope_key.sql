-- Enforce one active conversation for a user and the same business entry.
-- Keep the newest active session; older duplicates are retained as closed history.
UPDATE chat_session older
JOIN chat_session newer
  ON newer.user_id = older.user_id
 AND newer.merchant_code = older.merchant_code
 AND COALESCE(newer.order_id, 0) = COALESCE(older.order_id, 0)
 AND COALESCE(newer.ticket_id, 0) = COALESCE(older.ticket_id, 0)
 AND newer.deleted = 0
 AND newer.status <> 'CLOSED'
 AND (newer.update_time > older.update_time
      OR (newer.update_time = older.update_time AND newer.id > older.id))
SET older.status = 'CLOSED',
    older.close_time = COALESCE(older.close_time, NOW()),
    older.update_time = NOW()
WHERE older.deleted = 0
  AND older.status <> 'CLOSED';

-- Closed/deleted sessions return NULL and therefore remain historically retained.
ALTER TABLE chat_session
    ADD COLUMN active_scope_key VARCHAR(255)
        GENERATED ALWAYS AS (
            CASE
                WHEN deleted = 0 AND status <> 'CLOSED' THEN CONCAT(
                    user_id, ':', merchant_code, ':', COALESCE(order_id, 0), ':', COALESCE(ticket_id, 0)
                )
                ELSE NULL
            END
        ) STORED,
    ADD UNIQUE KEY uk_chat_session_active_scope (active_scope_key),
    ADD INDEX idx_chat_session_reuse_lookup (user_id, merchant_code, order_id, ticket_id, status, update_time);
