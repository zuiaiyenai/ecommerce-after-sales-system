package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.BizException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class KnowledgeMetadataPolicy {

    private static final List<Option> PRODUCT_CATEGORIES = List.of(
            new Option("digital", "数码通用"),
            new Option("phone", "手机"),
            new Option("headphone", "耳机"),
            new Option("apparel", "服装"),
            new Option("daily", "日用"),
            new Option("shoes", "鞋靴"),
            new Option("food", "食品"),
            new Option("home", "家居"),
            new Option("other", "其他")
    );
    private static final List<Option> SCENES = List.of(
            new Option("damage", "商品破损"),
            new Option("quality_issue", "功能或质量问题"),
            new Option("package_damage", "外包装破损"),
            new Option("wrong_item", "错发商品"),
            new Option("missing_item", "少发漏发"),
            new Option("wrong_or_missing_items", "错发或少发"),
            new Option("logistics_issue", "物流异常"),
            new Option("return", "退货退款"),
            new Option("exchange", "换货"),
            new Option("refund_only", "仅退款"),
            new Option("return_shipping", "退货运费"),
            new Option("refund_progress", "退款进度"),
            new Option("progress_query", "售后进度"),
            new Option("evidence_requirement", "凭证要求"),
            new Option("human_handoff", "人工接管"),
            new Option("completion", "售后完成"),
            new Option("review", "审核边界")
    );
    private static final List<Option> INTENTS = List.of(
            new Option("refund", "退款 / 退货退款"),
            new Option("exchange", "换货"),
            new Option("reissue", "补发"),
            new Option("refund_or_reissue", "退款或补发"),
            new Option("evidence_requirement", "凭证要求"),
            new Option("quality_standard", "质量判定标准"),
            new Option("policy_explanation", "政策解释"),
            new Option("ask_missing_evidence", "引导补充凭证"),
            new Option("compensation_or_review", "补偿或人工复核"),
            new Option("guardrail", "安全边界"),
            new Option("review_invitation", "评价邀请"),
            new Option("guideline", "操作指南")
    );
    private static final Set<String> VERSIONED_KNOWLEDGE_TYPES = Set.of(
            "after_sales_policy", "refund_policy", "exchange_rule"
    );

    private static final Map<String, String> CATEGORY_ALIASES = aliases(PRODUCT_CATEGORIES, Map.ofEntries(
            Map.entry("数码", "digital"),
            Map.entry("手机", "phone"),
            Map.entry("耳机", "headphone"),
            Map.entry("蓝牙耳机", "headphone"),
            Map.entry("服装", "apparel"),
            Map.entry("日用", "daily"),
            Map.entry("鞋靴", "shoes"),
            Map.entry("食品", "food"),
            Map.entry("家居", "home"),
            Map.entry("其他", "other")
    ));
    private static final Map<String, String> SCENE_ALIASES = aliases(SCENES, Map.ofEntries(
            Map.entry("product_damage", "damage"),
            Map.entry("logistics_damage", "logistics_issue")
    ));
    private static final Map<String, String> INTENT_ALIASES = aliases(INTENTS, Map.ofEntries(
            Map.entry("resend", "reissue")
    ));

    private final AgentPolicyCatalogService agentPolicyCatalogService;

    public Map<String, Object> options(String merchantCode) {
        String currentPolicyVersion = currentPolicyVersion(merchantCode);
        return Map.of(
                "merchants", merchantOptions(),
                "productCategories", PRODUCT_CATEGORIES,
                "scenes", SCENES,
                "intents", INTENTS,
                "versionedKnowledgeTypes", VERSIONED_KNOWLEDGE_TYPES,
                "currentPolicyVersion", currentPolicyVersion
        );
    }

    public String normalizeMerchantCode(String merchantCode) {
        String requested = merchantCode == null || merchantCode.isBlank()
                ? "MERCHANT_DEMO"
                : merchantCode.trim().toUpperCase(Locale.ROOT);
        boolean supported = merchantOptions().stream().anyMatch(option -> option.value().equals(requested));
        if (!supported) {
            throw new BizException("商家代码不是系统策略目录中的有效商家，请从管理端选项中选择");
        }
        return requested;
    }

    public String normalizeProductCategory(String value) {
        return normalizeControlled(value, CATEGORY_ALIASES, "商品品类");
    }

    public String normalizeScene(String value) {
        return normalizeControlled(value, SCENE_ALIASES, "售后场景");
    }

    public String normalizeIntent(String value) {
        return normalizeControlled(value, INTENT_ALIASES, "知识用途");
    }

    public String resolvePolicyVersion(String knowledgeType, String merchantCode) {
        if (!isVersionedKnowledgeType(knowledgeType)) {
            return null;
        }
        return resolvePolicySnapshot(merchantCode).policyVersion();
    }

    public PolicySnapshot resolvePolicySnapshot(String merchantCode) {
        String normalizedMerchantCode = requireKnownMerchantCode(merchantCode);
        Map<String, Object> servicePolicy = currentServicePolicy(normalizedMerchantCode);
        String policyCode = stringValue(servicePolicy.get("policy_code"));
        String policyVersion = stringValue(servicePolicy.get("policy_version"));
        if (policyCode.isBlank() || policyVersion.isBlank()) {
            throw new BizException("当前商家没有可绑定的售后政策版本");
        }
        return new PolicySnapshot(policyCode, policyVersion);
    }

    private String requireKnownMerchantCode(String merchantCode) {
        if (merchantCode == null || merchantCode.isBlank()) {
            throw new BizException("商家代码不是系统策略目录中的有效商家，请从管理端选项中选择");
        }
        String requested = merchantCode.trim().toUpperCase(Locale.ROOT);
        boolean supported = merchantOptions().stream().anyMatch(option -> option.value().equals(requested));
        if (!supported) {
            throw new BizException("商家代码不是系统策略目录中的有效商家，请从管理端选项中选择");
        }
        return requested;
    }

    public boolean isVersionedKnowledgeType(String knowledgeType) {
        return VERSIONED_KNOWLEDGE_TYPES.contains(normalizeKey(knowledgeType));
    }

    private String currentPolicyVersion(String merchantCode) {
        return stringValue(currentServicePolicy(merchantCode).get("policy_version"));
    }

    private Map<String, Object> currentServicePolicy(String merchantCode) {
        Map<String, Object> policy = agentPolicyCatalogService.getMerchantPolicy(merchantCode);
        Object rawServicePolicy = policy.get("service_policy");
        if (!(rawServicePolicy instanceof Map<?, ?> rawMap)) {
            return Map.of();
        }
        Map<String, Object> servicePolicy = new LinkedHashMap<>();
        rawMap.forEach((key, value) -> servicePolicy.put(String.valueOf(key), value));
        return servicePolicy;
    }

    private static String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private List<Option> merchantOptions() {
        Object rawMerchants = agentPolicyCatalogService.getCatalog().get("merchants");
        if (!(rawMerchants instanceof Map<?, ?> merchants)) {
            return List.of();
        }
        return merchants.entrySet().stream()
                .map(entry -> {
                    String code = String.valueOf(entry.getKey()).trim().toUpperCase(Locale.ROOT);
                    String label = code;
                    if (entry.getValue() instanceof Map<?, ?> policy) {
                        Object displayName = policy.get("display_name");
                        if (displayName != null && !String.valueOf(displayName).isBlank()) {
                            label = String.valueOf(displayName) + "（" + code + "）";
                        }
                    }
                    return new Option(code, label);
                })
                .sorted(java.util.Comparator.comparing(Option::value))
                .toList();
    }

    private static String normalizeControlled(String value, Map<String, String> aliases, String fieldLabel) {
        String key = normalizeKey(value);
        if (key.isBlank() || Set.of("general", "通用", "全部", "all").contains(key)) {
            return null;
        }
        String normalized = aliases.get(key);
        if (normalized == null) {
            throw new BizException(fieldLabel + "不是系统支持的标准值，请从管理端选项中选择");
        }
        return normalized;
    }

    private static Map<String, String> aliases(List<Option> options, Map<String, String> extraAliases) {
        Map<String, String> result = new LinkedHashMap<>();
        for (Option option : options) {
            result.put(normalizeKey(option.value()), option.value());
            result.put(normalizeKey(option.label()), option.value());
        }
        extraAliases.forEach((key, value) -> result.put(normalizeKey(key), value));
        return Map.copyOf(result);
    }

    private static String normalizeKey(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }

    public record PolicySnapshot(String policyCode, String policyVersion) {}

    public record Option(String value, String label) {}
}
