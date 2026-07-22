package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.BizException;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class KnowledgeMetadataPolicyTest {

    @Test
    void aliasesAreCanonicalizedAndGeneralScopeUsesNull() {
        KnowledgeMetadataPolicy policy = policy("2026-07-02-v3");

        assertThat(policy.normalizeProductCategory("数码")).isEqualTo("digital");
        assertThat(policy.normalizeProductCategory("通用")).isNull();
        assertThat(policy.normalizeScene("product_damage")).isEqualTo("damage");
        assertThat(policy.normalizeIntent("resend")).isEqualTo("reissue");
    }

    @Test
    void unknownStrongFilterIsRejectedInsteadOfSilentlyCreatingAnUnreachableDocument() {
        KnowledgeMetadataPolicy policy = policy("2026-07-02-v3");

        assertThatThrownBy(() -> policy.normalizeScene("qualty_isue"))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("不是系统支持的标准值");
        assertThatThrownBy(() -> policy.normalizeMerchantCode("MERCHANT_DME0"))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("有效商家");
    }

    @Test
    void policyVersionComesFromMerchantPolicyAndNonPolicyKnowledgeHasNoForcedVersion() {
        KnowledgeMetadataPolicy policy = policy("2026-07-02-v3");

        assertThat(policy.resolvePolicyVersion("after_sales_policy", "MERCHANT_DEMO"))
                .isEqualTo("2026-07-02-v3");
        assertThat(policy.resolvePolicyVersion("faq", "MERCHANT_DEMO")).isNull();
        assertThat(policy.resolvePolicySnapshot("MERCHANT_DEMO"))
                .isEqualTo(new KnowledgeMetadataPolicy.PolicySnapshot(
                        "DEFAULT_POLICY",
                        "2026-07-02-v3"
                ));
    }

    private KnowledgeMetadataPolicy policy(String version) {
        AgentPolicyCatalogService catalogService = mock(AgentPolicyCatalogService.class);
        when(catalogService.getCatalog()).thenReturn(Map.of(
                "merchants", Map.of("MERCHANT_DEMO", Map.of("display_name", "演示商家"))
        ));
        when(catalogService.getMerchantPolicy(any()))
                .thenReturn(Map.of("service_policy", Map.of(
                        "policy_code", "DEFAULT_POLICY",
                        "policy_version", version
                )));
        return new KnowledgeMetadataPolicy(catalogService);
    }
}
