-- ============================================================
-- 种子数据 —— 商品目录 + 默认商家客服账号
-- 执行顺序：先执行 schema.sql，再执行本文件
-- ============================================================

USE ecommerce_aftersales;

-- ============================================================
-- 默认商家客服账号
-- 登录账号：cs_demo
-- 登录密码：123456
-- 商家编码：MERCHANT_DEMO
-- ============================================================

INSERT INTO sys_user (id, username, password, real_name, phone, email, role_type, status, online_status, max_sessions, merchant_code) VALUES
(1, 'cs_demo', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '林真', '13800000001', 'cs_demo@example.com', 'AGENT', 1, 1, 8, 'MERCHANT_DEMO');

-- ============================================================
-- 商品数据（5 个商品，供小程序商城使用）
-- ============================================================

INSERT INTO product_info (id, product_name, product_code, category, description, main_image, images, price, status, merchant_code) VALUES
(1, '纯棉圆领T恤', 'TSHIRT-001', '服装',
 '100%新疆长绒棉，亲肤透气，经典圆领设计，适合日常穿搭。支持机洗，不易变形褪色。',
 '/static/images/product-tshirt.png',
 '["/static/images/product-tshirt.png"]',
 35.00, 1, 'MERCHANT_DEMO'),

(2, '手机', 'PHONE-001', '数码',
 '高性能智能手机，大容量电池，高清屏幕，流畅运行。',
 '/static/images/product-phone.png',
 '["/static/images/product-phone.png"]',
 2999.00, 1, 'MERCHANT_DEMO'),

(3, '相纸', 'PHOTO-001', '日用',
 '高清相纸，6寸规格，40张装，打印效果清晰鲜艳。',
 '/static/images/product-photo-paper.png',
 '["/static/images/product-photo-paper.png"]',
 35.90, 1, 'MERCHANT_DEMO'),

(4, '蓝牙降噪耳机', 'EARPHONE-001', '数码',
 '主动降噪，蓝牙5.3，续航30小时，Type-C快充。支持多设备连接，触控操作。',
 '/static/images/product-earphone.png',
 '["/static/images/product-earphone.png"]',
 129.00, 1, 'MERCHANT_DEMO'),

(5, '运动鞋', 'SHOE-001', '鞋靴',
 '飞织鞋面，轻盈透气，EVA缓震鞋底，适合日常跑步和健身。防滑耐磨橡胶外底。',
 '/static/images/product-shoes.png',
 '["/static/images/product-shoes.png"]',
 199.00, 1, 'MERCHANT_DEMO');
