-- Base PostgreSQL/pgvector knowledge seed for the after-sales RAG database.
-- Execute against ecommerce_rag after sql/pgvector_schema.sql.

INSERT INTO knowledge_document
    (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status)
VALUES
('after_sales_policy', 'damage_policy_001', 'MERCHANT_DEMO', '商品破损售后政策',
$$适用范围：签收后发现商品外壳破裂、裂纹、碎屏、断裂、明显磕碰等物理破损。
处理规则：
1. 用户应在签收后7天内提交售后申请。
2. 必须提供清晰的破损部位照片，能看清破损位置、范围和商品主体。
3. 建议补充外包装照片和物流面单，用于判断是否属于运输破损。
4. 经核实属于签收即破损或运输破损的，支持退货退款或换货。
5. 图片模糊、只拍局部无法确认商品、描述与图片不一致、疑似人为损坏时，应转人工复核。
6. 最终退款、换货或拒绝由人工客服结合订单和证据确认。$$,
'digital', 'damage', 'refund', 'v1.0', 1),

('after_sales_policy', 'quality_issue_001', 'MERCHANT_DEMO', '质量问题售后政策',
$$适用范围：商品存在功能缺陷、性能不达标、电流声、异响、无法充电、无法开机、连接不稳定等质量问题。
处理规则：
1. 用户应描述具体故障现象、出现时间、频率、是否更换设备或配件后仍存在。
2. 建议提供商品整体照片；声音、连接、开机、充电等功能问题可补充视频、录音或检测截图。
3. 售后时效内且描述具体的，可以先创建待审核售后单。
4. 功能类问题通常不能仅凭静态照片自动判定通过，证据不足时应引导补充材料或转人工。
5. 明确人为进水、摔落、私拆导致的异常，不应建议通过。$$,
'digital', 'quality_issue', 'refund', 'v1.0', 1),

('after_sales_policy', 'return_policy_001', 'MERCHANT_DEMO', '退货退款基本政策',
$$退货退款规则：
1. 7天无理由退货要求商品未使用、包装和配件完整、不影响二次销售。
2. 破损或质量问题退货需提供照片、视频或明确故障描述。
3. 退款金额通常以商品实际支付金额为准，运费承担以责任归属为准。
4. 退货退款一般在商家收到退回商品并确认无误后，按原支付渠道退款。
5. 退回商品前应保留完整包装、配件、赠品和购买凭证。
6. 证据不足或责任不清时，不应承诺直接退款，应转人工或引导补充材料。$$,
'general', 'return', 'refund', 'v1.0', 1),

('after_sales_policy', 'exchange_policy_001', 'MERCHANT_DEMO', '换货政策',
$$适用情况：商品破损、质量问题、收到错误商品、商品缺件或漏发配件。
处理流程：
1. 用户提交换货申请并上传证明材料。
2. 审核通过后寄回旧商品或确认漏发事实。
3. 商家收到旧商品或确认问题后发出新商品或补发配件。
4. 质量问题、错发、漏发通常由商家承担往返运费；个人原因通常由买家承担。
5. 同一商品多次换货或责任争议场景应转人工处理。$$,
'general', 'exchange', 'exchange', 'v1.0', 1),

('faq', 'faq_damage_evidence', 'MERCHANT_DEMO', '破损商品需要提供什么证据',
$$破损类售后建议提供：
1. 破损部位特写照片，能看清裂纹、断裂、磕碰等细节。
2. 商品整体照片，能确认商品主体和破损位置。
3. 外包装照片，如果外包装也有破损建议一并上传。
4. 物流面单照片，用于确认签收和包裹来源。
拍摄建议：光线充足、对焦清晰、多角度拍摄；如果破损较小，可用手指或标记指出位置。$$,
'digital', 'damage', 'evidence_requirement', 'v1.0', 1),

('faq', 'faq_quality_evidence', 'MERCHANT_DEMO', '质量问题需要提供什么证据',
$$质量问题应尽量补充以下信息：
1. 具体故障现象，例如无法开机、充电慢、电流声、连接断开、按键失灵。
2. 故障出现时间、持续时间、复现频率。
3. 商品整体照片，用于确认商品状态。
4. 功能类问题建议提供视频、录音、截图或检测结果。
5. 充电、连接类问题建议说明是否使用原装充电器、数据线或是否更换设备测试。$$,
'digital', 'quality_issue', 'evidence_requirement', 'v1.0', 1),

('product_knowledge', 'product_headphone_common', 'MERCHANT_DEMO', '蓝牙耳机常见质量问题',
$$蓝牙耳机常见质量判断：
1. 新品外壳破裂、充电盒裂纹、明显磕碰，通常按破损售后处理。
2. 开机后持续存在电流声、杂音、单边无声，可能属于质量问题。
3. 10米内频繁断连、无法搜索设备、配对失败，可能属于连接质量问题。
4. 新品续航明显低于标称、充不满电、充电异常发热，可能属于电池或充电问题。
5. 单个音源或单首歌曲出现杂音，可能是音源问题，需要进一步排查。
6. 证据无法证明功能异常时，应引导补充视频或转人工。$$,
'headphone', 'quality_issue', 'quality_standard', 'v1.0', 1),

('guideline', 'guideline_photo_tips', 'MERCHANT_DEMO', '售后照片拍摄指南',
$$售后照片拍摄要求：
1. 拍商品问题位置特写，例如破损、裂纹、缺件、故障部位。
2. 拍商品整体照片，确保能识别商品主体。
3. 如涉及运输责任，补充外包装和物流面单照片。
4. 光线充足、对焦清晰，避免过暗、模糊、遮挡。
5. 多角度拍摄，至少2到3张；小破损可用手指或标记指出位置。
6. 只拍局部且无法识别商品、图片模糊、描述和图片不一致时，需要补充材料或转人工。$$,
'general', 'evidence_requirement', 'guideline', 'v1.0', 1)
ON CONFLICT (source_type, source_code, merchant_code) DO UPDATE SET
    title = EXCLUDED.title,
    content = EXCLUDED.content,
    product_category = EXCLUDED.product_category,
    scene = EXCLUDED.scene,
    intent = EXCLUDED.intent,
    policy_version = EXCLUDED.policy_version,
    status = EXCLUDED.status,
    updated_at = NOW();
