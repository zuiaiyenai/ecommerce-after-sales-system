package com.ecommerce.aftersales.mapper;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import javax.sql.DataSource;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
class AfterSalesTicketMapperMySqlTest {
    @Container static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4").withDatabaseName("aftersales").withUsername("test").withPassword("test");
    static SqlSessionFactory factory;

    @BeforeAll static void setup() throws Exception {
        DataSource ds = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        try (var connection = ds.getConnection(); var statement = connection.createStatement()) {
            statement.execute("""
                    CREATE TABLE after_sales_ticket (
                      id BIGINT NOT NULL PRIMARY KEY, ticket_no VARCHAR(32) NOT NULL UNIQUE,
                      order_id BIGINT NOT NULL, order_no VARCHAR(32) NOT NULL, user_id BIGINT NOT NULL,
                      reason VARCHAR(50) NOT NULL, status VARCHAR(20) NOT NULL,
                      evidence_revision INT NOT NULL DEFAULT 0,
                      ai_review_request_id VARCHAR(64) NULL UNIQUE,
                      ai_review_status VARCHAR(32) NOT NULL DEFAULT 'RUNNING', ai_review_result VARCHAR(30) NULL,
                      ai_review_reason VARCHAR(500) NULL, ai_review_time DATETIME NULL,
                      ai_review_audit_json TEXT NULL, ai_review_confidence DECIMAL(3,2) NULL,
                      ai_suggested_after_sale_type VARCHAR(30) NULL,
                      audit_opinion VARCHAR(500) NULL, audit_time DATETIME NULL,
                      expected_complete_time DATETIME NULL, manual_review_required TINYINT NOT NULL DEFAULT 0,
                      priority TINYINT NOT NULL DEFAULT 0, deleted TINYINT NOT NULL DEFAULT 0,
                      create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                    """);
        }
        MybatisSqlSessionFactoryBean bean = new MybatisSqlSessionFactoryBean(); bean.setDataSource(ds);
        MybatisConfiguration config = new MybatisConfiguration(); config.addMapper(AfterSalesTicketMapper.class); bean.setConfiguration(config); factory = bean.getObject();
    }

    @Test void onlyOneConcurrentAiUpdateCanApply() throws Exception {
        insert(1L, "PENDING", "concurrent-request");
        Callable<Integer> apply = () -> { try (SqlSession s = factory.openSession(true)) { return s.getMapper(AfterSalesTicketMapper.class).applyAiApprovalIfPending(1L, "concurrent-request", "ok", "{}", BigDecimal.ONE, LocalDateTime.now(), LocalDateTime.now()); } };
        try (var pool = Executors.newFixedThreadPool(2)) { var results = pool.invokeAll(java.util.List.of(apply, apply)); assertThat(results.stream().mapToInt(f -> { try { return f.get(); } catch (Exception e) { throw new RuntimeException(e); } }).sum()).isEqualTo(1); }
    }

    @Test void repeatedRequestIdAndAllTerminalStatusesAreProtected() throws Exception {
        insert(2L, "PENDING_REVIEW", "same-request");
        try (SqlSession s = factory.openSession(true)) {
            var mapper = s.getMapper(AfterSalesTicketMapper.class);
            assertThat(mapper.applyAiApprovalIfPending(2L, "same-request", "ok", "{}", BigDecimal.ONE, LocalDateTime.now(), LocalDateTime.now())).isOne();
            assertThat(mapper.applyAiApprovalIfPending(2L, "same-request", "ok", "{}", BigDecimal.ONE, LocalDateTime.now(), LocalDateTime.now())).isZero();
        }
        String[] terminal = {"PROCESSING", "COMPLETED", "REJECTED", "CLOSED"};
        for (int i = 0; i < terminal.length; i++) {
            long id = 10L + i;
            insert(id, terminal[i], "terminal-" + id);
            try (SqlSession s = factory.openSession(true)) {
                assertThat(s.getMapper(AfterSalesTicketMapper.class).applyAiApprovalIfPending(id, "terminal-" + id, "ok", "{}", BigDecimal.ONE, LocalDateTime.now(), LocalDateTime.now())).isZero();
            }
        }
    }

    @Test void humanAndAiRaceEndsWithHumanDecisionAndAiCannotOverwriteItLater() throws Exception {
        insert(30L, "PENDING_REVIEW", "race-ai");
        CountDownLatch start = new CountDownLatch(1);
        Callable<Integer> ai = () -> { start.await(); try (SqlSession s = factory.openSession(true)) { return s.getMapper(AfterSalesTicketMapper.class).applyAiApprovalIfPending(30L, "race-ai", "ok", "{}", BigDecimal.ONE, LocalDateTime.now(), LocalDateTime.now()); } };
        Callable<Integer> human = () -> { start.await(); try (var c = MYSQL.createConnection(""); var p = c.prepareStatement("update after_sales_ticket set status='REJECTED' where id=30")) { return p.executeUpdate(); } };
        try (var pool = Executors.newFixedThreadPool(2)) {
            var aiResult = pool.submit(ai); var humanResult = pool.submit(human); start.countDown();
            assertThat(humanResult.get()).isOne(); aiResult.get();
        }
        assertThat(status(30L)).isEqualTo("REJECTED");
        try (SqlSession s = factory.openSession(true)) {
            assertThat(s.getMapper(AfterSalesTicketMapper.class).applyAiApprovalIfPending(30L, "race-ai", "ok", "{}", BigDecimal.ONE, LocalDateTime.now(), LocalDateTime.now())).isZero();
        }
    }

    private static void insert(long id, String status, String reviewRequestId) throws Exception { try (var c = MYSQL.createConnection("" ); var p = c.prepareStatement("insert into after_sales_ticket(id,ticket_no,order_id,order_no,user_id,reason,status,ai_review_request_id) values(?,?,?,?,?,?,?,?)")) { p.setLong(1,id); p.setString(2,"T"+id); p.setLong(3,id); p.setString(4,"O"+id); p.setLong(5,id); p.setString(6,"OTHER"); p.setString(7,status); p.setString(8,reviewRequestId); p.executeUpdate(); } }
    private static String status(long id) throws Exception { try (var c = MYSQL.createConnection(""); var p = c.prepareStatement("select status from after_sales_ticket where id=?")) { p.setLong(1, id); try (var rs = p.executeQuery()) { rs.next(); return rs.getString(1); } } }
}
