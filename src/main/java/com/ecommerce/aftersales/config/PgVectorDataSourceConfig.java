package com.ecommerce.aftersales.config;

import com.zaxxer.hikari.HikariDataSource;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.PlatformTransactionManager;

import javax.sql.DataSource;

/**
 * 多数据源配置
 * <p>
 * dataSource Bean 全部显式构造 HikariDataSource，避免 DataSourceBuilder + @ConfigurationProperties
 * 在 Hikari 5.x 下 url → jdbcUrl 映射失败导致 "jdbcUrl is required with driverClassName"。
 * <ul>
 *   <li>mysqlDataSource — @Primary，MyBatis-Plus / 所有业务表</li>
 *   <li>pgDataSource — PgVector 向量库，仅 KnowledgeService 通过 @Qualifier("pgJdbcTemplate") 使用</li>
 * </ul>
 */
@Configuration
public class PgVectorDataSourceConfig {

    // ==================== MySQL 主数据源（@Primary） ====================

    @Value("${spring.datasource.driver-class-name}")
    private String mysqlDriverClassName;

    @Value("${spring.datasource.url}")
    private String mysqlUrl;

    @Value("${spring.datasource.username}")
    private String mysqlUsername;

    @Value("${spring.datasource.password}")
    private String mysqlPassword;

    @Primary
    @Bean(name = "mysqlDataSource")
    public DataSource mysqlDataSource() {
        HikariDataSource ds = new HikariDataSource();
        ds.setJdbcUrl(mysqlUrl);
        ds.setUsername(mysqlUsername);
        ds.setPassword(mysqlPassword);
        ds.setDriverClassName(mysqlDriverClassName);
        ds.setPoolName("MySQL-HikariPool");
        return ds;
    }

    // ==================== PgVector 向量数据源 ====================

    @Value("${pgvector.datasource.url}")
    private String pgUrl;

    @Value("${pgvector.datasource.username}")
    private String pgUsername;

    @Value("${pgvector.datasource.password}")
    private String pgPassword;

    @Value("${pgvector.datasource.driver-class-name:org.postgresql.Driver}")
    private String pgDriverClassName;

    @Value("${pgvector.datasource.hikari.maximum-pool-size:5}")
    private int pgMaxPoolSize;

    @Value("${pgvector.datasource.hikari.minimum-idle:1}")
    private int pgMinIdle;

    @Bean(name = "pgDataSource")
    public DataSource pgDataSource() {
        HikariDataSource ds = new HikariDataSource();
        ds.setJdbcUrl(pgUrl);
        ds.setUsername(pgUsername);
        ds.setPassword(pgPassword);
        ds.setDriverClassName(pgDriverClassName);
        ds.setMaximumPoolSize(pgMaxPoolSize);
        ds.setMinimumIdle(pgMinIdle);
        ds.setPoolName("PgVector-HikariPool");
        return ds;
    }

    @Bean(name = "pgJdbcTemplate")
    public JdbcTemplate pgJdbcTemplate(@Qualifier("pgDataSource") DataSource pgDataSource) {
        return new JdbcTemplate(pgDataSource);
    }

    @Bean(name = "pgTransactionManager")
    public PlatformTransactionManager pgTransactionManager(
            @Qualifier("pgDataSource") DataSource pgDataSource) {
        return new DataSourceTransactionManager(pgDataSource);
    }
}
