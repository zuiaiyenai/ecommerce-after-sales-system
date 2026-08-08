package com.ecommerce.aftersales.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Server-side Prometheus adapter. PromQL never crosses the browser boundary. */
@Component
public class PrometheusQueryClient {

    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper;
    private final String baseUrl;

    public PrometheusQueryClient(RestTemplateBuilder builder,
                                 ObjectMapper objectMapper,
                                 @Value("${app.observability.prometheus-base-url:http://127.0.0.1:9090}") String baseUrl,
                                 @Value("${app.observability.prometheus-timeout:2s}") Duration timeout) {
        this.restTemplate = builder
                .setConnectTimeout(timeout)
                .setReadTimeout(timeout)
                .build();
        this.objectMapper = objectMapper;
        this.baseUrl = stripTrailingSlash(baseUrl);
    }

    public List<VectorSample> query(String promql) {
        URI uri = UriComponentsBuilder.fromUriString(baseUrl)
                .path("/api/v1/query")
                .queryParam("query", promql)
                .build()
                .encode()
                .toUri();
        JsonNode result = execute(uri).path("data").path("result");
        List<VectorSample> samples = new ArrayList<>();
        if (!result.isArray()) {
            return samples;
        }
        for (JsonNode item : result) {
            JsonNode value = item.path("value");
            Double parsed = value.isArray() && value.size() > 1 ? finiteDouble(value.get(1).asText()) : null;
            if (parsed != null) {
                samples.add(new VectorSample(labels(item.path("metric")), parsed));
            }
        }
        return samples;
    }

    public List<MatrixSeries> queryRange(String promql, long startEpochSecond, long endEpochSecond, int stepSeconds) {
        URI uri = UriComponentsBuilder.fromUriString(baseUrl)
                .path("/api/v1/query_range")
                .queryParam("query", promql)
                .queryParam("start", startEpochSecond)
                .queryParam("end", endEpochSecond)
                .queryParam("step", stepSeconds)
                .build()
                .encode()
                .toUri();
        JsonNode result = execute(uri).path("data").path("result");
        List<MatrixSeries> series = new ArrayList<>();
        if (!result.isArray()) {
            return series;
        }
        for (JsonNode item : result) {
            List<DataPoint> points = new ArrayList<>();
            JsonNode values = item.path("values");
            if (values.isArray()) {
                for (JsonNode value : values) {
                    Double parsed = value.isArray() && value.size() > 1 ? finiteDouble(value.get(1).asText()) : null;
                    if (parsed != null) {
                        points.add(new DataPoint(value.get(0).asLong(), parsed));
                    }
                }
            }
            series.add(new MatrixSeries(labels(item.path("metric")), points));
        }
        return series;
    }

    private JsonNode execute(URI uri) {
        try {
            String body = restTemplate.getForObject(uri, String.class);
            JsonNode root = objectMapper.readTree(body == null ? "{}" : body);
            if (!"success".equals(root.path("status").asText())) {
                throw new PrometheusUnavailableException("Prometheus returned a non-success response");
            }
            return root;
        } catch (PrometheusUnavailableException exception) {
            throw exception;
        } catch (RestClientException exception) {
            throw new PrometheusUnavailableException("Prometheus request failed", exception);
        } catch (Exception exception) {
            throw new PrometheusUnavailableException("Prometheus response could not be parsed", exception);
        }
    }

    private static Map<String, String> labels(JsonNode metric) {
        Map<String, String> labels = new LinkedHashMap<>();
        if (!metric.isObject()) {
            return labels;
        }
        Iterator<Map.Entry<String, JsonNode>> fields = metric.fields();
        while (fields.hasNext()) {
            Map.Entry<String, JsonNode> field = fields.next();
            labels.put(field.getKey(), field.getValue().asText());
        }
        return labels;
    }

    private static Double finiteDouble(String value) {
        try {
            double parsed = Double.parseDouble(value);
            return Double.isFinite(parsed) ? parsed : null;
        } catch (NumberFormatException exception) {
            return null;
        }
    }

    private static String stripTrailingSlash(String value) {
        String normalized = value == null ? "" : value.trim();
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    public record VectorSample(Map<String, String> labels, double value) {
    }

    public record MatrixSeries(Map<String, String> labels, List<DataPoint> points) {
    }

    public record DataPoint(long epochSecond, double value) {
    }

    public static class PrometheusUnavailableException extends RuntimeException {
        public PrometheusUnavailableException(String message) {
            super(message);
        }

        public PrometheusUnavailableException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
