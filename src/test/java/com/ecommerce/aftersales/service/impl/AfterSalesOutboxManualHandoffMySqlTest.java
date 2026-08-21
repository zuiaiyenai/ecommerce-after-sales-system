package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.config.GlobalConfig;
import com.baomidou.mybatisplus.core.toolkit.GlobalConfigUtils;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.ecommerce.aftersales.config.MybatisPlusMetaObjectHandler;
import com.ecommerce.aftersales.entity.AfterSalesEventOutbox;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.mapper.AfterSalesEventOutboxMapper;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.AiReviewUserNotificationService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.mybatis.spring.SqlSessionTemplate;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import javax.sql.DataSource;
import java.time.LocalDateTime;
import java.util.concurrent.CompletableFuture;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@Testcontainers(disabledWithoutDocker = true)
class AfterSalesOutboxManualHandoffMySqlTest {

    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
            .withDatabaseName("aftersales")
            .withUsername("test")
            .withPassword("test");

    static SqlSessionFactory factory;
    static DataSource dataSource;

    @BeforeAll
    static void setup() throws Exception {
        dataSource = new DriverManagerDataSource(
                MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        try (var connection = dataSource.getConnection(); var statement = connection.createStatement()) {
            statement.execute("""
                    CREATE TABLE after_sales_ticket (
                      id BIGINT NOT NULL PRIMARY KEY, ticket_no VARCHAR(32) NOT NULL UNIQUE,
                      order_id BIGINT NOT NULL, order_no VARCHAR(32) NOT NULL, user_id BIGINT NOT NULL,
                      merchant_id BIGINT NULL, merchant_code VARCHAR(50) NOT NULL DEFAULT 'MERCHANT_DEMO',
                      policy_code VARCHAR(64) NULL, policy_version VARCHAR(32) NULL, product_name VARCHAR(200) NULL,
                      after_sale_type VARCHAR(30) NULL, reason VARCHAR(50) NOT NULL, reason_detail VARCHAR(500) NULL,
                      description TEXT NULL, refund_amount DECIMAL(10,2) NULL, ai_review_audit_json TEXT NULL,
                      ai_review_confidence DECIMAL(3,2) NULL, ai_suggested_after_sale_type VARCHAR(30) NULL,
                      ai_review_request_id VARCHAR(64) NULL UNIQUE,
                      ai_review_status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
                      evidence_revision INT NOT NULL DEFAULT 0,
                      ai_review_result VARCHAR(30) NULL,
                      ai_review_reason VARCHAR(500) NULL, ai_review_time DATETIME NULL,
                      manual_review_required TINYINT NOT NULL DEFAULT 0, status VARCHAR(20) NOT NULL,
                      priority TINYINT NOT NULL DEFAULT 0, assignee_id BIGINT NULL, audit_opinion VARCHAR(500) NULL,
                      audit_time DATETIME NULL, expected_complete_time DATETIME NULL, complete_time DATETIME NULL,
                      deleted TINYINT NOT NULL DEFAULT 0, create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                    """);
            statement.execute("""
                    CREATE TABLE ticket_log (
                      id BIGINT NOT NULL PRIMARY KEY, ticket_id BIGINT NOT NULL, operator_id BIGINT NULL,
                      operator_type VARCHAR(20) NOT NULL, from_status VARCHAR(20) NULL,
                      to_status VARCHAR(20) NOT NULL, action VARCHAR(80) NOT NULL, content VARCHAR(500) NULL,
                      create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      INDEX idx_ticket_log_ticket(ticket_id)
                    ) ENGINE=InnoDB
                    """);
            statement.execute("""
                    CREATE TABLE after_sales_event_outbox (
                      id BIGINT NOT NULL PRIMARY KEY, event_id VARCHAR(64) NOT NULL UNIQUE,
                      event_type VARCHAR(64) NOT NULL, topic VARCHAR(128) NOT NULL,
                      aggregate_type VARCHAR(64) NOT NULL, aggregate_id BIGINT NOT NULL, payload TEXT NOT NULL,
                      status VARCHAR(20) NOT NULL, retry_count INT NOT NULL, last_error VARCHAR(500) NULL,
                      next_retry_time DATETIME NULL, published_time DATETIME NULL,
                      create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                    """);
        }

        MybatisSqlSessionFactoryBean bean = new MybatisSqlSessionFactoryBean();
        bean.setDataSource(dataSource);
        GlobalConfig globalConfig = new GlobalConfig();
        globalConfig.setDbConfig(new GlobalConfig.DbConfig());
        globalConfig.setMetaObjectHandler(new MybatisPlusMetaObjectHandler());
        bean.setGlobalConfig(globalConfig);
        MybatisConfiguration configuration = new MybatisConfiguration();
        GlobalConfigUtils.setGlobalConfig(configuration, globalConfig);
        configuration.addMapper(AfterSalesTicketMapper.class);
        configuration.addMapper(TicketLogMapper.class);
        configuration.addMapper(AfterSalesEventOutboxMapper.class);
        bean.setConfiguration(configuration);
        factory = bean.getObject();
    }

    @Test
    void ticketAndOutboxRollbackTogetherWhenBusinessTransactionFails() {
        SqlSessionTemplate template = new SqlSessionTemplate(factory);
        AfterSalesTicketMapper ticketMapper = template.getMapper(AfterSalesTicketMapper.class);
        AfterSalesEventOutboxMapper outboxMapper = template.getMapper(AfterSalesEventOutboxMapper.class);
        @SuppressWarnings("unchecked")
        KafkaTemplate<String, String> kafkaTemplate = mock(KafkaTemplate.class);
        AfterSalesReviewEventServiceImpl reviewEvents = new AfterSalesReviewEventServiceImpl(
                outboxMapper, new ObjectMapper(), kafkaTemplate,
                mock(com.ecommerce.aftersales.service.AiReviewManualHandoffService.class),
                new AgentGatewayMetrics());
        ReflectionTestUtils.setField(reviewEvents, "reviewRequestTopic", "after_sales.review.request");
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(300L);
        ticket.setTicketNo("T300");
        ticket.setOrderId(300L);
        ticket.setOrderNo("O300");
        ticket.setUserId(300L);
        ticket.setReason("OTHER");
        ticket.setStatus("PENDING_REVIEW");
        ticket.setAiReviewRequestId("review-300");
        ticket.setAiReviewStatus("RUNNING");
        ticket.setEvidenceRevision(0);
        TransactionTemplate transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));

        assertThatThrownBy(() -> transaction.executeWithoutResult(ignored -> {
            ticketMapper.insert(ticket);
            reviewEvents.enqueueReviewStarted(ticket, null);
            throw new IllegalStateException("rollback business transaction");
        })).isInstanceOf(IllegalStateException.class);

        assertThat(ticketMapper.selectById(300L)).isNull();
        assertThat(outboxMapper.selectList(null)).noneMatch(item -> Long.valueOf(300L).equals(item.getAggregateId()));
    }

    @Test
    void exhaustedOutboxPersistsManualReviewFactAndAuditLogBeforeBecomingDead() throws Exception {
        insertTicket(100L, "PENDING_REVIEW");
        AiReviewStatusCacheService cache = mock(AiReviewStatusCacheService.class);

        try (SqlSession session = factory.openSession(true)) {
            AfterSalesTicketMapper ticketMapper = session.getMapper(AfterSalesTicketMapper.class);
            TicketLogMapper logMapper = session.getMapper(TicketLogMapper.class);
            AfterSalesEventOutboxMapper outboxMapper = session.getMapper(AfterSalesEventOutboxMapper.class);
            AiReviewManualHandoffServiceImpl handoff =
                    new AiReviewManualHandoffServiceImpl(ticketMapper, logMapper, cache,
                            mock(AiReviewUserNotificationService.class), new AgentGatewayMetrics());

            @SuppressWarnings("unchecked")
            KafkaTemplate<String, String> kafkaTemplate = mock(KafkaTemplate.class);
            when(kafkaTemplate.send(anyString(), anyString(), anyString()))
                    .thenReturn(CompletableFuture.failedFuture(new IllegalStateException("broker unavailable")));

            AfterSalesReviewEventServiceImpl service = new AfterSalesReviewEventServiceImpl(
                    outboxMapper, new ObjectMapper(), kafkaTemplate, handoff, new AgentGatewayMetrics());
            ReflectionTestUtils.setField(service, "maxRetries", 0);

            AfterSalesEventOutbox event = new AfterSalesEventOutbox();
            event.setId(200L);
            event.setEventId("event-outbox-dead");
            event.setEventType("AFTER_SALES_REVIEW_REQUESTED");
            event.setTopic("after_sales.review.request");
            event.setAggregateType("after_sales_ticket");
            event.setAggregateId(100L);
            event.setPayload("{\"review_request_id\":\"review-100\",\"evidence_revision\":0}");
            event.setStatus("NEW");
            event.setRetryCount(0);
            event.setNextRetryTime(LocalDateTime.now());
            event.setCreateTime(LocalDateTime.now());
            event.setUpdateTime(LocalDateTime.now());
            outboxMapper.insert(event);

            service.publishOne(event);

            var ticket = ticketMapper.selectById(100L);
            var persistedOutbox = outboxMapper.selectById(200L);
            assertThat(ticket.getStatus()).isEqualTo("PENDING_REVIEW");
            assertThat(ticket.getAiReviewResult()).isEqualTo("MANUAL_REVIEW_REQUIRED");
            assertThat(ticket.getManualReviewRequired()).isOne();
            assertThat(ticket.getAiReviewRequestId()).isEqualTo("review-100");
            assertThat(persistedOutbox.getStatus()).isEqualTo("DEAD");
            assertThat(logMapper.selectList(null))
                    .singleElement()
                    .satisfies(log -> {
                        assertThat(log.getTicketId()).isEqualTo(100L);
                        assertThat(log.getAction()).isEqualTo("AI_REVIEW_MANUAL_OUTBOX_DEAD");
                    });
        }

        verify(cache).cacheStatus(100L, "MANUAL_REQUIRED");
    }

    private static void insertTicket(long id, String status) throws Exception {
        try (var connection = MYSQL.createConnection("");
             var statement = connection.prepareStatement("""
                     INSERT INTO after_sales_ticket
                       (id, ticket_no, order_id, order_no, user_id, reason, status,
                        ai_review_request_id, ai_review_status, evidence_revision)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', 0)
                     """)) {
            statement.setLong(1, id);
            statement.setString(2, "T" + id);
            statement.setLong(3, id);
            statement.setString(4, "O" + id);
            statement.setLong(5, id);
            statement.setString(6, "OTHER");
            statement.setString(7, status);
            statement.setString(8, "review-" + id);
            statement.executeUpdate();
        }
    }
}
