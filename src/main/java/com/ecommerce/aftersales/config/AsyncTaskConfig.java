package com.ecommerce.aftersales.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.slf4j.MDC;

import java.util.Map;
import java.util.concurrent.ThreadPoolExecutor;

/** Keeps slow knowledge ingestion work isolated from request-handling threads. */
@Configuration
public class AsyncTaskConfig {

    @Bean(name = "knowledgeIngestionExecutor")
    public ThreadPoolTaskExecutor knowledgeIngestionExecutor(
            @Value("${app.async.knowledge-ingestion.core-pool-size:2}") int corePoolSize,
            @Value("${app.async.knowledge-ingestion.max-pool-size:4}") int maxPoolSize,
            @Value("${app.async.knowledge-ingestion.queue-capacity:100}") int queueCapacity
    ) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(Math.max(1, corePoolSize));
        executor.setMaxPoolSize(Math.max(corePoolSize, maxPoolSize));
        executor.setQueueCapacity(Math.max(1, queueCapacity));
        executor.setThreadNamePrefix("knowledge-ingest-");
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.setTaskDecorator(this::withMdcContext);
        // Preserve application availability when an import burst fills the queue.
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.initialize();
        return executor;
    }

    @Bean(name = "agentSseExecutor")
    public ThreadPoolTaskExecutor agentSseExecutor(
            @Value("${app.async.agent-sse.core-pool-size:4}") int corePoolSize,
            @Value("${app.async.agent-sse.max-pool-size:32}") int maxPoolSize,
            @Value("${app.async.agent-sse.queue-capacity:64}") int queueCapacity
    ) {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(Math.max(1, corePoolSize));
        executor.setMaxPoolSize(Math.max(corePoolSize, maxPoolSize));
        executor.setQueueCapacity(Math.max(1, queueCapacity));
        executor.setThreadNamePrefix("agent-sse-");
        executor.setWaitForTasksToCompleteOnShutdown(false);
        executor.setTaskDecorator(this::withMdcContext);
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        executor.initialize();
        return executor;
    }

    private Runnable withMdcContext(Runnable task) {
        Map<String, String> captured = MDC.getCopyOfContextMap();
        return () -> {
            Map<String, String> previous = MDC.getCopyOfContextMap();
            if (captured == null) {
                MDC.clear();
            } else {
                MDC.setContextMap(captured);
            }
            try {
                task.run();
            } finally {
                if (previous == null) {
                    MDC.clear();
                } else {
                    MDC.setContextMap(previous);
                }
            }
        };
    }
}
