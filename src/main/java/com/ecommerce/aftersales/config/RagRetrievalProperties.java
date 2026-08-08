package com.ecommerce.aftersales.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.rag")
public class RagRetrievalProperties {

    private boolean layeredRetrievalEnabled = false;

    public boolean isLayeredRetrievalEnabled() {
        return layeredRetrievalEnabled;
    }

    public void setLayeredRetrievalEnabled(boolean layeredRetrievalEnabled) {
        this.layeredRetrievalEnabled = layeredRetrievalEnabled;
    }
}
