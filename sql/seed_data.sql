-- ============================================================
-- 种子数据 —— 商品、订单、售后工单、会话等初始数据
-- 执行顺序：先执行 schema.sql 建表，再执行本文件插入数据
-- ============================================================

USE ecommerce_aftersales;

-- ============================================================
-- 清理旧数据（重新插入前先删除）
-- ============================================================
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE ticket_log;
TRUNCATE TABLE ticket_attachment;
TRUNCATE TABLE after_sales_ticket;
TRUNCATE TABLE chat_message;
TRUNCATE TABLE chat_session;
TRUNCATE TABLE message_notice;
TRUNCATE TABLE order_item;
TRUNCATE TABLE order_info;
TRUNCATE TABLE product_info;
TRUNCATE TABLE sys_user;
TRUNCATE TABLE user_info;
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================
-- 0. 测试用户（开发阶段使用）
-- ============================================================

INSERT INTO user_info (id, user_account, phone, password, nickname, role_type, status) VALUES
(1, '13397987740', '13397987740', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', 'yyx', 'USER', 1);

INSERT INTO sys_user (id, username, password, real_name, phone, email, role_type, status, online_status, max_sessions) VALUES
(1, 'cs_demo', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '林真', '13800000001', 'cs_demo@example.com', 'AGENT', 1, 1, 8);

-- ============================================================
-- 1. 商品数据（6 个商品）
-- ============================================================

INSERT INTO product_info (id, product_name, product_code, category, description, main_image, images, price, status) VALUES
(1, '纯棉圆领T恤', 'TSHIRT-001', '服装',
 '100%新疆长绒棉，亲肤透气，经典圆领设计，适合日常穿搭。支持机洗，不易变形褪色。',
 '/static/images/product-tshirt.png',
 '["/static/images/product-tshirt.png"]',
 35.00, 1),

(2, '手机', 'PHONE-001', '数码',
 '高性能智能手机，大容量电池，高清屏幕，流畅运行。',
 '/static/images/product-phone.png',
 '["/static/images/product-phone.png"]',
 2999.00, 1),

(3, '相纸', 'PHOTO-001', '日用',
 '高清相纸，6寸规格，40张装，打印效果清晰鲜艳。',
 '/static/images/product-photo-paper.png',
 '["/static/images/product-photo-paper.png"]',
 35.90, 1),

(4, '蓝牙降噪耳机', 'EARPHONE-001', '数码',
 '主动降噪，蓝牙5.3，续航30小时，Type-C快充。支持多设备连接，触控操作。',
 '/static/images/product-earphone.png',
 '["/static/images/product-earphone.png"]',
 129.00, 1),

(5, '运动鞋', 'SHOE-001', '鞋靴',
 '飞织鞋面，轻盈透气，EVA缓震鞋底，适合日常跑步和健身。防滑耐磨橡胶外底。',
 '/static/images/product-shoes.png',
 '["/static/images/product-shoes.png"]',
 199.00, 1);

-- ============================================================
-- 2. 收货地址（给已有用户）
-- ============================================================

-- 注意：user_id 需要替换为实际用户的 ID（登录后从 user_info 表查询）
-- 这里先用占位 ID，执行时请替换
-- INSERT INTO shipping_address (id, user_id, name, phone, province, city, district, detail, is_default) VALUES
-- (1, <你的用户ID>, 'yyx', '13397987740', '北京市', '朝阳区', '三里屯', '三里屯路19号院1号楼2单元301', 1);

-- ============================================================
-- 3. 订单数据（模拟用户已购买的商品）
-- ============================================================

-- 订单1：已收货（可申请售后）
INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, tracking_company, tracking_no, pay_time, ship_time, receive_time) VALUES
(1, 'ORD20240115001', 1, 35.00, 35.00, 'RECEIVED', 'yyx', '13397987740', '北京市朝阳区三里屯路19号院', '顺丰快递', 'SF1234567890', '2024-01-15 14:30:00', '2024-01-16 09:00:00', '2024-01-18 14:00:00');

INSERT INTO order_item (id, order_id, product_id, price, quantity, subtotal) VALUES
(1, 1, 1, 35.00, 1, 35.00);

-- 订单2：已收货（可申请售后）
INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, tracking_company, tracking_no, pay_time, ship_time, receive_time) VALUES
(2, 'ORD20240118001', 1, 2999.00, 2999.00, 'RECEIVED', 'yyx', '13397987740', '北京市朝阳区三里屯路19号院', '中通快递', 'ZT9876543210', '2024-01-18 10:00:00', '2024-01-19 08:00:00', '2024-01-21 16:00:00');

INSERT INTO order_item (id, order_id, product_id, price, quantity, subtotal) VALUES
(2, 2, 2, 2999.00, 1, 2999.00);

-- 订单3：已发货（待收货）
INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, tracking_company, tracking_no, pay_time, ship_time) VALUES
(3, 'ORD20240120001', 1, 35.90, 35.90, 'SHIPPED', 'yyx', '13397987740', '北京市朝阳区三里屯路19号院', '圆通快递', 'YT1122334455', '2024-01-20 09:00:00', '2024-01-21 10:00:00');

INSERT INTO order_item (id, order_id, product_id, price, quantity, subtotal) VALUES
(3, 3, 3, 35.90, 1, 35.90);

-- 订单4：已付款（待发货）
INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, pay_time) VALUES
(4, 'ORD20240122001', 1, 328.00, 328.00, 'PAID', 'yyx', '13397987740', '北京市朝阳区三里屯路19号院', '2024-01-22 20:00:00');

INSERT INTO order_item (id, order_id, product_id, price, quantity, subtotal) VALUES
(4, 4, 4, 129.00, 1, 129.00),
(5, 4, 5, 199.00, 1, 199.00);

-- 订单5：已收货
INSERT INTO order_info (id, order_no, user_id, total_amount, pay_amount, status, receiver_name, receiver_phone, receiver_address, tracking_company, tracking_no, pay_time, ship_time, receive_time) VALUES
(5, 'ORD20240125001', 1, 199.00, 199.00, 'RECEIVED', 'yyx', '13397987740', '北京市朝阳区三里屯路19号院', '韵达快递', 'YD6677889900', '2024-01-25 15:00:00', '2024-01-26 09:00:00', '2024-01-28 11:00:00');

INSERT INTO order_item (id, order_id, product_id, price, quantity, subtotal) VALUES
(6, 5, 5, 199.00, 1, 199.00);

-- ============================================================
-- 4. 售后工单数据（模拟已有售后记录）
-- ============================================================

-- 工单1：处理中（质量问题）
INSERT INTO after_sales_ticket (id, ticket_no, order_id, order_no, user_id, product_name, reason, description, ai_recommend_type, status, priority) VALUES
(1, 'AS20240120001', 1, 'ORD20240115001', 1, '纯棉圆领T恤', 'QUALITY', '收到的衣服领口有明显的线头脱线，穿了一次就开裂了', 'REFUND_RETURN', 'PROCESSING', 1);

INSERT INTO ticket_attachment (id, ticket_id, file_url, file_type, file_name, sort_order) VALUES
(1, 1, '/static/images/product-tshirt.png', 'IMAGE', 'T恤照片.jpg', 0);

INSERT INTO ticket_log (id, ticket_id, operator_id, operator_type, from_status, to_status, action, content) VALUES
(1, 1, NULL, 'USER', NULL, 'PENDING', 'SUBMIT', '用户提交售后申请'),
(2, 1, NULL, 'AI', 'PENDING', 'PROCESSING', 'AI_CLASSIFY', 'AI识别为质量问题，推荐退货退款，置信度0.92');

-- 工单2：已通过（手机问题）
INSERT INTO after_sales_ticket (id, ticket_no, order_id, order_no, user_id, product_name, after_sale_type, reason, description, ai_recommend_type, ai_confidence, status, priority, audit_opinion, audit_time) VALUES
(2, 'AS20240122001', 2, 'ORD20240118001', 1, '手机', 'REFUND_RETURN', 'QUALITY', '手机屏幕有划痕，疑似二手翻新', 'EXCHANGE', 0.85, 'APPROVED', 0, '同意换货，请将商品寄回', '2024-01-23 10:00:00');

INSERT INTO ticket_log (id, ticket_id, operator_id, operator_type, from_status, to_status, action, content) VALUES
(3, 2, NULL, 'USER', NULL, 'PENDING', 'SUBMIT', '用户提交售后申请'),
(4, 2, NULL, 'AI', 'PENDING', 'PROCESSING', 'AI_CLASSIFY', 'AI识别为质量问题，推荐换货，置信度0.85'),
(5, 2, 1, 'AGENT', 'PROCESSING', 'APPROVED', 'APPROVE', '同意换货，请将商品寄回');

-- 工单3：已完成（物流损坏）
INSERT INTO after_sales_ticket (id, ticket_no, order_id, order_no, user_id, product_name, after_sale_type, reason, description, ai_recommend_type, ai_confidence, status, priority, refund_amount, audit_opinion, audit_time, complete_time) VALUES
(3, 'AS20240125001', 5, 'ORD20240125001', 1, '运动鞋', 'REFUND_ONLY', 'DAMAGE', '收到时包装被压扁，鞋面有污渍', 'REFUND_ONLY', 0.95, 'COMPLETED', 1, 199.00, '确认物流损坏，全额退款', '2024-01-26 09:00:00', '2024-01-27 14:00:00');

INSERT INTO ticket_attachment (id, ticket_id, file_url, file_type, file_name, sort_order) VALUES
(3, 3, '/static/images/product-shoes.png', 'IMAGE', '鞋子照片.jpg', 0);

INSERT INTO ticket_log (id, ticket_id, operator_id, operator_type, from_status, to_status, action, content) VALUES
(6, 3, NULL, 'USER', NULL, 'PENDING', 'SUBMIT', '用户提交售后申请'),
(7, 3, NULL, 'AI', 'PENDING', 'PROCESSING', 'AI_CLASSIFY', 'AI识别为物流损坏，推荐仅退款，置信度0.95'),
(8, 3, 1, 'AGENT', 'PROCESSING', 'APPROVED', 'APPROVE', '确认物流损坏，全额退款'),
(9, 3, NULL, 'SYSTEM', 'APPROVED', 'COMPLETED', 'AUTO_REFUND', '退款199.00元已原路返回');

-- ============================================================
-- 5. 商家客服端会话与通知数据
-- ============================================================

INSERT INTO chat_session (id, session_no, user_id, order_id, ticket_id, human_agent_id, mode, status, emotion_score, emotion_label, user_query, resolved, satisfaction) VALUES
(101, 'CS20260625007', 1, 1, 1, 1, 'HUMAN', 'ACTIVE', 0.35, 'ANXIETY', '退款进度咨询', 0, NULL),
(102, 'CS20260625008', 1, 2, 2, 1, 'HUMAN', 'WAITING', 0.55, 'NORMAL', '换货物流异常', 0, NULL),
(103, 'CS20260625009', 1, 5, 3, 1, 'HUMAN', 'CLOSED', 0.90, 'NORMAL', '服务评价已完成', 1, 5);

INSERT INTO chat_message (id, session_id, role, content, message_type, emotion_label) VALUES
(1, 101, 'USER', '我的退款什么时候能到账？', 'TEXT', 'ANXIETY'),
(2, 101, 'ASSISTANT', '您好，我已经帮您核对退款进度，目前工单正在处理中。', 'TEXT', 'NORMAL'),
(3, 102, 'USER', '换货包裹三天没有更新了。', 'TEXT', 'NORMAL'),
(4, 103, 'SYSTEM', '用户已完成服务评价。', 'TEXT', 'NORMAL');

INSERT INTO message_notice (id, user_id, title, content, notice_type, ref_id, ref_type, is_read) VALUES
(1, 1, '退款工单待审核', 'AS20240120001 需要客服继续处理。', 'AFTER_SALE', 1, 'TICKET', 0),
(2, 1, '新会话待接入', 'CS20260625008 等待客服接入。', 'CHAT', 102, 'SESSION', 0),
(3, 1, '订单核验提醒', 'ORD20240118001 关联售后工单已更新。', 'ORDER', 2, 'ORDER', 1);
