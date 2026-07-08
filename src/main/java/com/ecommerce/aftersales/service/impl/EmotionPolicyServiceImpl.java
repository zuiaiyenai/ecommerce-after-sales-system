package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.EmotionPolicyDtos.*;
import com.ecommerce.aftersales.service.EmotionPolicyService;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

@Slf4j
@Service
public class EmotionPolicyServiceImpl implements EmotionPolicyService {

    private static final DateTimeFormatter TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final AtomicLong idGenerator = new AtomicLong(1000L);
    private final Map<Long, EmotionPolicyDetail> versionStore = new LinkedHashMap<>();
    private EmotionPolicyDetail draftPolicy;
    private EmotionPolicyDetail publishedPolicy;
    private long currentVersion;

    @PostConstruct
    public void init() {
        EmotionPolicyDetail defaultPolicy = buildDefaultPolicy();
        currentVersion = defaultPolicy.getVersion();
        publishedPolicy = copy(defaultPolicy);
        draftPolicy = copy(defaultPolicy);
        versionStore.put(defaultPolicy.getVersion(), copy(defaultPolicy));
    }

    @Override
    public synchronized EmotionPolicyWorkspace getWorkspace() {
        EmotionPolicyWorkspace workspace = new EmotionPolicyWorkspace();
        workspace.setDraft(copy(draftPolicy));
        workspace.setPublished(copy(publishedPolicy));
        workspace.setVersions(listVersions());
        return workspace;
    }

    @Override
    public synchronized List<EmotionPolicyVersionItem> listVersions() {
        List<EmotionPolicyVersionItem> versions = new ArrayList<>();
        for (EmotionPolicyDetail detail : versionStore.values()) {
            EmotionPolicyVersionItem item = new EmotionPolicyVersionItem();
            item.setVersion(detail.getVersion());
            item.setStatus(detail.getStatus());
            item.setNote(detail.getSummary());
            item.setUpdatedAt(detail.getUpdatedAt());
            item.setPublishedAt(detail.getPublishedAt());
            versions.add(item);
        }
        return versions;
    }

    @Override
    public synchronized EmotionPolicyWorkspace saveDraft(EmotionPolicySaveRequest request) {
        EmotionPolicyDetail nextDraft = mergeRequestIntoDraft(request);
        nextDraft.setStatus("DRAFT");
        nextDraft.setEditable(Boolean.TRUE);
        nextDraft.setUpdatedAt(now());
        draftPolicy = nextDraft;
        return getWorkspace();
    }

    @Override
    public synchronized EmotionPolicyWorkspace publish(EmotionPolicyPublishRequest request) {
        if (draftPolicy == null) {
            throw new BizException(400, "No draft policy to publish");
        }
        EmotionPolicyDetail published = copy(draftPolicy);
        currentVersion = currentVersion + 1;
        published.setVersion(currentVersion);
        published.setStatus("PUBLISHED");
        published.setEditable(Boolean.FALSE);
        published.setOperatorName(blankToDefault(request.getOperatorName(), published.getOperatorName()));
        published.setPublishedAt(now());
        published.setUpdatedAt(now());
        if (request.getPublishNote() != null && !request.getPublishNote().isBlank()) {
            published.setSummary(request.getPublishNote());
        }
        publishedPolicy = copy(published);
        draftPolicy = copy(published);
        versionStore.put(published.getVersion(), copy(published));
        return getWorkspace();
    }

    @Override
    public synchronized EmotionPolicyWorkspace rollback(EmotionPolicyRollbackRequest request) {
        if (request.getTargetVersion() == null) {
            throw new BizException(400, "targetVersion is required");
        }
        EmotionPolicyDetail snapshot = versionStore.get(request.getTargetVersion());
        if (snapshot == null) {
            throw new BizException(404, "Target policy version not found");
        }
        EmotionPolicyDetail rolledBack = copy(snapshot);
        rolledBack.setVersion(currentVersion + 1);
        rolledBack.setStatus("DRAFT");
        rolledBack.setEditable(Boolean.TRUE);
        rolledBack.setOperatorName(blankToDefault(request.getOperatorName(), rolledBack.getOperatorName()));
        rolledBack.setSummary(buildRollbackSummary(snapshot, request.getRollbackReason()));
        rolledBack.setUpdatedAt(now());
        draftPolicy = rolledBack;
        return getWorkspace();
    }

    @Override
    public synchronized EmotionPolicyTestResponse testPolicy(EmotionPolicyTestRequest request) {
        EmotionPolicyDetail policy = draftPolicy != null ? draftPolicy : publishedPolicy;
        return EmotionPolicyPreviewEngine.preview(policy, request);
    }

    private EmotionPolicyDetail buildDefaultPolicy() {
        EmotionPolicyDetail detail = new EmotionPolicyDetail();
        detail.setPolicyId(idGenerator.incrementAndGet());
        detail.setPolicyName("default-emotion-policy");
        detail.setScopeType("GLOBAL");
        detail.setScopeValue("ALL");
        detail.setStatus("PUBLISHED");
        detail.setVersion(1L);
        detail.setSensitivityLevel("STANDARD");
        detail.setSummary("Default policy for all conversations");
        detail.setOperatorName("system");
        detail.setUpdatedAt(now());
        detail.setPublishedAt(now());
        detail.setEditable(Boolean.FALSE);

        EmotionThresholds thresholds = new EmotionThresholds();
        thresholds.setAnxious(20);
        thresholds.setDissatisfied(45);
        thresholds.setAngry(85);
        detail.setThresholds(thresholds);

        EmotionWeights weights = new EmotionWeights();
        weights.setPunctuationTriple(8);
        weights.setPunctuationExclamation(4);
        weights.setPunctuationQuestion(4);
        weights.setHumanRequestFirst(8);
        weights.setHumanRequestRepeat(12);
        weights.setTimeout(10);
        weights.setMerchantRejected(12);
        detail.setWeights(weights);

        EmotionTrendPolicy trend = new EmotionTrendPolicy();
        trend.setConsecutiveRiseTrigger(2);
        trend.setCalmToAngryEnabled(Boolean.TRUE);
        detail.setTrend(trend);

        List<EmotionKeywordRule> keywordRules = new ArrayList<>();
        keywordRules.add(keywordRule("complaint", List.of(
                "\u6295\u8bc9", "\u4e3e\u62a5", "\u5dee\u8bc4", "\u9a97\u4eba", "\u6b3a\u8bc8"), 40, 3));
        keywordRules.add(keywordRule("anger", List.of(
                "\u751f\u6c14", "\u6c14\u6b7b", "\u592a\u8fc7\u5206", "\u53d7\u4e0d\u4e86", "\u4f60\u4eec\u5230\u5e95",
                "\u4e0d\u6ee1\u610f", "\u79bb\u8c31"), 30, 3));
        keywordRules.add(keywordRule("stalled", List.of(
                "\u592a\u6162\u4e86", "\u4e00\u76f4\u6ca1\u4eba\u5904\u7406", "\u6ca1\u4eba\u5904\u7406",
                "\u5230\u5e95\u600e\u4e48\u5904\u7406", "\u8fd9\u4e5f\u592a\u6162\u4e86"), 22, 2));
        keywordRules.add(keywordRule("progress_query", List.of(
                "\u600e\u4e48\u8fd8", "\u4e00\u76f4\u6ca1", "\u591a\u4e45\u4e86", "\u5feb\u70b9",
                "\u50ac\u4e00\u4e0b", "\u4ec0\u4e48\u65f6\u5019\u5230\u8d27", "\u8fd8\u6ca1\u5904\u7406"), 15, 2));
        detail.setKeywordRules(keywordRules);

        List<EmotionComboRule> comboRules = new ArrayList<>();
        comboRules.add(comboRule("complaint_plus_human",
                List.of(
                        List.of("\u6295\u8bc9", "\u5dee\u8bc4", "\u4e3e\u62a5"),
                        List.of("\u4eba\u5de5", "\u5ba2\u670d", "\u771f\u4eba")
                ), 10));
        comboRules.add(comboRule("fraud_complaint_combo",
                List.of(
                        List.of("\u9a97\u4eba", "\u6b3a\u8bc8"),
                        List.of("\u6295\u8bc9", "\u4e3e\u62a5", "\u5dee\u8bc4")
                ), 15));
        comboRules.add(comboRule("stalled_progress_combo",
                List.of(
                        List.of("\u4e00\u76f4\u6ca1\u4eba\u5904\u7406", "\u6ca1\u4eba\u5904\u7406", "\u8fd8\u6ca1\u5904\u7406"),
                        List.of("\u592a\u6162\u4e86", "\u5feb\u70b9", "\u50ac\u4e00\u4e0b")
                ), 8));
        detail.setComboRules(comboRules);
        return detail;
    }

    private EmotionPolicyDetail mergeRequestIntoDraft(EmotionPolicySaveRequest request) {
        EmotionPolicyDetail base = draftPolicy != null ? copy(draftPolicy) : buildDefaultPolicy();
        base.setPolicyName(request.getPolicyName());
        base.setScopeType(blankToDefault(request.getScopeType(), base.getScopeType()));
        base.setScopeValue(blankToDefault(request.getScopeValue(), base.getScopeValue()));
        base.setSensitivityLevel(blankToDefault(request.getSensitivityLevel(), base.getSensitivityLevel()));
        base.setSummary(blankToDefault(request.getSummary(), base.getSummary()));
        base.setOperatorName(blankToDefault(request.getOperatorName(), base.getOperatorName()));
        if (request.getThresholds() != null) {
            base.setThresholds(copy(request.getThresholds()));
        }
        if (request.getWeights() != null) {
            base.setWeights(copy(request.getWeights()));
        }
        if (request.getTrend() != null) {
            base.setTrend(copy(request.getTrend()));
        }
        if (request.getKeywordRules() != null) {
            base.setKeywordRules(copyKeywordRules(request.getKeywordRules()));
        }
        if (request.getComboRules() != null) {
            base.setComboRules(copyComboRules(request.getComboRules()));
        }
        return base;
    }

    private static EmotionKeywordRule keywordRule(String name, List<String> keywords, int score, int extraPerMatch) {
        EmotionKeywordRule rule = new EmotionKeywordRule();
        rule.setName(name);
        rule.setKeywords(new ArrayList<>(keywords));
        rule.setScore(score);
        rule.setExtraPerMatch(extraPerMatch);
        rule.setEnabled(Boolean.TRUE);
        return rule;
    }

    private static EmotionComboRule comboRule(String name, List<List<String>> groups, int bonus) {
        EmotionComboRule rule = new EmotionComboRule();
        rule.setName(name);
        rule.setGroups(groups.stream().<List<String>>map(group -> new ArrayList<>(group)).toList());
        rule.setBonus(bonus);
        rule.setEnabled(Boolean.TRUE);
        return rule;
    }

    private static EmotionPolicyDetail copy(EmotionPolicyDetail source) {
        if (source == null) {
            return null;
        }
        EmotionPolicyDetail target = new EmotionPolicyDetail();
        target.setPolicyId(source.getPolicyId());
        target.setPolicyName(source.getPolicyName());
        target.setScopeType(source.getScopeType());
        target.setScopeValue(source.getScopeValue());
        target.setStatus(source.getStatus());
        target.setVersion(source.getVersion());
        target.setSensitivityLevel(source.getSensitivityLevel());
        target.setSummary(source.getSummary());
        target.setThresholds(copy(source.getThresholds()));
        target.setWeights(copy(source.getWeights()));
        target.setTrend(copy(source.getTrend()));
        target.setKeywordRules(copyKeywordRules(source.getKeywordRules()));
        target.setComboRules(copyComboRules(source.getComboRules()));
        target.setOperatorName(source.getOperatorName());
        target.setUpdatedAt(source.getUpdatedAt());
        target.setPublishedAt(source.getPublishedAt());
        target.setEditable(source.getEditable());
        return target;
    }

    private static EmotionThresholds copy(EmotionThresholds source) {
        if (source == null) {
            return null;
        }
        EmotionThresholds target = new EmotionThresholds();
        target.setAnxious(source.getAnxious());
        target.setDissatisfied(source.getDissatisfied());
        target.setAngry(source.getAngry());
        return target;
    }

    private static EmotionWeights copy(EmotionWeights source) {
        if (source == null) {
            return null;
        }
        EmotionWeights target = new EmotionWeights();
        target.setPunctuationTriple(source.getPunctuationTriple());
        target.setPunctuationExclamation(source.getPunctuationExclamation());
        target.setPunctuationQuestion(source.getPunctuationQuestion());
        target.setHumanRequestFirst(source.getHumanRequestFirst());
        target.setHumanRequestRepeat(source.getHumanRequestRepeat());
        target.setTimeout(source.getTimeout());
        target.setMerchantRejected(source.getMerchantRejected());
        return target;
    }

    private static EmotionTrendPolicy copy(EmotionTrendPolicy source) {
        if (source == null) {
            return null;
        }
        EmotionTrendPolicy target = new EmotionTrendPolicy();
        target.setConsecutiveRiseTrigger(source.getConsecutiveRiseTrigger());
        target.setCalmToAngryEnabled(source.getCalmToAngryEnabled());
        return target;
    }

    private static List<EmotionKeywordRule> copyKeywordRules(List<EmotionKeywordRule> source) {
        List<EmotionKeywordRule> target = new ArrayList<>();
        if (source == null) {
            return target;
        }
        for (EmotionKeywordRule item : source) {
            if (item == null) {
                continue;
            }
            EmotionKeywordRule rule = new EmotionKeywordRule();
            rule.setName(item.getName());
            rule.setKeywords(item.getKeywords() == null ? List.of() : new ArrayList<>(item.getKeywords()));
            rule.setScore(item.getScore());
            rule.setExtraPerMatch(item.getExtraPerMatch());
            rule.setEnabled(item.getEnabled());
            target.add(rule);
        }
        return target;
    }

    private static List<EmotionComboRule> copyComboRules(List<EmotionComboRule> source) {
        List<EmotionComboRule> target = new ArrayList<>();
        if (source == null) {
            return target;
        }
        for (EmotionComboRule item : source) {
            if (item == null) {
                continue;
            }
            EmotionComboRule rule = new EmotionComboRule();
            rule.setName(item.getName());
            List<List<String>> groups = new ArrayList<>();
            if (item.getGroups() != null) {
                for (List<String> group : item.getGroups()) {
                    groups.add(group == null ? List.of() : new ArrayList<>(group));
                }
            }
            rule.setGroups(groups);
            rule.setBonus(item.getBonus());
            rule.setEnabled(item.getEnabled());
            target.add(rule);
        }
        return target;
    }

    private static String now() {
        return LocalDateTime.now().format(TIME_FORMATTER);
    }

    private static String blankToDefault(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    private static String buildRollbackSummary(EmotionPolicyDetail snapshot, String rollbackReason) {
        String base = "Rollback to version " + snapshot.getVersion();
        if (rollbackReason == null || rollbackReason.isBlank()) {
            return base;
        }
        return base + ", reason: " + rollbackReason;
    }

    private static final class EmotionPolicyPreviewEngine {

        private EmotionPolicyPreviewEngine() {
        }

        private static EmotionPolicyTestResponse preview(EmotionPolicyDetail policy, EmotionPolicyTestRequest request) {
            EmotionThresholds thresholds = policy != null && policy.getThresholds() != null
                    ? policy.getThresholds() : defaultThresholds();
            EmotionWeights weights = policy != null && policy.getWeights() != null
                    ? policy.getWeights() : defaultWeights();
            EmotionTrendPolicy trendPolicy = policy != null && policy.getTrend() != null
                    ? policy.getTrend() : defaultTrend();

            List<EmotionTurnView> timeline = new ArrayList<>();
            if (request.getHistoryTexts() != null) {
                for (String text : request.getHistoryTexts()) {
                    if (text == null || text.isBlank()) {
                        continue;
                    }
                    timeline.add(scoreTurn(text, true, thresholds, weights, policy));
                }
            }
            EmotionTurnView current = scoreTurn(request.getText(), false, thresholds, weights, policy);
            timeline.add(current);

            String trend = resolveTrend(timeline);
            int consecutiveRises = countConsecutiveRises(timeline);
            List<String> escalationSignals = new ArrayList<>();
            if (consecutiveRises >= safeInt(trendPolicy.getConsecutiveRiseTrigger())) {
                escalationSignals.add("consecutive_rises");
            }
            if (Boolean.TRUE.equals(trendPolicy.getCalmToAngryEnabled())
                    && timeline.size() >= 2
                    && "CALM".equalsIgnoreCase(timeline.get(timeline.size() - 2).getLabel())
                    && "ANGRY".equalsIgnoreCase(current.getLabel())) {
                escalationSignals.add("jump_calm_to_angry");
            }
            Integer humanRequestCount = request.getHumanRequestCount();
            if (humanRequestCount != null && humanRequestCount >= 2
                    && ("DISSATISFIED".equalsIgnoreCase(current.getLabel())
                    || "ANGRY".equalsIgnoreCase(current.getLabel()))) {
                escalationSignals.add("repeated_human_request_without_relief");
            }
            if ("ANGRY".equalsIgnoreCase(current.getLabel()) && "up".equalsIgnoreCase(trend)) {
                escalationSignals.add("anger_uptrend");
            }

            EmotionPolicyTestResponse response = new EmotionPolicyTestResponse();
            response.setEmotionLabel(current.getLabel());
            response.setScore(current.getScore());
            response.setTrend(trend);
            response.setConsecutiveRises(consecutiveRises);
            response.setNeedHuman("ANGRY".equalsIgnoreCase(current.getLabel()) || !escalationSignals.isEmpty());
            response.setReplyTone(resolveReplyTone(current.getLabel(), escalationSignals));
            response.setMatchedRules(current.getTriggers());
            response.setEscalationSignals(escalationSignals);
            response.setSummary(buildSummary(current.getLabel(), current.getScore(), escalationSignals));
            response.setTimeline(timeline);
            return response;
        }

        private static EmotionTurnView scoreTurn(String text,
                                                 boolean fromHistory,
                                                 EmotionThresholds thresholds,
                                                 EmotionWeights weights,
                                                 EmotionPolicyDetail policy) {
            String normalized = text == null ? "" : text.trim();
            int score = 0;
            List<String> triggers = new ArrayList<>();
            if (policy != null && policy.getKeywordRules() != null) {
                for (EmotionKeywordRule rule : policy.getKeywordRules()) {
                    if (rule == null || Boolean.FALSE.equals(rule.getEnabled())) {
                        continue;
                    }
                    score += applyKeywordRule(normalized, rule, triggers);
                }
                if (policy.getComboRules() != null) {
                    for (EmotionComboRule rule : policy.getComboRules()) {
                        if (rule == null || Boolean.FALSE.equals(rule.getEnabled())) {
                            continue;
                        }
                        if (comboMatched(normalized, rule.getGroups())) {
                            score += safeInt(rule.getBonus());
                            triggers.add(rule.getName());
                        }
                    }
                }
            }
            score += punctuationScore(normalized, weights);
            score = Math.min(score, 100);
            EmotionTurnView view = new EmotionTurnView();
            view.setText(normalized);
            view.setScore(score);
            view.setLabel(resolveLabel(score, thresholds));
            view.setTriggers(triggers.stream().distinct().toList());
            view.setFromHistory(fromHistory);
            view.setCreatedAt(now());
            return view;
        }

        private static int applyKeywordRule(String text, EmotionKeywordRule rule, List<String> triggers) {
            if (rule.getKeywords() == null || rule.getKeywords().isEmpty()) {
                return 0;
            }
            List<String> matched = new ArrayList<>();
            for (String keyword : rule.getKeywords()) {
                if (keyword != null && !keyword.isBlank() && text.contains(keyword)) {
                    matched.add(keyword);
                }
            }
            if (matched.isEmpty()) {
                return 0;
            }
            triggers.addAll(matched);
            triggers.add(rule.getName());
            int extra = Math.max(0, matched.size() - 1) * safeInt(rule.getExtraPerMatch());
            return safeInt(rule.getScore()) + extra;
        }

        private static boolean comboMatched(String text, List<List<String>> groups) {
            if (groups == null || groups.isEmpty()) {
                return false;
            }
            for (List<String> group : groups) {
                boolean matched = false;
                if (group != null) {
                    for (String keyword : group) {
                        if (keyword != null && !keyword.isBlank() && text.contains(keyword)) {
                            matched = true;
                            break;
                        }
                    }
                }
                if (!matched) {
                    return false;
                }
            }
            return true;
        }

        private static int punctuationScore(String text, EmotionWeights weights) {
            int score = 0;
            if (text.contains("!!!") || text.contains("???")) {
                score += safeInt(weights.getPunctuationTriple());
            }
            if (countChar(text, '!') >= 3) {
                score += safeInt(weights.getPunctuationExclamation());
            }
            if (countChar(text, '?') >= 3) {
                score += safeInt(weights.getPunctuationQuestion());
            }
            return score;
        }

        private static int countChar(String text, char target) {
            int count = 0;
            for (int i = 0; i < text.length(); i++) {
                if (text.charAt(i) == target) {
                    count++;
                }
            }
            return count;
        }

        private static String resolveLabel(int score, EmotionThresholds thresholds) {
            if (score >= safeInt(thresholds.getAngry())) {
                return "ANGRY";
            }
            if (score >= safeInt(thresholds.getDissatisfied())) {
                return "DISSATISFIED";
            }
            if (score >= safeInt(thresholds.getAnxious())) {
                return "ANXIOUS";
            }
            return "CALM";
        }

        private static String resolveTrend(List<EmotionTurnView> timeline) {
            if (timeline.size() < 2) {
                return "stable";
            }
            int previous = level(timeline.get(timeline.size() - 2).getLabel());
            int current = level(timeline.get(timeline.size() - 1).getLabel());
            if (current > previous) {
                return "up";
            }
            if (current < previous) {
                return "down";
            }
            return "stable";
        }

        private static int countConsecutiveRises(List<EmotionTurnView> timeline) {
            if (timeline.size() < 2) {
                return 0;
            }
            int rises = 0;
            for (int index = timeline.size() - 1; index > 0; index--) {
                int current = level(timeline.get(index).getLabel());
                int previous = level(timeline.get(index - 1).getLabel());
                if (current > previous) {
                    rises++;
                    continue;
                }
                break;
            }
            return rises;
        }

        private static int level(String label) {
            if ("ANGRY".equalsIgnoreCase(label)) {
                return 3;
            }
            if ("DISSATISFIED".equalsIgnoreCase(label)) {
                return 2;
            }
            if ("ANXIOUS".equalsIgnoreCase(label)) {
                return 1;
            }
            return 0;
        }

        private static String resolveReplyTone(String label, List<String> escalationSignals) {
            if (!escalationSignals.isEmpty() && ("DISSATISFIED".equalsIgnoreCase(label) || "ANGRY".equalsIgnoreCase(label))) {
                return "priority_human_support";
            }
            return switch (label == null ? "CALM" : label.toUpperCase()) {
                case "ANXIOUS" -> "comfort_and_progress";
                case "DISSATISFIED" -> "comfort_and_action";
                case "ANGRY" -> "priority_human_support";
                default -> "clear";
            };
        }

        private static String buildSummary(String label, int score, List<String> escalationSignals) {
            StringBuilder builder = new StringBuilder();
            builder.append("Current emotion: ").append(label).append(", score: ").append(score).append(".");
            if (!escalationSignals.isEmpty()) {
                builder.append(" Escalation signals: ").append(String.join(", ", escalationSignals)).append(".");
            }
            return builder.toString();
        }

        private static EmotionThresholds defaultThresholds() {
            EmotionThresholds thresholds = new EmotionThresholds();
            thresholds.setAnxious(20);
            thresholds.setDissatisfied(45);
            thresholds.setAngry(85);
            return thresholds;
        }

        private static EmotionWeights defaultWeights() {
            EmotionWeights weights = new EmotionWeights();
            weights.setPunctuationTriple(8);
            weights.setPunctuationExclamation(4);
            weights.setPunctuationQuestion(4);
            weights.setHumanRequestFirst(8);
            weights.setHumanRequestRepeat(12);
            weights.setTimeout(10);
            weights.setMerchantRejected(12);
            return weights;
        }

        private static EmotionTrendPolicy defaultTrend() {
            EmotionTrendPolicy trend = new EmotionTrendPolicy();
            trend.setConsecutiveRiseTrigger(2);
            trend.setCalmToAngryEnabled(Boolean.TRUE);
            return trend;
        }

        private static int safeInt(Integer value) {
            return value == null ? 0 : value;
        }
    }
}
