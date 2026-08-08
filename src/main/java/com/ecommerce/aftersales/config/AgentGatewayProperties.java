package com.ecommerce.aftersales.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

@Data
@ConfigurationProperties(prefix = "app.agent")
public class AgentGatewayProperties {

    /**
     * Python Agent service base URL, for example http://127.0.0.1:8000/api
     */
    private String baseUrl = "http://127.0.0.1:8000/api";

    /** Optional Agent replica URLs for round-robin routing. */
    private List<String> baseUrls = new ArrayList<>();

    /**
     * Gateway timeout in milliseconds.
     */
    private int timeoutMillis = 15000;

    /**
     * Whether Spring Boot should try to launch the local Python agent automatically.
     */
    private boolean autoStart = true;

    /**
     * Python executable used to launch the local agent.
     */
    private String pythonCommand = "python";

    /**
     * Arguments passed to the Python executable when starting the local agent.
     */
    private List<String> launchArgs = new ArrayList<>(Arrays.asList("-m", "after_sales_agent.api.http_server"));

    /**
     * Legacy script path relative to workingDirectory. When set, it takes precedence over launchArgs.
     */
    private String scriptPath = "";

    /**
     * Project working directory for the Python agent process.
     */
    private String workingDirectory = "python_agent";

    /**
     * Startup wait time in milliseconds for the local agent health check.
     */
    private int startupWaitMillis = 15000;

    /** Shared secret used only by the local Python Agent for server-to-server calls. */
    private String internalToken = "";

    /** Total gateway concurrency; 0 derives capacity from replica count. */
    private int maxConcurrentRequests = 0;

    /** Capacity contributed by one healthy Agent replica in automatic mode. */
    private int perInstanceMaxConcurrentRequests = 2;

    /** Maximum time to wait for an Agent execution slot. */
    private int queueWaitMillis = 200;
}
