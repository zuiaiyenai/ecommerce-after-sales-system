package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
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
            cachedKnowledgeBase = readJsonResource(KNOWLEDGE_BASE_RESOURCE_NAME);
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
