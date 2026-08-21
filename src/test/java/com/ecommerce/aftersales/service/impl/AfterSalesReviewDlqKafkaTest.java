package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;
import org.junit.jupiter.api.Test;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.kafka.KafkaContainer;

import java.time.Duration;
import java.util.List;
import java.util.Properties;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@Testcontainers(disabledWithoutDocker = true)
class AfterSalesReviewDlqKafkaTest {
    private static final String TOPIC = "after_sales.review.dlq.validation";
    @Container static final KafkaContainer KAFKA = new KafkaContainer("apache/kafka-native:3.8.0");

    @Test void failedMysqlHandoffLeavesOffsetUncommittedAndRecoveryCanReplay() throws Exception {
        String payload = "{\"ticket_id\":\"1\",\"review_request_id\":\"event-1\",\"failed_stage\":\"submit_manual_fallback\",\"error_message\":\"timeout\"}";
        produce(payload);
        AiReviewManualHandoffService failing = mock(AiReviewManualHandoffService.class);
        when(failing.markManualRequired(any(), anyString(), anyString(), anyString(), any(), any()))
                .thenReturn(new AiReviewManualHandoffService.ManualHandoffResult(null, false, false, "TICKET_NOT_FOUND"));
        try (KafkaConsumer<String, String> consumer = consumer("phase0-dlq")) {
            String first = pollOne(consumer);
            assertThatThrownBy(() -> new AfterSalesReviewDlqConsumer(new ObjectMapper(), failing, new AgentGatewayMetrics()).recoverManualHandoff(first))
                    .isInstanceOf(IllegalStateException.class);
        }

        AiReviewManualHandoffService recovered = mock(AiReviewManualHandoffService.class);
        AfterSalesTicket ticket = new AfterSalesTicket(); ticket.setId(1L); ticket.setStatus("PENDING_REVIEW");
        when(recovered.markManualRequired(any(), anyString(), anyString(), anyString(), any(), any()))
                .thenReturn(new AiReviewManualHandoffService.ManualHandoffResult(ticket, true, false, null));
        try (KafkaConsumer<String, String> consumer = consumer("phase0-dlq")) {
            String replay = pollOne(consumer);
            new AfterSalesReviewDlqConsumer(new ObjectMapper(), recovered, new AgentGatewayMetrics()).recoverManualHandoff(replay);
            consumer.commitSync();
            assertThat(replay).isEqualTo(payload);
        }
    }

    private static void produce(String value) throws Exception {
        Properties p = new Properties(); p.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers());
        p.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class); p.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
        try (KafkaProducer<String, String> producer = new KafkaProducer<>(p)) { producer.send(new ProducerRecord<>(TOPIC, "event-1", value)).get(); }
    }

    private static KafkaConsumer<String, String> consumer(String group) {
        Properties p = new Properties(); p.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers()); p.put(ConsumerConfig.GROUP_ID_CONFIG, group);
        p.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest"); p.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        p.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class); p.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        KafkaConsumer<String, String> consumer = new KafkaConsumer<>(p); consumer.subscribe(List.of(TOPIC)); return consumer;
    }

    private static String pollOne(KafkaConsumer<String, String> consumer) {
        long deadline = System.nanoTime() + Duration.ofSeconds(20).toNanos();
        while (System.nanoTime() < deadline) {
            var records = consumer.poll(Duration.ofMillis(500));
            if (!records.isEmpty()) return records.iterator().next().value();
        }
        throw new AssertionError("DLQ record was not received");
    }
}
