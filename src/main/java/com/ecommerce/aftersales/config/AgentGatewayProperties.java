package com.ecommerce.aftersales.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

@Data
@ConfigurationProperties(prefix = "app.agent")
public class AgentGatewayProperties {

    /**
     * Python Agent service base URL, for example http://127.0.0.1:8000/api
     */
    private String baseUrl = "http://127.0.0.1:8000/api";

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
     * Script path relative to project root.
     */
    private String scriptPath = "python_agent/web_demo.py";

    /**
     * Project working directory for the Python agent process.
     */
    private String workingDirectory = ".";

    /**
     * Startup wait time in milliseconds for the local agent health check.
     */
    private int startupWaitMillis = 15000;
}
