package com.ecommerce.aftersales.integration;

import org.junit.jupiter.api.BeforeAll;
import org.postgresql.ds.PGSimpleDataSource;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.support.EncodedResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.init.ScriptUtils;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;

@Testcontainers(disabledWithoutDocker = true)
abstract class PostgresRagIntegrationSupport {

    @Container
    static final GenericContainer<?> POSTGRES = new GenericContainer<>(DockerImageName.parse("pgvector/pgvector:pg16"))
            .withEnv("POSTGRES_DB", "rag_test")
            .withEnv("POSTGRES_USER", "rag_test")
            .withEnv("POSTGRES_PASSWORD", "rag_test")
            .withExposedPorts(5432);

    static JdbcTemplate jdbc;

    @BeforeAll
    static void initializeSchema() throws Exception {
        PGSimpleDataSource dataSource = new PGSimpleDataSource();
        dataSource.setURL("jdbc:postgresql://" + POSTGRES.getHost() + ":" + POSTGRES.getMappedPort(5432) + "/rag_test");
        dataSource.setUser("rag_test");
        dataSource.setPassword("rag_test");
        jdbc = new JdbcTemplate(dataSource);
        try (Connection connection = dataSource.getConnection()) {
            ScriptUtils.executeSqlScript(connection,
                    new EncodedResource(new FileSystemResource("sql/pgvector_schema.sql"), StandardCharsets.UTF_8));
            executeLifecycleMigration();
            executeLifecycleMigration();
        }
    }

    static void executeLifecycleMigration() throws Exception {
        try (Connection connection = jdbc.getDataSource().getConnection()) {
            ScriptUtils.executeSqlScript(connection,
                    new EncodedResource(new FileSystemResource("sql/migrations/20260721_add_layered_rag_lifecycle.sql"), StandardCharsets.UTF_8));
        }
    }
}
