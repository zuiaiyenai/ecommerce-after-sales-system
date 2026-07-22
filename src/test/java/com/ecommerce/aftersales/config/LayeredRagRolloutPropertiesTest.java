package com.ecommerce.aftersales.config;

import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Configuration;

import static org.assertj.core.api.Assertions.assertThat;

class LayeredRagRolloutPropertiesTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(RolloutPropertiesConfiguration.class);

    @Test
    void bindsSafeDefaultValuesForTheLayeredRagRollout() {
        contextRunner.run(context -> {
            assertThat(context.getBean(RagRetrievalProperties.class).isLayeredRetrievalEnabled()).isFalse();
            assertThat(context.getBean(KnowledgeUploadProperties.class).getMaxFileBytes()).isEqualTo(10_485_760L);
        });
    }

    @Configuration(proxyBeanMethods = false)
    @EnableConfigurationProperties({RagRetrievalProperties.class, KnowledgeUploadProperties.class})
    static class RolloutPropertiesConfiguration {
    }
}
