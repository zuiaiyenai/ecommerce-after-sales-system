-- Extended PostgreSQL/pgvector knowledge seed for after-sales Agent.
-- Execute against ecommerce_rag. Rebuild knowledge_chunk after this file is applied.

INSERT INTO knowledge_document
    (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status)
VALUES
('after_sales_policy', 'quality_phone_charging_slow_001', 'MERCHANT_DEMO', '手机充电慢质量问题售后规则',
'适用场景：用户反馈手机充电很慢、充不进去电、30分钟只充少量电、充电发热、充电断断续续，并要求退款、退货退款、换货或检测。
处理规则：
1. 用户提交售后申请后先进入待审核状态。
2. 必需信息包括充电器和数据线是否原装、充电时长、充电百分比变化、是否发热、是否更换充电器后仍存在。
3. 商品照片只能证明商品外观，通常无法直接证明充电慢；若用户只上传电量截图或商品照片，AI 不应自动建议通过，应转人工或引导补充视频/检测信息。
4. 若描述清楚且订单允许售后，可创建待审核售后单；是否通过由人工结合检测或进一步证据确认。
5. 明确人为进水、摔落、私拆导致充电异常的，不应建议通过。',
'phone', 'quality_issue', 'refund', 'v1.0', 1),

('after_sales_policy', 'quality_phone_power_reboot_001', 'MERCHANT_DEMO', '手机无法开机重启售后规则',
'适用场景：手机无法开机、频繁重启、死机、黑屏、闪屏、系统卡顿严重等功能异常。
处理规则：
1. 用户应描述异常出现时间、是否充电后仍无法开机、是否摔落进水、是否更新系统后出现。
2. 可要求补充故障视频或开机失败画面；单张静态照片通常无法确认功能异常。
3. 符合售后时效且描述具体时，可创建待审核售后单。
4. AI 不能仅凭静态图片对功能异常建议通过；无法判断时转人工。',
'phone', 'quality_issue', 'refund', 'v1.0', 1),

('after_sales_policy', 'quality_battery_life_001', 'MERCHANT_DEMO', '电池续航异常售后规则',
'适用场景：手机、耳机、数码设备续航明显不足、掉电快、耗电异常、电池充不满。
处理规则：
1. 用户需要提供使用时长、耗电速度、充满电百分比、是否开启高耗电功能等描述。
2. 建议补充电量变化截图或视频，但图片不能直接证明电池质量问题。
3. 新品在售后时效内且描述具体，可创建待审核申请；AI 不直接建议通过，需人工或检测确认。
4. 长期使用后的电池自然损耗、非原装充电器导致异常，需要人工判断。',
'digital', 'quality_issue', 'refund', 'v1.0', 1),

('scene_evidence', 'quality_function_evidence_001', 'MERCHANT_DEMO', '功能类质量问题证据要求',
'功能类质量问题包括充电慢、无法开机、电流声、蓝牙断连、按键失灵、触控异常、续航差等。
必需信息：
1. 具体故障描述，说明何时出现、出现频率、持续时间。
2. 商品整体照片，用于确认商品主体和外观状态。
建议补充：
1. 故障视频、录音、截图或检测结果。
2. 充电/连接/开机类问题可补充操作过程视频。
判断边界：
1. 静态图片无法直接证明功能异常时，不进入自动建议通过。
2. 图片与描述无法核验时，直接转人工处理。
3. 描述过于笼统时，先引导补充故障描述。',
'digital', 'quality_issue', 'evidence_requirement', 'v1.0', 1),

('after_sales_policy', 'wrong_item_policy_001', 'MERCHANT_DEMO', '错发商品售后规则',
'适用场景：用户收到的商品型号、颜色、规格、数量与订单不一致。
处理规则：
1. 用户应提供收到的商品照片、订单商品信息截图或描述、外包装/物流面单照片。
2. 经确认错发后优先支持换货或补发正确商品；用户不接受时可协商退货退款。
3. 只凭文字描述无法确认错发时，应引导上传实收商品照片和订单商品对比信息。
4. 图片无法确认商品或与订单不匹配时，转人工复核。',
'general', 'wrong_item', 'exchange', 'v1.0', 1),

('after_sales_policy', 'missing_item_reissue_001', 'MERCHANT_DEMO', '少发漏发补发规则',
'适用场景：用户反馈少发、漏发、缺少配件、包装内没有某个商品或配件。
处理规则：
1. 用户需提供实收商品整体照片、包装内物品照片、外包装照片。
2. 涉及配件缺失时，需说明缺少的配件名称和数量。
3. 经核实少发漏发后，优先补发；若补发不可行，可按缺失部分协商退款。
4. 无照片或无法确认缺件时，先引导补充材料或转人工。',
'general', 'missing_item', 'reissue', 'v1.0', 1),

('scene_evidence', 'wrong_missing_evidence_001', 'MERCHANT_DEMO', '错发少发证据要求',
'错发少发类证据要求：
1. 实收商品照片，能看清商品、颜色、规格和数量。
2. 外包装照片和物流面单照片，用于确认包裹来源。
3. 订单中应收到的商品或配件说明。
4. 若是缺配件，需拍摄包装盒内所有物品。
判断原则：
1. 材料齐全后可创建待审核售后单。
2. 图片不能确认数量或规格时，转人工复核。
3. 用户只描述“少了”但没有照片时，引导补充照片。',
'general', 'wrong_or_missing_items', 'evidence_requirement', 'v1.0', 1),

('after_sales_policy', 'logistics_signed_not_received_001', 'MERCHANT_DEMO', '显示签收但未收到处理规则',
'适用场景：物流显示已签收，但用户表示没有收到商品。
处理规则：
1. 先查询订单物流状态和签收时间。
2. 引导用户确认收件地址、门卫/驿站/家人代收情况。
3. 需要物流面单或物流轨迹作为核验依据。
4. 此类责任需要物流侧核实，AI 不应直接创建退款建议通过，应转人工或发起物流核查。
5. 若确认丢件，可按商家规则补发或退款。',
'general', 'logistics_issue', 'refund_or_reissue', 'v1.0', 1),

('after_sales_policy', 'package_damage_only_001', 'MERCHANT_DEMO', '外包装破损但商品完好规则',
'适用场景：用户反馈外包装破损、盒子压坏、包装变形，但商品本体暂无明显问题。
处理规则：
1. 需要外包装照片和商品本体照片。
2. 如果商品本体完好且不影响使用，通常不直接支持退货退款，可根据商家政策提供补偿或人工协商。
3. 如果包装破损伴随商品破损，应按商品破损规则处理。
4. 仅凭外包装破损无法自动建议退款通过，需人工确认影响程度。',
'general', 'package_damage', 'compensation_or_review', 'v1.0', 1),

('after_sales_policy', 'refund_only_boundary_001', 'MERCHANT_DEMO', '仅退款适用边界',
'仅退款适用场景：
1. 商品未发货或订单取消。
2. 物流丢件、长时间未收到且经核实无法送达。
3. 少发漏发且只退缺失部分金额。
4. 商品无需退回且商家确认可退款的特殊场景。
不适用场景：
1. 已收到完整商品且要求全额退款，通常应走退货退款。
2. 商品破损或质量问题需要退回检测时，不应直接仅退款。
3. 证据不足时不自动建议仅退款通过。',
'general', 'refund_only', 'refund', 'v1.0', 1),

('after_sales_policy', 'return_shipping_fee_001', 'MERCHANT_DEMO', '退货运费承担规则',
'退货运费承担规则：
1. 质量问题、错发、少发、商品破损且经核实属商家或物流责任的，退货运费通常由商家承担。
2. 7天无理由、个人不喜欢、拍错规格等非质量原因，运费通常由买家承担。
3. 争议场景需人工结合订单、商品类目、物流证据判断。
4. AI 回复时应说明以最终审核结果为准，不承诺具体赔付金额。',
'general', 'return_shipping', 'policy_explanation', 'v1.0', 1),

('faq', 'faq_refund_arrival_time_001', 'MERCHANT_DEMO', '退款多久到账？',
'退款到账时效说明：
1. 审核通过后，退款通常原路退回。
2. 支付渠道处理一般需要1-5个工作日。
3. 退货退款场景通常需要商家收到退回商品并确认无误后再退款。
4. 若超过预计时效仍未到账，可转人工查询支付渠道或订单退款状态。',
'general', 'refund_progress', 'policy_explanation', 'v1.0', 1),

('faq', 'faq_after_sales_progress_001', 'MERCHANT_DEMO', '售后审核多久有结果？',
'售后审核进度说明：
1. 资料齐全的售后申请通常会优先处理。
2. 需要人工复核的场景，例如功能异常、图片无法判断、物流争议、责任不清，一般需要客服进一步核实。
3. 用户可在售后进度入口查看当前状态。
4. 若用户多次催促、情绪强烈或超过承诺时效，应转人工跟进。',
'general', 'progress_query', 'policy_explanation', 'v1.0', 1),

('reply_template', 'template_request_function_detail_001', 'MERCHANT_DEMO', '功能异常补充描述话术',
'当用户只说质量问题、充电慢、电流声、无法开机等但描述不足时，可回复：
为了继续判断售后规则，请补充一下具体异常现象，例如出现时间、持续多久、是否更换充电器/设备后仍存在；如果方便，也可以上传一段故障视频或截图。',
'general', 'quality_issue', 'ask_missing_evidence', 'v1.0', 1),

('reply_template', 'template_request_damage_photo_001', 'MERCHANT_DEMO', '破损照片补充话术',
'当用户描述商品破损但未上传清晰破损照片时，可回复：
已了解您的问题。为了继续判断售后规则，请上传一张能清楚看到破损位置和商品主体的照片；如是刚签收发现破损，也建议补充外包装照片和物流面单照片。',
'general', 'damage', 'ask_missing_evidence', 'v1.0', 1),

('guideline', 'human_handoff_boundary_002', 'MERCHANT_DEMO', '售后自动转人工边界',
'以下情况应自动转人工：
1. 功能类质量问题上传的图片无法核验问题现象。
2. 图片与用户描述不一致。
3. 图片模糊、只拍局部、无法确认商品主体。
4. 涉及物流丢件、签收争议、运费争议、赔偿金额争议。
5. 用户明确要求转人工，或多轮补充后仍无法判断。
6. 知识库没有命中明确政策或证据规则。',
'general', 'human_handoff', 'guardrail', 'v1.0', 1),

('guideline', 'completion_review_invite_001', 'MERCHANT_DEMO', '售后完成后评价邀请规则',
'售后单最终完成后，系统应自动发送评价邀请。
触发条件：
1. 售后状态进入已完成。
2. 人工最终处理完成退款、换货、补发或拒绝后。
3. 同一售后单不重复发送评价邀请。
话术应简短，不影响用户继续查看售后进度。',
'general', 'completion', 'review_invitation', 'v1.0', 1)
ON CONFLICT (source_type, source_code, merchant_code) DO UPDATE SET
    title = EXCLUDED.title,
    content = EXCLUDED.content,
    product_category = EXCLUDED.product_category,
    scene = EXCLUDED.scene,
    intent = EXCLUDED.intent,
    policy_version = EXCLUDED.policy_version,
    status = EXCLUDED.status,
    updated_at = NOW();
