package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.AgentOperationsView;
import com.ecommerce.aftersales.service.PrometheusQueryClient.DataPoint;
import com.ecommerce.aftersales.service.PrometheusQueryClient.MatrixSeries;
import com.ecommerce.aftersales.service.PrometheusQueryClient.PrometheusUnavailableException;
import com.ecommerce.aftersales.service.PrometheusQueryClient.VectorSample;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AgentOperationsMonitoringServiceTest {

    @Test
    void aggregatesPrometheusMetricsIntoAStableAdminView() {
        PrometheusQueryClient client = mock(PrometheusQueryClient.class);
        when(client.query(anyString())).thenAnswer(invocation -> vectorResponse(invocation.getArgument(0)));
        when(client.queryRange(anyString(), anyLong(), anyLong(), anyInt()))
                .thenAnswer(invocation -> matrixResponse(invocation.getArgument(0)));
        AgentOperationsMonitoringService service = new AgentOperationsMonitoringService(client, "http://localhost:3000/agent");

        AgentOperationsView view = service.load("6h");

        assertThat(view.getDataStatus()).isEqualTo("AVAILABLE");
        assertThat(view.getOverallStatus()).isEqualTo("HEALTHY");
        assertThat(view.getRange()).isEqualTo("6h");
        assertThat(view.getTargets()).extracting("status").containsExactly("UP", "UP");
        assertThat(view.getOverview().getGatewaySuccessRate()).isEqualTo(0.99D);
        assertThat(view.getOverview().getGatewayP95Seconds()).isEqualTo(0.8D);
        assertThat(view.getOverview().getAgentP95Seconds()).isEqualTo(0.6D);
        assertThat(view.getOverview().getHandoffRate()).isEqualTo(0.2D);
        assertThat(view.getOverview().getUnrepliedSessions()).isEqualTo(4L);
        assertThat(view.getRagModes()).extracting("key").containsExactlyInAnyOrder("pgvector", "lexical_fallback");
        assertThat(view.getToolFailures()).isEmpty();
        assertThat(view.getInsights()).singleElement().extracting("level").isEqualTo("healthy");
    }

    @Test
    void returnsExplicitUnavailableStateWithoutFabricatingMetrics() {
        PrometheusQueryClient client = mock(PrometheusQueryClient.class);
        when(client.query(anyString())).thenThrow(new PrometheusUnavailableException("connection refused"));
        AgentOperationsMonitoringService service = new AgentOperationsMonitoringService(client, "http://localhost:3000/agent");

        AgentOperationsView view = service.load("unsupported");

        assertThat(view.getDataStatus()).isEqualTo("UNAVAILABLE");
        assertThat(view.getOverallStatus()).isEqualTo("UNAVAILABLE");
        assertThat(view.getRange()).isEqualTo("1h");
        assertThat(view.getOverview().getGatewaySuccessRate()).isNull();
        assertThat(view.getThroughputSeries()).isEmpty();
        assertThat(view.getTargets()).extracting("status").containsOnly("UNKNOWN");
        assertThat(view.getInsights()).singleElement().extracting("title").isEqualTo("监控数据暂不可用");
    }

    private List<VectorSample> vectorResponse(String query) {
        if (query.startsWith("up{")) {
            return List.of(
                    sample(Map.of("job", "ecommerce-java"), 1D),
                    sample(Map.of("job", "ecommerce-python-agent"), 1D)
            );
        }
        if (query.contains("agent_chat_requests_total")) {
            return List.of(sample(Map.of(), 10D));
        }
        if (query.contains("agent_chat_handoffs_total")) {
            return List.of(sample(Map.of(), 2D));
        }
        if (query.contains("agent_merchant_queue_unreplied")) {
            return List.of(sample(Map.of(), 4D));
        }
        if (query.contains("agent_rag_retrievals_total")) {
            return List.of(
                    sample(Map.of("mode", "pgvector"), 9D),
                    sample(Map.of("mode", "lexical_fallback"), 1D)
            );
        }
        if (query.contains("agent_tool_calls_total")) {
            return List.of(sample(Map.of("tool", "lookup_order", "outcome", "success"), 8D));
        }
        if (query.contains("agent_review_verdicts_total")) {
            return List.of(sample(Map.of("verdict", "approve"), 3D));
        }
        if (query.contains("agent_outbox_publishes_total")) {
            return List.of(sample(Map.of("status", "published"), 3D));
        }
        return List.of();
    }

    private List<MatrixSeries> matrixResponse(String query) {
        long now = Instant.now().getEpochSecond();
        if (query.contains("agent_gateway_requests_total")) {
            return List.of(
                    series(Map.of("outcome", "success"), now, 0.98D, 0.99D),
                    series(Map.of("outcome", "failure"), now, 0.02D, 0.01D)
            );
        }
        if (query.contains("agent_gateway_duration_seconds_bucket")) {
            return List.of(series(Map.of(), now, 0.7D, 0.8D));
        }
        if (query.contains("agent_request_duration_seconds_bucket")) {
            return List.of(series(Map.of(), now, 0.5D, 0.6D));
        }
        return List.of();
    }

    private VectorSample sample(Map<String, String> labels, double value) {
        return new VectorSample(labels, value);
    }

    private MatrixSeries series(Map<String, String> labels, long now, double first, double second) {
        return new MatrixSeries(labels, List.of(
                new DataPoint(now - 30, first),
                new DataPoint(now, second)
        ));
    }
}
