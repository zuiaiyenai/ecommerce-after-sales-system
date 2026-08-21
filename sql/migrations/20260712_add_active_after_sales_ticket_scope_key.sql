-- Enforce one active after-sales ticket per user and order.
-- Keep the newest active ticket; older duplicates are retained as closed history.
UPDATE after_sales_ticket older
JOIN after_sales_ticket newer
  ON newer.user_id = older.user_id
 AND newer.order_id = older.order_id
 AND newer.deleted = 0
 AND newer.status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING')
 AND (newer.update_time > older.update_time
      OR (newer.update_time = older.update_time AND newer.id > older.id))
SET older.status = 'CLOSED',
    older.audit_opinion = CASE
        WHEN older.audit_opinion IS NULL OR older.audit_opinion = '' THEN 'Closed automatically during duplicate ticket cleanup.'
        ELSE CONCAT(older.audit_opinion, ' | Closed automatically during duplicate ticket cleanup.')
    END,
    older.update_time = NOW()
WHERE older.deleted = 0
  AND older.status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING');

ALTER TABLE after_sales_ticket
    ADD COLUMN active_scope_key VARCHAR(128)
        GENERATED ALWAYS AS (
            CASE
                WHEN deleted = 0 AND status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING')
                    THEN CONCAT(user_id, ':', order_id)
                ELSE NULL
            END
        ) STORED,
    ADD UNIQUE KEY uk_after_sales_ticket_active_scope (active_scope_key),
    ADD INDEX idx_after_sales_ticket_reuse_lookup (user_id, order_id, status, update_time);
