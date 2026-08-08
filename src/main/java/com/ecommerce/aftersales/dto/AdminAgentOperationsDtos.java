package com.ecommerce.aftersales.dto;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/** Stable admin-facing contract for the Agent operations center. */
public final class AdminAgentOperationsDtos {

    private AdminAgentOperationsDtos() {
    }

    @Data
    public static class AgentOperationsView {
        private String dataStatus;
        private String overallStatus;
        private String generatedAt;
        private String range;
        private Integer refreshAfterSeconds;
        private String grafanaUrl;
        private List<TargetView> targets = new ArrayList<>();
        private OverviewView overview = new OverviewView();
        private List<MetricSeriesView> throughputSeries = new ArrayList<>();
        private List<MetricSeriesView> latencySeries = new ArrayList<>();
        private List<BreakdownView> ragModes = new ArrayList<>();
        private List<BreakdownView> toolFailures = new ArrayList<>();
        private List<BreakdownView> reviewVerdicts = new ArrayList<>();
        private List<BreakdownView> messageReliability = new ArrayList<>();
        private List<InsightView> insights = new ArrayList<>();
    }

    @Data
    public static class TargetView {
        private String key;
        private String label;
        private String component;
        private String status;
    }

    @Data
    public static class OverviewView {
        private Double gatewaySuccessRate;
        private Double gatewayP95Seconds;
        private Double agentP95Seconds;
        private Double toolFailureRate;
        private Double handoffRate;
        private Double requestsPerSecond;
        private Long unrepliedSessions;
        private Double dlqEvents;
    }

    @Data
    public static class MetricSeriesView {
        private String key;
        private String label;
        private String unit;
        private String tone;
        private List<MetricPointView> points = new ArrayList<>();
    }

    @Data
    public static class MetricPointView {
        private String timestamp;
        private Double value;
    }

    @Data
    public static class BreakdownView {
        private String key;
        private String label;
        private Double value;
        private Double total;
        private Double ratio;
        private String tone;
        private String detail;
    }

    @Data
    public static class InsightView {
        private String level;
        private String title;
        private String description;
    }
}
