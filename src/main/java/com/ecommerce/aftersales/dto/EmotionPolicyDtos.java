package com.ecommerce.aftersales.dto;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.List;

public final class EmotionPolicyDtos {

    private EmotionPolicyDtos() {
    }

    @Data
    public static class EmotionPolicyWorkspace {
        private EmotionPolicyDetail draft;
        private EmotionPolicyDetail published;
        private List<EmotionPolicyVersionItem> versions;
    }

    @Data
    public static class EmotionPolicyDetail {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long policyId;
        private String policyName;
        private String scopeType;
        private String scopeValue;
        private String status;
        private Long version;
        private String sensitivityLevel;
        private String summary;
        private EmotionThresholds thresholds;
        private EmotionWeights weights;
        private EmotionTrendPolicy trend;
        private List<EmotionKeywordRule> keywordRules;
        private List<EmotionComboRule> comboRules;
        private String operatorName;
        private String updatedAt;
        private String publishedAt;
        private Boolean editable;
    }

    @Data
    public static class EmotionThresholds {
        private Integer anxious;
        private Integer dissatisfied;
        private Integer angry;
    }

    @Data
    public static class EmotionWeights {
        private Integer punctuationTriple;
        private Integer punctuationExclamation;
        private Integer punctuationQuestion;
        private Integer humanRequestFirst;
        private Integer humanRequestRepeat;
        private Integer timeout;
        private Integer merchantRejected;
    }

    @Data
    public static class EmotionTrendPolicy {
        private Integer consecutiveRiseTrigger;
        private Boolean calmToAngryEnabled;
    }

    @Data
    public static class EmotionKeywordRule {
        private String name;
        private List<String> keywords;
        private Integer score;
        private Integer extraPerMatch;
        private Boolean enabled;
    }

    @Data
    public static class EmotionComboRule {
        private String name;
        private List<List<String>> groups;
        private Integer bonus;
        private Boolean enabled;
    }

    @Data
    public static class EmotionPolicyVersionItem {
        private Long version;
        private String status;
        private String note;
        private String updatedAt;
        private String publishedAt;
    }

    @Data
    public static class EmotionPolicySaveRequest {
        @NotBlank(message = "policyName不能为空")
        private String policyName;
        private String scopeType;
        private String scopeValue;
        private String sensitivityLevel;
        private String summary;
        @Valid
        private EmotionThresholds thresholds;
        @Valid
        private EmotionWeights weights;
        @Valid
        private EmotionTrendPolicy trend;
        @Valid
        private List<EmotionKeywordRule> keywordRules;
        @Valid
        private List<EmotionComboRule> comboRules;
        private String operatorName;
    }

    @Data
    public static class EmotionPolicyPublishRequest {
        private String publishNote;
        private String operatorName;
    }

    @Data
    public static class EmotionPolicyRollbackRequest {
        private Long targetVersion;
        private String rollbackReason;
        private String operatorName;
    }

    @Data
    public static class EmotionPolicyTestRequest {
        @NotBlank(message = "text不能为空")
        private String text;
        private List<String> historyTexts;
        private Integer humanRequestCount;
        private String orderStatus;
        private String productCategory;
        private String merchantCode;
    }

    @Data
    public static class EmotionTurnView {
        private String text;
        private String label;
        private Integer score;
        private Integer confidence;
        private Boolean needHumanPriority;
        private List<String> triggers;
        private Boolean fromHistory;
        private String createdAt;
    }

    @Data
    public static class EmotionPolicyTestResponse {
        private String emotionLabel;
        private Integer score;
        private String trend;
        private Integer consecutiveRises;
        private Boolean needHuman;
        private String replyTone;
        private List<String> matchedRules;
        private List<String> escalationSignals;
        private String summary;
        private List<EmotionTurnView> timeline;
    }
}
