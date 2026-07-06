package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.entity.AfterSalesPolicy;
import com.ecommerce.aftersales.entity.AfterSalesSchemeKnowledge;
import com.ecommerce.aftersales.entity.EmotionLevelKnowledge;
import com.ecommerce.aftersales.entity.EmotionKeywordKnowledge;
import com.ecommerce.aftersales.entity.EmotionStrategyKnowledge;
import com.ecommerce.aftersales.entity.Faq;
import com.ecommerce.aftersales.entity.ProductKnowledge;
import com.ecommerce.aftersales.entity.ReplyTemplateKnowledge;
import com.ecommerce.aftersales.entity.ReviewInterpretationKnowledge;
import com.ecommerce.aftersales.entity.SceneEvidenceKnowledge;
import com.ecommerce.aftersales.mapper.AfterSalesPolicyMapper;
import com.ecommerce.aftersales.mapper.AfterSalesSchemeKnowledgeMapper;
import com.ecommerce.aftersales.mapper.EmotionLevelKnowledgeMapper;
import com.ecommerce.aftersales.mapper.EmotionKeywordKnowledgeMapper;
import com.ecommerce.aftersales.mapper.EmotionStrategyKnowledgeMapper;
import com.ecommerce.aftersales.mapper.FaqMapper;
import com.ecommerce.aftersales.mapper.ProductKnowledgeMapper;
import com.ecommerce.aftersales.mapper.ReplyTemplateKnowledgeMapper;
import com.ecommerce.aftersales.mapper.ReviewInterpretationKnowledgeMapper;
import com.ecommerce.aftersales.mapper.SceneEvidenceKnowledgeMapper;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class ResourceAgentPolicyCatalogService implements AgentPolicyCatalogService {

    private static final String RESOURCE_NAME = "after-sales-policy-catalog.json";
    private static final String KNOWLEDGE_BASE_RESOURCE_NAME = "agent-knowledge-base/policy-knowledge-base.json";
    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";
    private static final String OVERRIDE_FILE = "data/agent-policy-overrides.json";
    private static final TypeReference<LinkedHashMap<String, Object>> MAP_TYPE =
            new TypeReference<>() {};
    private static final TypeReference<LinkedHashMap<String, LinkedHashMap<String, Object>>> OVERRIDE_TYPE =
            new TypeReference<>() {};

    private final ObjectMapper objectMapper;
    private final EmotionLevelKnowledgeMapper emotionLevelKnowledgeMapper;
    private final EmotionKeywordKnowledgeMapper emotionKeywordKnowledgeMapper;
    private final EmotionStrategyKnowledgeMapper emotionStrategyKnowledgeMapper;
    private final AfterSalesSchemeKnowledgeMapper afterSalesSchemeKnowledgeMapper;
    private final SceneEvidenceKnowledgeMapper sceneEvidenceKnowledgeMapper;
    private final FaqMapper faqMapper;
    private final ProductKnowledgeMapper productKnowledgeMapper;
    private final AfterSalesPolicyMapper afterSalesPolicyMapper;
    private final ReplyTemplateKnowledgeMapper replyTemplateKnowledgeMapper;
    private final ReviewInterpretationKnowledgeMapper reviewInterpretationKnowledgeMapper;

    private volatile Map<String, Object> cachedBaseCatalog;
    private volatile Map<String, Object> cachedKnowledgeBase;
    private volatile LinkedHashMap<String, LinkedHashMap<String, Object>> cachedOverrides;

    @Override
    public Map<String, Object> getCatalog() {
        Map<String, Object> catalog = effectiveCatalog();
        catalog.put("knowledge_base", deepCopy(loadKnowledgeBase()));
        return catalog;
    }

    @Override
    public Map<String, Object> getKnowledgeBase() {
        return deepCopy(loadKnowledgeBase());
    }

    @Override
    public Map<String, Object> resolvePolicy(AgentGatewayDtos.PolicyResolveRequest request) {
        String merchantCode = normalizeMerchantCode(request.getMerchantCode());
        Map<String, Object> catalog = effectiveCatalog();
        Map<String, Object> servicePolicy = findServicePolicy(catalog, merchantCode);

        Map<String, Object> payload = basePayload(catalog, merchantCode, servicePolicy);
        payload.put("resolve_context", Map.of(
                "merchant_code", merchantCode,
                "product_category", Optional.ofNullable(request.getProductCategory()).orElse(""),
                "order_status", Optional.ofNullable(request.getOrderStatus()).orElse(""),
                "after_sales_status", Optional.ofNullable(request.getAfterSalesStatus()).orElse(""),
                "message_scene", Optional.ofNullable(request.getMessageScene()).orElse("")
        ));
        return payload;
    }

    @Override
    public Map<String, Object> getMerchantPolicy(String merchantCode) {
        String normalizedMerchantCode = normalizeMerchantCode(merchantCode);
        Map<String, Object> catalog = effectiveCatalog();
        Map<String, Object> servicePolicy = findServicePolicy(catalog, normalizedMerchantCode);

        Map<String, Object> payload = basePayload(catalog, normalizedMerchantCode, servicePolicy);
        payload.put("config_scope", "merchant_editable");
        return payload;
    }

    @Override
    public Map<String, Object> updateMerchantPolicy(
            String merchantCode,
            AgentGatewayDtos.PolicyConfigUpdateRequest request
    ) {
        String normalizedMerchantCode = normalizeMerchantCode(merchantCode);
        validateUpdateRequest(request);

        synchronized (this) {
            LinkedHashMap<String, LinkedHashMap<String, Object>> overrides = loadOverrides();
            LinkedHashMap<String, Object> merchantOverride = deepCopyMap(overrides.get(normalizedMerchantCode));
            if (merchantOverride == null) {
                merchantOverride = new LinkedHashMap<>();
            }

            merchantOverride.put("merchant_code", normalizedMerchantCode);
            merchantOverride.put("merchant_type", request.getProductCode().trim());
            merchantOverride.put("policy_version", "custom-" + DateTimeFormatter.ofPattern("yyyyMMddHHmmss").format(LocalDateTime.now()));

            LinkedHashMap<String, Object> riskPolicy = mutableNestedMap(merchantOverride, "risk_policy");
            riskPolicy.put("auto_refund_limit", request.getAutoRefundLimit());

            LinkedHashMap<String, Object> handoffPolicy = mutableNestedMap(merchantOverride, "handoff_policy");
            handoffPolicy.put("emotion_handoff_min_level", request.getEmotionHandoffMinLevel().trim().toLowerCase());

            overrides.put(normalizedMerchantCode, merchantOverride);
            persistOverrides(overrides);
        }

        return getMerchantPolicy(normalizedMerchantCode);
    }

    private Map<String, Object> effectiveCatalog() {
        Map<String, Object> catalog = deepCopy(loadBaseCatalog());
        Map<String, Object> merchants = mutableMap(catalog.get("merchants"));
        LinkedHashMap<String, LinkedHashMap<String, Object>> overrides = loadOverrides();

        for (Map.Entry<String, LinkedHashMap<String, Object>> entry : overrides.entrySet()) {
            String merchantCode = entry.getKey();
            Map<String, Object> basePolicy = findBaseMerchantPolicy(loadBaseCatalog(), merchantCode);
            LinkedHashMap<String, Object> mergedPolicy = deepCopyMap(basePolicy);
            mergeInto(mergedPolicy, entry.getValue());
            merchants.put(merchantCode, mergedPolicy);
        }

        catalog.put("merchants", merchants);
        return catalog;
    }

    private Map<String, Object> basePayload(
            Map<String, Object> catalog,
            String merchantCode,
            Map<String, Object> servicePolicy
    ) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("catalog_version", catalog.getOrDefault("catalog_version", ""));
        payload.put("source", "springboot_resource_catalog");
        payload.put("service_policy", mergeServicePolicy(catalog, servicePolicy));
        payload.put("merchant_code", merchantCode);
        payload.put("knowledge_base", deepCopy(loadKnowledgeBase()));
        return payload;
    }

    private Map<String, Object> findServicePolicy(Map<String, Object> catalog, String merchantCode) {
        Map<String, Object> merchants = asMap(catalog.get("merchants"));
        Map<String, Object> servicePolicy = asMap(
                merchants.getOrDefault(merchantCode, merchants.get(DEFAULT_MERCHANT_CODE))
        );
        if (servicePolicy.isEmpty()) {
            throw new BizException(500, "default after-sales policy not found");
        }
        return servicePolicy;
    }

    private Map<String, Object> findBaseMerchantPolicy(Map<String, Object> catalog, String merchantCode) {
        Map<String, Object> merchants = asMap(catalog.get("merchants"));
        Map<String, Object> servicePolicy = asMap(
                merchants.getOrDefault(merchantCode, merchants.get(DEFAULT_MERCHANT_CODE))
        );
        if (servicePolicy.isEmpty()) {
            throw new BizException(500, "default after-sales policy not found");
        }
        return servicePolicy;
    }

    private Map<String, Object> loadBaseCatalog() {
        Map<String, Object> local = cachedBaseCatalog;
        if (local != null) {
            return local;
        }
        synchronized (this) {
            if (cachedBaseCatalog != null) {
                return cachedBaseCatalog;
            }
            cachedBaseCatalog = readCatalog();
            return cachedBaseCatalog;
        }
    }

    private Map<String, Object> loadKnowledgeBase() {
        Map<String, Object> local = cachedKnowledgeBase;
        if (local != null) {
            return local;
        }
        synchronized (this) {
            if (cachedKnowledgeBase != null) {
                return cachedKnowledgeBase;
            }
            Map<String, Object> fallbackKnowledgeBase = readJsonResource(KNOWLEDGE_BASE_RESOURCE_NAME);
            cachedKnowledgeBase = mergeKnowledgeBaseFromDatabase(fallbackKnowledgeBase);
            return cachedKnowledgeBase;
        }
    }

    private LinkedHashMap<String, LinkedHashMap<String, Object>> loadOverrides() {
        LinkedHashMap<String, LinkedHashMap<String, Object>> local = cachedOverrides;
        if (local != null) {
            return local;
        }
        synchronized (this) {
            if (cachedOverrides != null) {
                return cachedOverrides;
            }
            cachedOverrides = readOverrides();
            return cachedOverrides;
        }
    }

    private Map<String, Object> readCatalog() {
        return readJsonResource(RESOURCE_NAME);
    }

    private Map<String, Object> readJsonResource(String resourceName) {
        ClassPathResource resource = new ClassPathResource(resourceName);
        if (!resource.exists()) {
            throw new BizException(500, "missing after-sales knowledge resource: " + resourceName);
        }
        try (InputStream inputStream = resource.getInputStream()) {
            return objectMapper.readValue(inputStream, MAP_TYPE);
        } catch (IOException exception) {
            throw new BizException(500, "failed to read after-sales knowledge resource: " + exception.getMessage());
        }
    }

    private LinkedHashMap<String, LinkedHashMap<String, Object>> readOverrides() {
        Path path = Paths.get(OVERRIDE_FILE);
        if (!Files.exists(path)) {
            return new LinkedHashMap<>();
        }
        try (InputStream inputStream = Files.newInputStream(path)) {
            return objectMapper.readValue(inputStream, OVERRIDE_TYPE);
        } catch (IOException exception) {
            throw new BizException(500, "failed to read agent policy overrides: " + exception.getMessage());
        }
    }

    private Map<String, Object> mergeKnowledgeBaseFromDatabase(Map<String, Object> fallbackKnowledgeBase) {
        Map<String, Object> knowledgeBase = deepCopy(fallbackKnowledgeBase);

        try {
            var emotionLevels = emotionLevelKnowledgeMapper.selectList(
                    Wrappers.<EmotionLevelKnowledge>lambdaQuery()
                            .eq(EmotionLevelKnowledge::getStatus, 1)
                            .orderByAsc(EmotionLevelKnowledge::getRankOrder, EmotionLevelKnowledge::getId)
            );
            if (!emotionLevels.isEmpty()) {
                knowledgeBase.put("emotion_levels", emotionLevels.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("code", item.getCode());
                    row.put("label", item.getLabel());
                    row.put("rank", item.getRankOrder());
                    row.put("meaning", item.getMeaning());
                    row.put("handling_advice", item.getHandlingAdvice());
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var emotionKeywords = emotionKeywordKnowledgeMapper.selectList(
                    Wrappers.<EmotionKeywordKnowledge>lambdaQuery()
                            .eq(EmotionKeywordKnowledge::getStatus, 1)
                            .orderByAsc(EmotionKeywordKnowledge::getId)
            );
            if (!emotionKeywords.isEmpty()) {
                knowledgeBase.put("emotion_keyword_knowledge", emotionKeywords.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("group_code", item.getGroupCode());
                    row.put("label", item.getGroupLabel());
                    row.put("emotion", item.getEmotionCode());
                    row.put("source_scope", item.getSourceScope());
                    row.put("trigger_code", item.getTriggerCode());
                    row.put("keywords", parseStringArray(item.getKeywordsJson()));
                    row.put("hit_score", item.getHitScore());
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var emotionStrategies = emotionStrategyKnowledgeMapper.selectList(
                    Wrappers.<EmotionStrategyKnowledge>lambdaQuery()
                            .eq(EmotionStrategyKnowledge::getStatus, 1)
                            .orderByAsc(EmotionStrategyKnowledge::getId)
            );
            if (!emotionStrategies.isEmpty()) {
                knowledgeBase.put("emotion_strategy_knowledge", emotionStrategies.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("emotion", item.getEmotionCode());
                    row.put("reply_tone", item.getReplyTone());
                    row.put("comfort_prefix", item.getComfortPrefix());
                    row.put("comfort_examples", parseStringArray(item.getComfortExamplesJson()));
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var schemes = afterSalesSchemeKnowledgeMapper.selectList(
                    Wrappers.<AfterSalesSchemeKnowledge>lambdaQuery()
                            .eq(AfterSalesSchemeKnowledge::getStatus, 1)
                            .orderByAsc(AfterSalesSchemeKnowledge::getId)
            );
            if (!schemes.isEmpty()) {
                knowledgeBase.put("after_sales_scheme_knowledge", schemes.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("code", item.getSchemeCode());
                    row.put("label", item.getSchemeLabel());
                    row.put("description", item.getDescription());
                    row.put("requires_return", item.getRequiresReturn() != null && item.getRequiresReturn() == 1);
                    row.put("typical_scenes", parseStringArray(item.getTypicalScenesJson()));
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var sceneEvidence = sceneEvidenceKnowledgeMapper.selectList(
                    Wrappers.<SceneEvidenceKnowledge>lambdaQuery()
                            .eq(SceneEvidenceKnowledge::getStatus, 1)
                            .orderByAsc(SceneEvidenceKnowledge::getId)
            );
            if (!sceneEvidence.isEmpty()) {
                knowledgeBase.put("scene_evidence_knowledge", sceneEvidence.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("scene", item.getSceneCode());
                    row.put("label", item.getSceneLabel());
                    row.put("description", item.getDescription());
                    row.put("default_evidence", parseStringArray(item.getDefaultEvidenceJson()));
                    row.put("extra_evidence", parseStringArray(item.getExtraEvidenceJson()));
                    row.put("example_phrases", parseStringArray(item.getExamplePhrasesJson()));
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var faqList = faqMapper.selectList(
                    Wrappers.<Faq>lambdaQuery()
                            .eq(Faq::getStatus, 1)
                            .orderByAsc(Faq::getId)
            );
            if (!faqList.isEmpty()) {
                knowledgeBase.put("faq_knowledge", faqList.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("question", item.getQuestion());
                    row.put("answer", item.getAnswer());
                    row.put("tags", parseStringArray(item.getTags()));
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var productKnowledgeList = productKnowledgeMapper.selectList(
                    Wrappers.<ProductKnowledge>lambdaQuery()
                            .eq(ProductKnowledge::getStatus, 1)
                            .orderByAsc(ProductKnowledge::getId)
            );
            if (!productKnowledgeList.isEmpty()) {
                knowledgeBase.put("product_knowledge", productKnowledgeList.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("product_id", item.getProductId());
                    row.put("product_name", item.getProductName());
                    row.put("title", item.getTitle());
                    row.put("content", item.getContent());
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var policyList = afterSalesPolicyMapper.selectList(
                    Wrappers.<AfterSalesPolicy>lambdaQuery()
                            .eq(AfterSalesPolicy::getStatus, 1)
                            .orderByAsc(AfterSalesPolicy::getId)
            );
            if (!policyList.isEmpty()) {
                knowledgeBase.put("after_sales_policy_knowledge", policyList.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("policy_code", item.getPolicyCode());
                    row.put("policy_name", item.getPolicyName());
                    row.put("product_category", item.getProductCategory());
                    row.put("summary", item.getSummary());
                    row.put("content", item.getContent());
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var replyTemplates = replyTemplateKnowledgeMapper.selectList(
                    Wrappers.<ReplyTemplateKnowledge>lambdaQuery()
                            .eq(ReplyTemplateKnowledge::getStatus, 1)
                            .orderByAsc(ReplyTemplateKnowledge::getId)
            );
            if (!replyTemplates.isEmpty()) {
                knowledgeBase.put("reply_template_knowledge", replyTemplates.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("code", item.getTemplateCode());
                    row.put("scene", item.getSceneCode());
                    row.put("intent", item.getIntentCode());
                    row.put("tone", item.getTone());
                    row.put("template", item.getTemplateText());
                    row.put("description", item.getDescription());
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        try {
            var reviewKnowledgeList = reviewInterpretationKnowledgeMapper.selectList(
                    Wrappers.<ReviewInterpretationKnowledge>lambdaQuery()
                            .eq(ReviewInterpretationKnowledge::getStatus, 1)
                            .orderByAsc(ReviewInterpretationKnowledge::getId)
            );
            if (!reviewKnowledgeList.isEmpty()) {
                knowledgeBase.put("review_interpretation_knowledge", reviewKnowledgeList.stream().map(item -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("code", item.getCode());
                    row.put("sentiment", item.getSentiment());
                    row.put("scene", item.getSceneCode());
                    row.put("meaning", item.getMeaning());
                    row.put("response_strategy", item.getResponseStrategy());
                    row.put("example_phrases", parseStringArray(item.getExamplePhrasesJson()));
                    return row;
                }).toList());
            }
        } catch (Exception ignored) {
        }

        return knowledgeBase;
    }

    private void persistOverrides(LinkedHashMap<String, LinkedHashMap<String, Object>> overrides) {
        Path path = Paths.get(OVERRIDE_FILE);
        try {
            Path parent = path.getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            objectMapper.writerWithDefaultPrettyPrinter().writeValue(path.toFile(), overrides);
            cachedOverrides = overrides;
        } catch (IOException exception) {
            throw new BizException(500, "failed to save agent policy overrides: " + exception.getMessage());
        }
    }

    private void validateUpdateRequest(AgentGatewayDtos.PolicyConfigUpdateRequest request) {
        if (request == null) {
            throw new BizException(400, "missing policy update request");
        }
        if (!StringUtils.hasText(request.getProductCode())) {
            throw new BizException(400, "productCode is required");
        }
        if (request.getAutoRefundLimit() == null || request.getAutoRefundLimit() < 0) {
            throw new BizException(400, "autoRefundLimit must be >= 0");
        }
        if (!StringUtils.hasText(request.getEmotionHandoffMinLevel())) {
            throw new BizException(400, "emotionHandoffMinLevel is required");
        }
        String normalizedEmotion = request.getEmotionHandoffMinLevel().trim().toLowerCase();
        if (!supportedEmotionCodes().contains(normalizedEmotion)) {
            throw new BizException(400, "unsupported emotionHandoffMinLevel: " + request.getEmotionHandoffMinLevel());
        }
    }

    @SuppressWarnings("unchecked")
    private Set<String> supportedEmotionCodes() {
        Object rawLevels = loadKnowledgeBase().get("emotion_levels");
        if (!(rawLevels instanceof Iterable<?> iterable)) {
            return Set.of("satisfied", "calm", "anxious", "dissatisfied", "angry");
        }
        LinkedHashMap<String, Boolean> codes = new LinkedHashMap<>();
        for (Object item : iterable) {
            if (item instanceof Map<?, ?> map) {
                Object code = map.get("code");
                if (code != null) {
                    codes.put(String.valueOf(code).trim().toLowerCase(), Boolean.TRUE);
                }
            }
        }
        return codes.isEmpty() ? Set.of("satisfied", "calm", "anxious", "dissatisfied", "angry") : codes.keySet();
    }

    private java.util.List<String> parseStringArray(String json) {
        if (!StringUtils.hasText(json)) {
            return java.util.List.of();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<java.util.List<String>>() {});
        } catch (IOException exception) {
            return java.util.List.of();
        }
    }

    private Map<String, Object> deepCopy(Map<String, Object> source) {
        return objectMapper.convertValue(source, MAP_TYPE);
    }

    private LinkedHashMap<String, Object> deepCopyMap(Map<String, Object> source) {
        if (source == null) {
            return null;
        }
        return objectMapper.convertValue(source, MAP_TYPE);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object value) {
        if (value instanceof Map<?, ?> map) {
            return (Map<String, Object>) map;
        }
        return Map.of();
    }

    private LinkedHashMap<String, Object> mutableMap(Object value) {
        return deepCopyMap(asMap(value));
    }

    private LinkedHashMap<String, Object> mutableNestedMap(Map<String, Object> container, String key) {
        LinkedHashMap<String, Object> nested = mutableMap(container.get(key));
        container.put(key, nested);
        return nested;
    }

    private String normalizeMerchantCode(String merchantCode) {
        String raw = Optional.ofNullable(merchantCode).orElse(DEFAULT_MERCHANT_CODE).trim();
        return raw.isEmpty() ? DEFAULT_MERCHANT_CODE : raw.toUpperCase();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> mergeServicePolicy(Map<String, Object> catalog, Map<String, Object> servicePolicy) {
        Map<String, Object> merged = new LinkedHashMap<>(servicePolicy);
        Map<String, Object> templateMap = asMap(catalog.get("reply_templates"));
        if (!templateMap.isEmpty()) {
            Map<String, Object> merchantTemplates = asMap(servicePolicy.get("reply_templates"));
            Map<String, Object> combinedTemplates = new LinkedHashMap<>(templateMap);
            combinedTemplates.putAll(merchantTemplates);
            merged.put("reply_templates", combinedTemplates);
        }
        Map<String, Object> schemeMap = asMap(catalog.get("after_sales_schemes"));
        if (!schemeMap.isEmpty()) {
            merged.put("after_sales_schemes", schemeMap);
        }
        return merged;
    }

    @SuppressWarnings("unchecked")
    private void mergeInto(Map<String, Object> target, Map<String, Object> override) {
        for (Map.Entry<String, Object> entry : override.entrySet()) {
            Object currentValue = target.get(entry.getKey());
            Object overrideValue = entry.getValue();
            if (currentValue instanceof Map<?, ?> currentMap && overrideValue instanceof Map<?, ?> overrideMap) {
                LinkedHashMap<String, Object> mergedChild = mutableMap(currentMap);
                mergeInto(mergedChild, (Map<String, Object>) overrideMap);
                target.put(entry.getKey(), mergedChild);
                continue;
            }
            target.put(entry.getKey(), objectMapper.convertValue(overrideValue, Object.class));
        }
    }
}
