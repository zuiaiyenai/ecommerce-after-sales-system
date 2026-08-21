package com.ecommerce.aftersales.mapper;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import javax.sql.DataSource;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers(disabledWithoutDocker = true)
class ChatMessageBatchQueryMySqlTest {

    @Container
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
            .withDatabaseName("aftersales")
            .withUsername("test")
            .withPassword("test");

    static SqlSessionFactory factory;
    static DataSource dataSource;

    @BeforeAll
    static void setup() throws Exception {
        dataSource = new DriverManagerDataSource(MYSQL.getJdbcUrl(), MYSQL.getUsername(), MYSQL.getPassword());
        try (var connection = dataSource.getConnection(); var statement = connection.createStatement()) {
            statement.execute("""
                    CREATE TABLE chat_message (
                      id BIGINT NOT NULL PRIMARY KEY,
                      session_id BIGINT NOT NULL,
                      role VARCHAR(20) NOT NULL,
                      content TEXT NULL,
                      message_type VARCHAR(20) NULL,
                      file_url VARCHAR(500) NULL,
                      emotion_score DECIMAL(5,4) NULL,
                      create_time DATETIME NOT NULL,
                      INDEX idx_chat_message_session_time (session_id, create_time),
                      INDEX idx_chat_message_session_id (session_id, id)
                    ) ENGINE=InnoDB
                    """);
        }
        MybatisSqlSessionFactoryBean bean = new MybatisSqlSessionFactoryBean();
        bean.setDataSource(dataSource);
        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.addMapper(ChatMessageMapper.class);
        bean.setConfiguration(configuration);
        factory = bean.getObject();
        seedMessages();
    }

    @Test
    void latestMessageUsesCreateTimeAndIdAsStableTieBreaker() {
        try (SqlSession session = factory.openSession(true)) {
            var latest = session.getMapper(ChatMessageMapper.class).selectLatestBySessionIds(List.of(1L, 2L));
            assertThat(latest).extracting(message -> message.getId()).containsExactlyInAnyOrder(26L, 28L);
            assertThat(latest).filteredOn(message -> message.getId().equals(28L)).singleElement()
                    .satisfies(message -> {
                        assertThat(message.getMessageType()).isEqualTo("IMAGE");
                        assertThat(message.getFileUrl()).isEqualTo("/uploads/evidence.png");
                        assertThat(message.getContent()).isEqualTo("[图片]");
                    });
        }
    }

    @Test
    void recentEmotionQueryReturnsOnlyLatestTwentyInChronologicalOrder() {
        try (SqlSession session = factory.openSession(true)) {
            var emotions = session.getMapper(ChatMessageMapper.class).selectRecentUserEmotionsBySessionIds(List.of(1L));
            assertThat(emotions).hasSize(20);
            assertThat(emotions.get(0).getId()).isEqualTo(7L);
            assertThat(emotions.get(19).getId()).isEqualTo(26L);
            assertThat(emotions).extracting(message -> message.getEmotionScore())
                    .allMatch(score -> score.compareTo(BigDecimal.ZERO) > 0);
        }
    }

    @Test
    void existingSessionIndexesAreCandidatesForBatchProjection() throws Exception {
        String sql = """
                EXPLAIN SELECT id, session_id, role, content, message_type, file_url, create_time
                FROM (
                    SELECT id, session_id, role, content, message_type, file_url, create_time,
                           ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY create_time DESC, id DESC) row_num
                    FROM chat_message
                    WHERE session_id IN (1, 2)
                ) ranked
                WHERE row_num = 1
                """;
        List<String> indexEvidence = new ArrayList<>();
        try (var connection = dataSource.getConnection();
             var statement = connection.createStatement();
             var resultSet = statement.executeQuery(sql)) {
            while (resultSet.next()) {
                indexEvidence.add(String.valueOf(resultSet.getString("possible_keys")));
                indexEvidence.add(String.valueOf(resultSet.getString("key")));
            }
        }
        assertThat(String.join(",", indexEvidence))
                .containsAnyOf("idx_chat_message_session_time", "idx_chat_message_session_id");
    }

    private static void seedMessages() throws Exception {
        LocalDateTime base = LocalDateTime.of(2026, 7, 14, 12, 0);
        try (var connection = dataSource.getConnection();
             var statement = connection.prepareStatement("""
                     INSERT INTO chat_message(id, session_id, role, content, message_type, file_url, emotion_score, create_time)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                     """)) {
            for (long id = 1; id <= 26; id++) {
                statement.setLong(1, id);
                statement.setLong(2, 1L);
                statement.setString(3, "USER");
                statement.setString(4, "message-" + id);
                statement.setString(5, "TEXT");
                statement.setNull(6, java.sql.Types.VARCHAR);
                statement.setBigDecimal(7, BigDecimal.valueOf(id).movePointLeft(2));
                statement.setTimestamp(8, Timestamp.valueOf(id >= 25 ? base.plusMinutes(25) : base.plusMinutes(id)));
                statement.addBatch();
            }
            statement.setLong(1, 27L);
            statement.setLong(2, 2L);
            statement.setString(3, "USER");
            statement.setString(4, "older");
            statement.setString(5, "TEXT");
            statement.setNull(6, java.sql.Types.VARCHAR);
            statement.setBigDecimal(7, new BigDecimal("0.10"));
            statement.setTimestamp(8, Timestamp.valueOf(base));
            statement.addBatch();
            statement.setLong(1, 28L);
            statement.setLong(2, 2L);
            statement.setString(3, "SERVICE");
            statement.setString(4, "[图片]");
            statement.setString(5, "IMAGE");
            statement.setString(6, "/uploads/evidence.png");
            statement.setNull(7, java.sql.Types.DECIMAL);
            statement.setTimestamp(8, Timestamp.valueOf(base.plusMinutes(1)));
            statement.addBatch();
            statement.executeBatch();
        }
    }
}
