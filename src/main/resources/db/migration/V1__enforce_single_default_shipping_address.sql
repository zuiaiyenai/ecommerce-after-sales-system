UPDATE shipping_address address_to_clear
JOIN (
    SELECT user_id, MIN(id) AS keep_id
    FROM shipping_address
    WHERE is_default = 1 AND deleted = 0
    GROUP BY user_id
    HAVING COUNT(*) > 1
) duplicate_default ON duplicate_default.user_id = address_to_clear.user_id
SET address_to_clear.is_default = 0
WHERE address_to_clear.is_default = 1
  AND address_to_clear.deleted = 0
  AND address_to_clear.id <> duplicate_default.keep_id;

ALTER TABLE shipping_address
    ADD COLUMN default_user_id BIGINT GENERATED ALWAYS AS (
        CASE WHEN is_default = 1 AND deleted = 0 THEN user_id ELSE NULL END
    ) STORED COMMENT '当前有效默认地址的用户ID',
    ADD UNIQUE KEY uk_shipping_address_default_user (default_user_id);
