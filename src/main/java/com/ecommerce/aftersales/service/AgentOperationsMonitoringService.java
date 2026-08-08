package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.AgentOperationsView;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.BreakdownView;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.InsightView;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.MetricPointView;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.MetricSeriesView;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.OverviewView;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.TargetView;
import com.ecommerce.aftersales.service.PrometheusQueryClient.MatrixSeries;
import com.ecommerce.aftersales.service.PrometheusQueryClient.PrometheusUnavailableException;
import com.ecommerce.aftersales.service.PrometheusQueryClient.VectorSample;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** Aggregates a fixed, low-cardinality monitoring view for platform administrators. */
@Slf4j
@Service
public class AgentOperationsMonitoringService {

    private static final String TARGET_QUERY = "up{job=~\"ecommerce-java|ecommerce-python-agent\"}";
    private static final String GATEWAY_THROUGHPUT_QUERY =
            "sum by (outcome) (rate(agent_gateway_requests_total[5m]))";
    private static final String JAVA_P95_QUERY =
            "histogram_quantile(0.95, sum by (le) (rate(agent_gateway_duration_seconds_bucket[5m])))";
    private static final String AGENT_P95_QUERY =
            "histogram_quantile(0.95, sum by (le) (rate(agent_request_duration_seconds_bucket[5m])))";
    private static final String UNREPLIED_QUERY = "sum(agent_merchant_queue_unreplied)";

    private final PrometheusQueryClient prometheus;
    private final String grafanaUrl;

    public AgentOperationsMonitoringService(
            PrometheusQueryClient prometheus,
            @Value("${app.observability.grafana-agent-url:http://localhost:3000/d/ecommerce-agent-overview/ecommerce-after-sales-agent-overview}")
            String grafanaUrl) {
        this.prometheus = prometheus;
        this.grafanaUrl = grafanaUrl;
    }

    public AgentOperationsView load(String requestedRange) {
        RangeWindow window = RangeWindow.from(requestedRange);
        Instant end = Instant.now().truncatedTo(ChronoUnit.SECONDS);
        Instant start = end.minusSeconds(window.seconds());
        try {
            List<VectorSample> targets = prometheus.query(TARGET_QUERY);
            List<VectorSample> chatRequests = prometheus.query(increase("agent_chat_requests_total", window.prometheusRange()));
            List<VectorSample> handoffs = prometheus.query(increase("agent_chat_handoffs_total", window.prometheusRange()));
            List<VectorSample> unreplied = prometheus.query(UNREPLIED_QUERY);
            List<VectorSample> ragModes = prometheus.query(groupedIncrease("agent_rag_retrievals_total", "mode", window.prometheusRange()));
            List<VectorSample> tools = prometheus.query(groupedIncrease("agent_tool_calls_total", "tool, outcome", window.prometheusRange()));
            List<VectorSample> verdicts = prometheus.query(groupedIncrease("agent_review_verdicts_total", "verdict", window.prometheusRange()));
            List<VectorSample> outbox = prometheus.query(groupedIncrease("agent_outbox_publishes_total", "status", window.prometheusRange()));
            List<VectorSample> dlq = prometheus.query(groupedIncrease("agent_kafka_dlq_events_total", "stage", window.prometheusRange()));
            List<MatrixSeries> throughput = prometheus.queryRange(
                    GATEWAY_THROUGHPUT_QUERY, start.getEpochSecond(), end.getEpochSecond(), window.stepSeconds());
            List<MatrixSeries> javaLatency = prometheus.queryRange(
                    JAVA_P95_QUERY, start.getEpochSecond(), end.getEpochSecond(), window.stepSeconds());
            List<MatrixSeries> agentLatency = prometheus.queryRange(
                    AGENT_P95_QUERY, start.getEpochSecond(), end.getEpochSecond(), window.stepSeconds());

            return assemble(window, end, targets, chatRequests, handoffs, unreplied, ragModes, tools,
                    verdicts, outbox, dlq, throughput, javaLatency, agentLatency);
        } catch (PrometheusUnavailableException exception) {
            log.warn("agent_operations_monitoring data_status=unavailable reason={}", exception.getMessage());
            return unavailable(window, end);
        }
    }

    private AgentOperationsView assemble(
            RangeWindow window,
            Instant generatedAt,
            List<VectorSample> targetSamples,
            List<VectorSample> chatRequests,
            List<VectorSample> handoffs,
            List<VectorSample> unreplied,
            List<VectorSample> ragSamples,
            List<VectorSample> toolSamples,
            List<VectorSample> verdictSamples,
            List<VectorSample> outboxSamples,
            List<VectorSample> dlqSamples,
            List<MatrixSeries> throughput,
            List<MatrixSeries> javaLatency,
            List<MatrixSeries> agentLatency) {
        AgentOperationsView view = baseView(window, generatedAt);
        view.setDataStatus("AVAILABLE");
        view.setTargets(targets(targetSamples));
        view.setThroughputSeries(toLabelledSeries(throughput, "outcome", "requests_per_second"));

        List<MetricSeriesView> latencySeries = new ArrayList<>();
        latencySeries.add(toSingleSeries("java_gateway_p95", "Java 网关 P95", "seconds", "blue", javaLatency));
        latencySeries.add(toSingleSeries("python_agent_p95", "Python Agent P95", "seconds", "orange", agentLatency));
        view.setLatencySeries(latencySeries);

        List<BreakdownView> ragModes = simpleBreakdown(ragSamples, "mode", "rag");
        List<BreakdownView> toolFailures = toolFailureBreakdown(toolSamples);
        List<BreakdownView> reviewVerdicts = simpleBreakdown(verdictSamples, "verdict", "review");
        List<BreakdownView> reliability = reliabilityBreakdown(outboxSamples, dlqSamples);
        view.setRagModes(ragModes);
        view.setToolFailures(toolFailures);
        view.setReviewVerdicts(reviewVerdicts);
        view.setMessageReliability(reliability);

        OverviewView overview = overview(throughput, javaLatency, agentLatency, toolSamples, chatRequests,
                handoffs, unreplied, dlqSamples);
        view.setOverview(overview);
        view.setInsights(insights(view.getTargets(), overview, ragModes, reliability));
        view.setOverallStatus(overallStatus(view.getTargets(), overview, ragModes, reliability));
        return view;
    }

    private AgentOperationsView unavailable(RangeWindow window, Instant generatedAt) {
        AgentOperationsView view = baseView(window, generatedAt);
        view.setDataStatus("UNAVAILABLE");
        view.setOverallStatus("UNAVAILABLE");
        view.setTargets(List.of(
                target("ecommerce-java", "Java 业务网关", "java-backend", "UNKNOWN"),
                target("ecommerce-python-agent", "Python Agent", "python-agent", "UNKNOWN")
        ));
        view.setInsights(List.of(insight(
                "warning",
                "监控数据暂不可用",
                "Java 业务接口仍可独立运行；请检查 Prometheus 容器和采集目标后重试。"
        )));
        return view;
    }

    private AgentOperationsView baseView(RangeWindow window, Instant generatedAt) {
        AgentOperationsView view = new AgentOperationsView();
        view.setGeneratedAt(generatedAt.toString());
        view.setRange(window.key());
        view.setRefreshAfterSeconds(15);
        view.setGrafanaUrl(grafanaUrl);
        return view;
    }

    private OverviewView overview(
            List<MatrixSeries> throughput,
            List<MatrixSeries> javaLatency,
            List<MatrixSeries> agentLatency,
            List<VectorSample> tools,
            List<VectorSample> chatRequests,
            List<VectorSample> handoffs,
            List<VectorSample> unreplied,
            List<VectorSample> dlq) {
        OverviewView overview = new OverviewView();
        Map<String, Double> latestRates = latestByLabel(throughput, "outcome");
        double requestRate = latestRates.values().stream().mapToDouble(Double::doubleValue).sum();
        overview.setRequestsPerSecond(requestRate);
        overview.setGatewaySuccessRate(requestRate > 0D
                ? latestRates.getOrDefault("success", 0D) / requestRate
                : null);
        overview.setGatewayP95Seconds(latestValue(javaLatency).orElse(null));
        overview.setAgentP95Seconds(latestValue(agentLatency).orElse(null));

        double toolTotal = tools.stream().mapToDouble(VectorSample::value).sum();
        double toolFailures = tools.stream()
                .filter(sample -> "failure".equals(sample.labels().get("outcome")))
                .mapToDouble(VectorSample::value)
                .sum();
        overview.setToolFailureRate(toolTotal > 0D ? toolFailures / toolTotal : null);

        double chatTotal = sum(chatRequests);
        overview.setHandoffRate(chatTotal > 0D ? sum(handoffs) / chatTotal : null);
        overview.setUnrepliedSessions(Math.round(sum(unreplied)));
        overview.setDlqEvents(sum(dlq));
        return overview;
    }

    private List<TargetView> targets(List<VectorSample> samples) {
        Map<String, VectorSample> byJob = new LinkedHashMap<>();
        samples.forEach(sample -> byJob.put(sample.labels().getOrDefault("job", ""), sample));
        return List.of(
                targetFromSample("ecommerce-java", "Java 业务网关", "java-backend", byJob.get("ecommerce-java")),
                targetFromSample("ecommerce-python-agent", "Python Agent", "python-agent", byJob.get("ecommerce-python-agent"))
        );
    }

    private TargetView targetFromSample(String key, String label, String component, VectorSample sample) {
        return target(key, label, component, sample == null ? "UNKNOWN" : sample.value() >= 1D ? "UP" : "DOWN");
    }

    private TargetView target(String key, String label, String component, String status) {
        TargetView view = new TargetView();
        view.setKey(key);
        view.setLabel(label);
        view.setComponent(component);
        view.setStatus(status);
        return view;
    }

    private List<MetricSeriesView> toLabelledSeries(List<MatrixSeries> source, String labelName, String unit) {
        List<MetricSeriesView> result = new ArrayList<>();
        for (MatrixSeries item : source) {
            String key = item.labels().getOrDefault(labelName, "unknown");
            MetricSeriesView series = new MetricSeriesView();
            series.setKey(key);
            series.setLabel(outcomeLabel(key));
            series.setUnit(unit);
            series.setTone(outcomeTone(key));
            series.setPoints(points(item));
            result.add(series);
        }
        result.sort(Comparator.comparingInt(item -> outcomeOrder(item.getKey())));
        return result;
    }

    private MetricSeriesView toSingleSeries(String key, String label, String unit, String tone,
                                             List<MatrixSeries> source) {
        MetricSeriesView series = new MetricSeriesView();
        series.setKey(key);
        series.setLabel(label);
        series.setUnit(unit);
        series.setTone(tone);
        series.setPoints(source.isEmpty() ? List.of() : points(source.getFirst()));
        return series;
    }

    private List<MetricPointView> points(MatrixSeries series) {
        return series.points().stream().map(point -> {
            MetricPointView view = new MetricPointView();
            view.setTimestamp(Instant.ofEpochSecond(point.epochSecond()).toString());
            view.setValue(point.value());
            return view;
        }).toList();
    }

    private List<BreakdownView> simpleBreakdown(List<VectorSample> samples, String labelName, String category) {
        double total = sum(samples);
        return samples.stream()
                .filter(sample -> sample.value() > 0D)
                .map(sample -> breakdown(
                        sample.labels().getOrDefault(labelName, "unknown"),
                        breakdownLabel(category, sample.labels().getOrDefault(labelName, "unknown")),
                        sample.value(),
                        total,
                        breakdownTone(category, sample.labels().getOrDefault(labelName, "unknown")),
                        null))
                .sorted(Comparator.comparing(BreakdownView::getValue).reversed())
                .toList();
    }

    private List<BreakdownView> toolFailureBreakdown(List<VectorSample> samples) {
        Map<String, Double> totals = new LinkedHashMap<>();
        Map<String, Double> failures = new LinkedHashMap<>();
        for (VectorSample sample : samples) {
            String tool = sample.labels().getOrDefault("tool", "unknown");
            totals.merge(tool, sample.value(), Double::sum);
            if ("failure".equals(sample.labels().get("outcome"))) {
                failures.merge(tool, sample.value(), Double::sum);
            }
        }
        return failures.entrySet().stream()
                .filter(entry -> entry.getValue() > 0D)
                .map(entry -> breakdown(
                        entry.getKey(),
                        readableTechnicalName(entry.getKey()),
                        entry.getValue(),
                        totals.getOrDefault(entry.getKey(), entry.getValue()),
                        "danger",
                        "失败调用 / 该工具全部调用"))
                .sorted(Comparator.comparing(BreakdownView::getValue).reversed())
                .toList();
    }

    private List<BreakdownView> reliabilityBreakdown(List<VectorSample> outbox, List<VectorSample> dlq) {
        List<BreakdownView> result = new ArrayList<>();
        double outboxTotal = sum(outbox);
        for (VectorSample sample : outbox) {
            String status = sample.labels().getOrDefault("status", "unknown");
            if (sample.value() <= 0D) {
                continue;
            }
            result.add(breakdown(
                    "outbox_" + status,
                    breakdownLabel("outbox", status),
                    sample.value(),
                    outboxTotal,
                    breakdownTone("outbox", status),
                    "Outbox 事件投递"));
        }
        double dlqTotal = sum(dlq);
        if (dlqTotal > 0D) {
            result.add(breakdown("dlq", "进入 DLQ", dlqTotal, dlqTotal, "danger", "需人工排查或重放"));
        }
        result.sort(Comparator.comparing(BreakdownView::getValue).reversed());
        return result;
    }

    private BreakdownView breakdown(String key, String label, double value, double total, String tone, String detail) {
        BreakdownView view = new BreakdownView();
        view.setKey(key);
        view.setLabel(label);
        view.setValue(value);
        view.setTotal(total);
        view.setRatio(total > 0D ? value / total : null);
        view.setTone(tone);
        view.setDetail(detail);
        return view;
    }

    private List<InsightView> insights(List<TargetView> targets, OverviewView overview,
                                       List<BreakdownView> ragModes, List<BreakdownView> reliability) {
        List<InsightView> insights = new ArrayList<>();
        targets.stream()
                .filter(target -> !"UP".equals(target.getStatus()))
                .forEach(target -> insights.add(insight(
                        "critical", target.getLabel() + "采集异常", "Prometheus 当前未能确认该组件在线。")));
        if (overview.getGatewaySuccessRate() != null && overview.getGatewaySuccessRate() < 0.95D) {
            insights.add(insight("warning", "Agent 网关成功率偏低", "近 5 分钟成功率低于 95%，建议结合失败日志定位。"));
        }
        if (overview.getToolFailureRate() != null && overview.getToolFailureRate() > 0.10D) {
            insights.add(insight("warning", "工具调用失败偏高", "所选时间范围内工具失败率超过 10%。"));
        }
        double ragTotal = ragModes.stream().mapToDouble(BreakdownView::getValue).sum();
        double fallbackTotal = ragModes.stream()
                .filter(item -> !"pgvector".equals(item.getKey()))
                .mapToDouble(BreakdownView::getValue)
                .sum();
        if (ragTotal > 0D && fallbackTotal / ragTotal > 0.20D) {
            insights.add(insight("warning", "RAG 降级占比偏高", "超过 20% 的检索未走标准 pgvector 路径。"));
        }
        boolean hasDlq = reliability.stream().anyMatch(item -> "dlq".equals(item.getKey()) && item.getValue() > 0D);
        if (hasDlq) {
            insights.add(insight("critical", "发现 DLQ 事件", "异步 AI 初审存在未自动恢复的消息，请检查重放与人工兜底。"));
        }
        if (insights.isEmpty()) {
            insights.add(insight("healthy", "Agent 链路运行平稳", "当前采集目标、网关、RAG 和异步消息链路未发现显著异常。"));
        }
        return insights;
    }

    private String overallStatus(List<TargetView> targets, OverviewView overview,
                                 List<BreakdownView> ragModes, List<BreakdownView> reliability) {
        if (targets.stream().anyMatch(target -> !"UP".equals(target.getStatus()))) {
            return "CRITICAL";
        }
        boolean dlq = reliability.stream().anyMatch(item -> "dlq".equals(item.getKey()) && item.getValue() > 0D);
        double ragTotal = ragModes.stream().mapToDouble(BreakdownView::getValue).sum();
        double fallback = ragModes.stream().filter(item -> !"pgvector".equals(item.getKey()))
                .mapToDouble(BreakdownView::getValue).sum();
        boolean needsAttention = dlq
                || overview.getGatewaySuccessRate() != null && overview.getGatewaySuccessRate() < 0.95D
                || overview.getToolFailureRate() != null && overview.getToolFailureRate() > 0.10D
                || ragTotal > 0D && fallback / ragTotal > 0.20D;
        return needsAttention ? "ATTENTION" : "HEALTHY";
    }

    private InsightView insight(String level, String title, String description) {
        InsightView view = new InsightView();
        view.setLevel(level);
        view.setTitle(title);
        view.setDescription(description);
        return view;
    }

    private static Map<String, Double> latestByLabel(List<MatrixSeries> source, String label) {
        Map<String, Double> values = new LinkedHashMap<>();
        for (MatrixSeries series : source) {
            latestValue(List.of(series)).ifPresent(value ->
                    values.put(series.labels().getOrDefault(label, "unknown"), value));
        }
        return values;
    }

    private static Optional<Double> latestValue(List<MatrixSeries> source) {
        if (source.isEmpty() || source.getFirst().points().isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(source.getFirst().points().getLast().value());
    }

    private static double sum(List<VectorSample> samples) {
        return samples.stream().mapToDouble(VectorSample::value).sum();
    }

    private static String increase(String metric, String range) {
        return "sum(increase(" + metric + "[" + range + "]))";
    }

    private static String groupedIncrease(String metric, String labels, String range) {
        return "sum by (" + labels + ") (increase(" + metric + "[" + range + "]))";
    }

    private static String outcomeLabel(String outcome) {
        return switch (outcome) {
            case "success" -> "成功";
            case "failure" -> "失败";
            case "rejected" -> "限流拒绝";
            default -> readableTechnicalName(outcome);
        };
    }

    private static String outcomeTone(String outcome) {
        return switch (outcome) {
            case "success" -> "green";
            case "failure" -> "red";
            case "rejected" -> "amber";
            default -> "slate";
        };
    }

    private static int outcomeOrder(String outcome) {
        return switch (outcome) {
            case "success" -> 0;
            case "failure" -> 1;
            case "rejected" -> 2;
            default -> 3;
        };
    }

    private static String breakdownLabel(String category, String value) {
        return switch (category + ":" + value) {
            case "rag:pgvector" -> "pgvector 向量检索";
            case "rag:lexical_fallback" -> "关键词兜底";
            case "rag:lexical_fallback_after_embedding_error" -> "Embedding 异常后降级";
            case "review:approve" -> "自动通过";
            case "review:reject" -> "自动拒绝";
            case "review:manual_required" -> "转人工审核";
            case "review:supplement_required" -> "要求补充材料";
            case "outbox:published" -> "Outbox 已投递";
            case "outbox:failed" -> "Outbox 重试中";
            case "outbox:dead" -> "Outbox 已终止";
            default -> readableTechnicalName(value);
        };
    }

    private static String breakdownTone(String category, String value) {
        if ("rag".equals(category)) {
            return "pgvector".equals(value) ? "green" : "amber";
        }
        if ("outbox".equals(category)) {
            return "published".equals(value) ? "green" : "dead".equals(value) ? "red" : "amber";
        }
        if ("review".equals(category)) {
            return "approve".equals(value) ? "green" : "manual_required".equals(value) ? "amber" : "blue";
        }
        return "slate";
    }

    private static String readableTechnicalName(String value) {
        if (value == null || value.isBlank()) {
            return "未知";
        }
        String normalized = value.replace('_', ' ').replace('-', ' ').trim();
        return normalized.substring(0, 1).toUpperCase() + normalized.substring(1);
    }

    private record RangeWindow(String key, String prometheusRange, long seconds, int stepSeconds) {
        private static RangeWindow from(String requested) {
            return switch (requested == null ? "" : requested.trim().toLowerCase()) {
                case "6h" -> new RangeWindow("6h", "6h", 21_600L, 120);
                case "24h" -> new RangeWindow("24h", "24h", 86_400L, 300);
                default -> new RangeWindow("1h", "1h", 3_600L, 30);
            };
        }
    }
}
