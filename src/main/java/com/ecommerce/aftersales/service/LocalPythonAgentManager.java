package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.config.AgentGatewayProperties;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.ServerSocket;
import java.nio.file.Path;

@Slf4j
@Component
@RequiredArgsConstructor
public class LocalPythonAgentManager implements ApplicationRunner {

    private final AgentGatewayProperties properties;
    private final RestTemplate agentRestTemplate;
    private final Environment environment;

    private volatile Process localAgentProcess;

    @Override
    public void run(ApplicationArguments args) {
        if (!properties.isAutoStart()) {
            log.info("Local Python agent auto-start disabled.");
            return;
        }

        if (!isLocalAgentUrl()) {
            log.info("Agent base URL is not local, skip auto-start: {}", properties.getBaseUrl());
            return;
        }

        if (isAgentReachable()) {
            log.info("Python agent already reachable at {}", properties.getBaseUrl());
            return;
        }

        int port = resolveAgentPort();
        if (port < 0) {
            log.warn("Could not resolve agent port from base URL: {}", properties.getBaseUrl());
            return;
        }

        if (!isPortAvailable(port)) {
            log.warn("Port {} is occupied, skip starting local Python agent.", port);
            return;
        }

        startLocalAgent();
        waitForAgentReady();
    }

    @PreDestroy
    public void shutdown() {
        Process process = localAgentProcess;
        if (process == null) {
            return;
        }
        log.info("Stopping local Python agent process.");
        process.destroy();
        try {
            process.waitFor();
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
        }
    }

    private void startLocalAgent() {
        Path workingDir = Path.of(properties.getWorkingDirectory()).toAbsolutePath().normalize();
        Path scriptPath = workingDir.resolve(properties.getScriptPath()).normalize();
        if (!scriptPath.toFile().exists()) {
            log.warn("Python agent script not found, skip auto-start: {}", scriptPath);
            return;
        }

        ProcessBuilder builder = new ProcessBuilder(
                properties.getPythonCommand(),
                scriptPath.toString()
        );
        builder.directory(workingDir.toFile());
        builder.redirectErrorStream(true);
        builder.inheritIO();
        builder.environment().put("AFTERSALES_POLICY_BASE_URL", buildPolicyBaseUrl());
        try {
            localAgentProcess = builder.start();
            log.info("Local Python agent process started: {}", scriptPath);
        } catch (IOException exception) {
            log.error("Failed to start local Python agent.", exception);
        }
    }

    private void waitForAgentReady() {
        if (localAgentProcess == null) {
            return;
        }
        long deadline = System.currentTimeMillis() + properties.getStartupWaitMillis();
        while (System.currentTimeMillis() < deadline) {
            if (isAgentReachable()) {
                log.info("Local Python agent is ready.");
                return;
            }
            if (!localAgentProcess.isAlive()) {
                log.error("Local Python agent exited before becoming ready.");
                return;
            }
            try {
                Thread.sleep(1000);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        log.warn("Timed out waiting for local Python agent to become ready.");
    }

    private boolean isAgentReachable() {
        try {
            ResponseEntity<String> response = agentRestTemplate.getForEntity(buildHealthUrl(), String.class);
            return response.getStatusCode().is2xxSuccessful();
        } catch (Exception exception) {
            return false;
        }
    }

    private String buildHealthUrl() {
        String baseUrl = properties.getBaseUrl();
        if (baseUrl.endsWith("/")) {
            baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
        }
        return baseUrl + "/health";
    }

    private boolean isLocalAgentUrl() {
        String baseUrl = properties.getBaseUrl();
        return baseUrl.contains("127.0.0.1") || baseUrl.contains("localhost");
    }

    private int resolveAgentPort() {
        try {
            URI uri = new URI(properties.getBaseUrl());
            if (uri.getPort() > 0) {
                return uri.getPort();
            }
            return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
        } catch (URISyntaxException exception) {
            log.warn("Invalid agent base URL: {}", properties.getBaseUrl(), exception);
            return -1;
        }
    }

    private boolean isPortAvailable(int port) {
        try (ServerSocket ignored = new ServerSocket(port)) {
            return true;
        } catch (IOException exception) {
            return false;
        }
    }

    private String buildPolicyBaseUrl() {
        String port = environment.getProperty("server.port", "8080");
        String contextPath = environment.getProperty("server.servlet.context-path", "");
        String normalizedContextPath = contextPath == null ? "" : contextPath.trim();
        if (!normalizedContextPath.isEmpty() && !normalizedContextPath.startsWith("/")) {
            normalizedContextPath = "/" + normalizedContextPath;
        }
        return "http://127.0.0.1:" + port + normalizedContextPath + "/agent/policies";
    }
}
