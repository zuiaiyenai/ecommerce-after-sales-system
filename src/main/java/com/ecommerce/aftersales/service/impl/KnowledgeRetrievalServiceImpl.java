package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.ecommerce.aftersales.service.KnowledgeRetrievalService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class KnowledgeRetrievalServiceImpl implements KnowledgeRetrievalService {

    private static final int VECTOR_DIMENSIONS = 192;
    private static final int DEFAULT_TOP_K = 4;
    private static final int MAX_TOP_K = 8;
    private static final int RERANK_WINDOW = 12;
    private static final Set<String> DEFAULT_SOURCES = Set.of(
            "faq",
            "product",
            "policy",
            "scene_evidence",
            "review_interpretation"
    );

    private final AgentPolicyCatalogService agentPolicyCatalogService;

    @Override
    public AgentGatewayDtos.KnowledgeRetrieveResponse retrieve(AgentGatewayDtos.KnowledgeRetrieveRequest request) {
        String query = safeTrim(request.getQuery());
        int topK = normalizeTopK(request.getTopK());
        Set<String> enabledSources = normalizeSources(request.getSources());
        List<String> lexicalTerms = buildQueryTerms(query);
        List<String> focusTerms = buildFocusTerms(query);
        Map<String, Object> knowledgeBase = agentPolicyCatalogService.getKnowledgeBase();

        List<ScoredHit> scoredHits = new ArrayList<>();
        if (enabledSources.contains("faq")) {
            collectFaqHits(scoredHits, knowledgeBase, query, lexicalTerms);
        }
        if (enabledSources.contains("product")) {
            collectProductHits(scoredHits, knowledgeBase, query, lexicalTerms, safeTrim(request.getProductCategory()));
        }
        if (enabledSources.contains("policy")) {
            collectPolicyHits(scoredHits, knowledgeBase, query, lexicalTerms, safeTrim(request.getProductCategory()));
        }
        if (enabledSources.contains("scene_evidence")) {
            collectSceneEvidenceHits(scoredHits, knowledgeBase, query, lexicalTerms, safeTrim(request.getScene()));
        }
        if (enabledSources.contains("review_interpretation")) {
            collectReviewHits(scoredHits, knowledgeBase, query, lexicalTerms, safeTrim(request.getScene()));
        }

        scoredHits.sort((left, right) -> Double.compare(right.score(), left.score()));
        scoredHits = rerankHits(
                scoredHits,
                query,
                focusTerms,
                safeTrim(request.getProductCategory()),
                safeTrim(request.getScene())
        );

        List<AgentGatewayDtos.KnowledgeHitDto> hits = scoredHits.stream()
                .limit(topK)
                .map(ScoredHit::toHitWithScore)
                .toList();

        AgentGatewayDtos.KnowledgeRetrieveResponse response = new AgentGatewayDtos.KnowledgeRetrieveResponse();
        response.setQuery(query);
        response.setRetrieval_mode("vector_hybrid_rerank_v1");
        response.setTotal_hits(scoredHits.size());
        response.setHits(hits);

        Map<String, Object> trace = new LinkedHashMap<>();
        trace.put("knowledge_base_version", safeTrim(knowledgeBase.get("knowledge_base_version")));
        trace.put("sources", enabledSources);
        trace.put("top_k", topK);
        trace.put("vector_dimensions", VECTOR_DIMENSIONS);
        trace.put("rerank_window", Math.min(RERANK_WINDOW, scoredHits.size()));
        trace.put("pipeline", List.of("lexical", "vector", "rerank"));
        trace.put("product_category", safeTrim(request.getProductCategory()));
        trace.put("scene", safeTrim(request.getScene()));
        trace.put("intent", safeTrim(request.getIntent()));
        trace.put("merchant_code", safeTrim(request.getMerchantCode()));
        response.setTrace(trace);
        return response;
    }

    private void collectFaqHits(
            List<ScoredHit> scoredHits,
            Map<String, Object> knowledgeBase,
            String query,
            List<String> terms
    ) {
        for (Map<String, Object> row : listOfMaps(knowledgeBase.get("faq_knowledge"))) {
            String question = safeTrim(row.get("question"));
            String answer = safeTrim(row.get("answer"));
            List<String> tags = toStringList(row.get("tags"));
            double score = scoreDocument(query, terms, question, answer, String.join(" ", tags));
            if (score <= 0) {
                continue;
            }
            scoredHits.add(new ScoredHit(
                    score,
                    buildHit(
                            "faq",
                            question,
                            question,
                            answer,
                            answer,
                            score,
                            tags,
                            Map.of("question", question)
                    )
            ));
        }
    }

    private void collectProductHits(
            List<ScoredHit> scoredHits,
            Map<String, Object> knowledgeBase,
            String query,
            List<String> terms,
            String productCategory
    ) {
        for (Map<String, Object> row : listOfMaps(knowledgeBase.get("product_knowledge"))) {
            String productId = safeTrim(row.get("product_id"));
            String productName = safeTrim(row.get("product_name"));
            String title = safeTrim(row.get("title"));
            String content = safeTrim(row.get("content"));
            double score = scoreDocument(query, terms, title, content, productName, productId);
            if (StringUtils.hasText(productCategory) && content.contains(productCategory)) {
                score += 12.0;
            }
            if (score <= 0) {
                continue;
            }
            scoredHits.add(new ScoredHit(
                    score,
                    buildHit(
                            "product",
                            productId,
                            firstNonBlank(title, productName, "Product Knowledge"),
                            productName,
                            content,
                            score,
                            List.of(productName),
                            Map.of(
                                    "product_id", productId,
                                    "product_name", productName
                            )
                    )
            ));
        }
    }

    private void collectPolicyHits(
            List<ScoredHit> scoredHits,
            Map<String, Object> knowledgeBase,
            String query,
            List<String> terms,
            String productCategory
    ) {
        for (Map<String, Object> row : listOfMaps(knowledgeBase.get("after_sales_policy_knowledge"))) {
            String policyCode = safeTrim(row.get("policy_code"));
            String policyName = safeTrim(row.get("policy_name"));
            String summary = safeTrim(row.get("summary"));
            String content = safeTrim(row.get("content"));
            String category = safeTrim(row.get("product_category"));
            double score = scoreDocument(query, terms, policyName, summary + " " + content, category, policyCode);
            if (StringUtils.hasText(productCategory) && productCategory.equalsIgnoreCase(category)) {
                score += 24.0;
            }
            if (score <= 0) {
                continue;
            }
            scoredHits.add(new ScoredHit(
                    score,
                    buildHit(
                            "policy",
                            policyCode,
                            firstNonBlank(policyName, policyCode, "After-sales Policy"),
                            summary,
                            content,
                            score,
                            List.of(category),
                            Map.of(
                                    "policy_code", policyCode,
                                    "product_category", category
                            )
                    )
            ));
        }
    }

    private void collectSceneEvidenceHits(
            List<ScoredHit> scoredHits,
            Map<String, Object> knowledgeBase,
            String query,
            List<String> terms,
            String scene
    ) {
        for (Map<String, Object> row : listOfMaps(knowledgeBase.get("scene_evidence_knowledge"))) {
            String sceneCode = safeTrim(row.get("scene"));
            String label = safeTrim(row.get("label"));
            String description = safeTrim(row.get("description"));
            List<String> defaultEvidence = toStringList(row.get("default_evidence"));
            List<String> extraEvidence = toStringList(row.get("extra_evidence"));
            List<String> examples = toStringList(row.get("example_phrases"));
            String evidenceText = String.join(" ", defaultEvidence) + " " + String.join(" ", extraEvidence);
            double score = scoreDocument(query, terms, label, description + " " + evidenceText, sceneCode, String.join(" ", examples));
            if (StringUtils.hasText(scene) && scene.equalsIgnoreCase(sceneCode)) {
                score += 28.0;
            }
            if (score <= 0) {
                continue;
            }
            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("scene", sceneCode);
            metadata.put("default_evidence", defaultEvidence);
            metadata.put("extra_evidence", extraEvidence);
            metadata.put("example_phrases", examples);
            scoredHits.add(new ScoredHit(
                    score,
                    buildHit(
                            "scene_evidence",
                            sceneCode,
                            firstNonBlank(label, sceneCode, "Evidence Guidance"),
                            description,
                            evidenceText,
                            score,
                            defaultEvidence,
                            metadata
                    )
            ));
        }
    }

    private void collectReviewHits(
            List<ScoredHit> scoredHits,
            Map<String, Object> knowledgeBase,
            String query,
            List<String> terms,
            String scene
    ) {
        for (Map<String, Object> row : listOfMaps(knowledgeBase.get("review_interpretation_knowledge"))) {
            String code = safeTrim(row.get("code"));
            String sentiment = safeTrim(row.get("sentiment"));
            String sceneCode = firstNonBlank(safeTrim(row.get("scene_code")), safeTrim(row.get("scene")));
            String meaning = safeTrim(row.get("meaning"));
            String strategy = safeTrim(row.get("response_strategy"));
            List<String> examples = toStringList(row.get("example_phrases"));
            double score = scoreDocument(query, terms, sentiment + " " + sceneCode, meaning + " " + strategy, code, String.join(" ", examples));
            if (StringUtils.hasText(scene) && scene.equalsIgnoreCase(sceneCode)) {
                score += 18.0;
            }
            if (score <= 0) {
                continue;
            }
            scoredHits.add(new ScoredHit(
                    score,
                    buildHit(
                            "review_interpretation",
                            code,
                            firstNonBlank(meaning, code, "Review Interpretation"),
                            strategy,
                            String.join(" ", examples),
                            score,
                            List.of(sentiment, sceneCode),
                            Map.of(
                                    "code", code,
                                    "sentiment", sentiment,
                                    "scene", sceneCode
                            )
                    )
            ));
        }
    }

    private List<ScoredHit> rerankHits(
            List<ScoredHit> scoredHits,
            String query,
            List<String> focusTerms,
            String productCategory,
            String scene
    ) {
        if (scoredHits.isEmpty()) {
            return scoredHits;
        }
        int window = Math.min(RERANK_WINDOW, scoredHits.size());
        List<ScoredHit> reranked = new ArrayList<>(scoredHits.size());
        for (int index = 0; index < window; index++) {
            ScoredHit current = scoredHits.get(index);
            double rerankScore = rerankScore(current.hit(), current.score(), query, focusTerms, productCategory, scene);
            reranked.add(new ScoredHit(rerankScore, current.hit()));
        }
        reranked.sort((left, right) -> Double.compare(right.score(), left.score()));
        reranked.addAll(scoredHits.subList(window, scoredHits.size()));
        return reranked;
    }

    private double rerankScore(
            AgentGatewayDtos.KnowledgeHitDto hit,
            double baseScore,
            String query,
            List<String> focusTerms,
            String productCategory,
            String scene
    ) {
        String title = safeTrim(hit.getTitle());
        String summary = safeTrim(hit.getSummary());
        String snippet = safeTrim(hit.getSnippet());
        String normalizedQuery = normalizeText(query);
        String titleText = normalizeText(title);
        String summaryText = normalizeText(summary);
        String snippetText = normalizeText(snippet);
        String metadataText = normalizeText(flattenMetadata(hit.getMetadata()));

        int matchedTerms = 0;
        for (String term : focusTerms) {
            if (containsAny(term, titleText, summaryText, snippetText, metadataText)) {
                matchedTerms++;
            }
        }
        double coverage = focusTerms.isEmpty() ? 0.0 : (double) matchedTerms / focusTerms.size();
        double vectorScore = vectorSimilarity(query, title, summary + " " + snippet, flattenMetadata(hit.getMetadata()));

        double rerank = baseScore;
        rerank += coverage * 30.0;
        rerank += vectorScore * 22.0;
        if (StringUtils.hasText(normalizedQuery) && titleText.contains(normalizedQuery)) {
            rerank += 16.0;
        }
        if (StringUtils.hasText(normalizedQuery) && summaryText.contains(normalizedQuery)) {
            rerank += 10.0;
        }

        String hitCategory = safeTrim(hit.getMetadata() == null ? null : hit.getMetadata().get("product_category"));
        String hitScene = safeTrim(hit.getMetadata() == null ? null : hit.getMetadata().get("scene"));
        if (StringUtils.hasText(productCategory) && productCategory.equalsIgnoreCase(hitCategory)) {
            rerank += 12.0;
        }
        if (StringUtils.hasText(scene) && scene.equalsIgnoreCase(hitScene)) {
            rerank += 14.0;
        }
        if ("faq".equalsIgnoreCase(hit.getSource_type()) && isQuestionLike(query)) {
            rerank += 8.0;
        }
        return rerank;
    }

    private AgentGatewayDtos.KnowledgeHitDto buildHit(
            String sourceType,
            String sourceCode,
            String title,
            String summary,
            String content,
            double score,
            List<String> tags,
            Map<String, Object> metadata
    ) {
        AgentGatewayDtos.KnowledgeHitDto hit = new AgentGatewayDtos.KnowledgeHitDto();
        hit.setSource_type(sourceType);
        hit.setSource_code(sourceCode);
        hit.setTitle(title);
        hit.setSummary(truncate(summary, 120));
        hit.setSnippet(truncate(content, 180));
        hit.setScore(roundScore(score));
        hit.setTags(tags);
        hit.setMetadata(metadata);
        return hit;
    }

    private double scoreDocument(
            String query,
            List<String> terms,
            String title,
            String content,
            String... metadata
    ) {
        String titleText = normalizeText(title);
        String contentText = normalizeText(content);
        String metadataText = normalizeText(String.join(" ", metadata));
        if (!StringUtils.hasText(titleText) && !StringUtils.hasText(contentText) && !StringUtils.hasText(metadataText)) {
            return 0.0;
        }

        double lexicalScore = 0.0;
        if (StringUtils.hasText(query)) {
            String normalizedQuery = normalizeText(query);
            if (titleText.contains(normalizedQuery)) {
                lexicalScore += 120.0;
            }
            if (contentText.contains(normalizedQuery)) {
                lexicalScore += 90.0;
            }
            if (metadataText.contains(normalizedQuery)) {
                lexicalScore += 65.0;
            }
        }

        for (String term : terms) {
            if (term.length() < 2) {
                continue;
            }
            if (titleText.contains(term)) {
                lexicalScore += Math.min(24.0, term.length() * 4.0);
            }
            if (contentText.contains(term)) {
                lexicalScore += Math.min(16.0, term.length() * 2.5);
            }
            if (metadataText.contains(term)) {
                lexicalScore += Math.min(18.0, term.length() * 3.0);
            }
        }

        double vectorScore = vectorSimilarity(query, title, content, String.join(" ", metadata));
        return lexicalScore * 0.58 + vectorScore * 100.0 * 0.82;
    }

    private static String normalizeText(String value) {
        return safeTrim(value)
                .toLowerCase(Locale.ROOT)
                .replaceAll("[\\p{Punct}\\p{IsPunctuation}]+", " ")
                .replace('/', ' ')
                .replace('|', ' ')
                .replaceAll("\\s+", " ")
                .trim();
    }

    private static List<String> buildQueryTerms(String query) {
        LinkedHashSet<String> terms = new LinkedHashSet<>();
        String normalized = normalizeText(query);
        if (!StringUtils.hasText(normalized)) {
            return List.of();
        }
        terms.add(normalized);
        for (String token : normalized.split("\\s+")) {
            if (token.length() >= 2) {
                terms.add(token);
            }
            if (token.length() >= 4 && token.length() <= 12) {
                for (int index = 0; index <= token.length() - 2; index++) {
                    String bigram = token.substring(index, index + 2);
                    if (bigram.trim().length() == 2) {
                        terms.add(bigram);
                    }
                }
            }
        }
        return List.copyOf(terms);
    }

    private static List<String> buildFocusTerms(String query) {
        LinkedHashSet<String> terms = new LinkedHashSet<>();
        String normalized = normalizeText(query);
        if (!StringUtils.hasText(normalized)) {
            return List.of();
        }
        for (String token : normalized.split("\\s+")) {
            if (token.length() >= 2) {
                terms.add(token);
            }
        }
        String compact = normalized.replace(" ", "");
        for (int ngramSize = 2; ngramSize <= 3; ngramSize++) {
            if (compact.length() < ngramSize) {
                continue;
            }
            for (int index = 0; index <= compact.length() - ngramSize; index++) {
                terms.add(compact.substring(index, index + ngramSize));
                if (terms.size() >= 12) {
                    return List.copyOf(terms);
                }
            }
        }
        return List.copyOf(terms);
    }

    private static Set<String> normalizeSources(List<String> requestedSources) {
        if (requestedSources == null || requestedSources.isEmpty()) {
            return DEFAULT_SOURCES;
        }
        LinkedHashSet<String> normalized = new LinkedHashSet<>();
        for (String value : requestedSources) {
            String source = safeTrim(value).toLowerCase(Locale.ROOT);
            if (DEFAULT_SOURCES.contains(source)) {
                normalized.add(source);
            }
        }
        return normalized.isEmpty() ? DEFAULT_SOURCES : normalized;
    }

    private static int normalizeTopK(Integer topK) {
        if (topK == null) {
            return DEFAULT_TOP_K;
        }
        return Math.max(1, Math.min(topK, MAX_TOP_K));
    }

    private static List<Map<String, Object>> listOfMaps(Object raw) {
        if (!(raw instanceof Collection<?> items)) {
            return List.of();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Object item : items) {
            if (item instanceof Map<?, ?> map) {
                Map<String, Object> row = new LinkedHashMap<>();
                for (Map.Entry<?, ?> entry : map.entrySet()) {
                    row.put(String.valueOf(entry.getKey()), entry.getValue());
                }
                rows.add(row);
            }
        }
        return rows;
    }

    private static List<String> toStringList(Object raw) {
        if (raw instanceof Collection<?> items) {
            List<String> values = new ArrayList<>();
            for (Object item : items) {
                String text = safeTrim(item);
                if (StringUtils.hasText(text)) {
                    values.add(text);
                }
            }
            return values;
        }
        String text = safeTrim(raw);
        return StringUtils.hasText(text) ? List.of(text) : List.of();
    }

    private static String truncate(String value, int limit) {
        String text = safeTrim(value);
        if (text.length() <= limit) {
            return text;
        }
        return text.substring(0, limit) + "...";
    }

    private static String firstNonBlank(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return "";
    }

    private static Double roundScore(double score) {
        return Math.round(score * 10.0) / 10.0;
    }

    private static boolean containsAny(String term, String... haystacks) {
        if (!StringUtils.hasText(term)) {
            return false;
        }
        for (String haystack : haystacks) {
            if (StringUtils.hasText(haystack) && haystack.contains(term)) {
                return true;
            }
        }
        return false;
    }

    private static boolean isQuestionLike(String query) {
        String text = safeTrim(query);
        return text.contains("?") || text.contains("？") || text.contains("多久") || text.contains("怎么");
    }

    private static String flattenMetadata(Map<String, Object> metadata) {
        if (metadata == null || metadata.isEmpty()) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        for (Map.Entry<String, Object> entry : metadata.entrySet()) {
            builder.append(' ').append(safeTrim(entry.getKey())).append(' ').append(safeTrim(entry.getValue()));
        }
        return builder.toString();
    }

    private static double vectorSimilarity(
            String query,
            String title,
            String content,
            String metadata
    ) {
        String normalizedQuery = normalizeText(query);
        if (!StringUtils.hasText(normalizedQuery)) {
            return 0.0;
        }
        double[] queryVector = vectorize(normalizedQuery);
        double[] documentVector = vectorize(
                normalizeText(title) + " " + normalizeText(content) + " " + normalizeText(metadata)
        );
        return cosineSimilarity(queryVector, documentVector);
    }

    private static double[] vectorize(String text) {
        double[] vector = new double[VECTOR_DIMENSIONS];
        String normalized = normalizeText(text);
        if (!StringUtils.hasText(normalized)) {
            return vector;
        }

        for (String token : normalized.split("\\s+")) {
            if (token.length() >= 2) {
                addFeature(vector, token, 2.2);
            }
        }

        String compact = normalized.replace(" ", "");
        for (int ngramSize = 2; ngramSize <= 3; ngramSize++) {
            if (compact.length() < ngramSize) {
                continue;
            }
            double weight = ngramSize == 2 ? 1.2 : 0.9;
            for (int index = 0; index <= compact.length() - ngramSize; index++) {
                addFeature(vector, compact.substring(index, index + ngramSize), weight);
            }
        }
        return vector;
    }

    private static void addFeature(double[] vector, String feature, double weight) {
        int slot = Math.floorMod(feature.hashCode(), VECTOR_DIMENSIONS);
        vector[slot] += weight;
    }

    private static double cosineSimilarity(double[] left, double[] right) {
        double dot = 0.0;
        double leftNorm = 0.0;
        double rightNorm = 0.0;
        for (int index = 0; index < VECTOR_DIMENSIONS; index++) {
            dot += left[index] * right[index];
            leftNorm += left[index] * left[index];
            rightNorm += right[index] * right[index];
        }
        if (leftNorm <= 0.0 || rightNorm <= 0.0) {
            return 0.0;
        }
        return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
    }

    private static String safeTrim(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private record ScoredHit(double score, AgentGatewayDtos.KnowledgeHitDto hit) {
        private AgentGatewayDtos.KnowledgeHitDto toHitWithScore() {
            hit.setScore(roundScore(score));
            return hit;
        }
    }
}
