-- ============================================================
-- 客服账号种子数据
-- 密码: 123456 (BCrypt加密)
-- 在 MySQL 中执行: source sql/staff_seed.sql
-- ============================================================

USE ecommerce_aftersales;

INSERT INTO sys_user (id, username, password, real_name, phone, email, role_type, status, online_status, max_sessions, merchant_code) VALUES
(1, 'cs_demo', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '林真', '13800000001', 'cs_demo@example.com', 'AGENT', 1, 1, 8, 'MERCHANT_DEMO');
