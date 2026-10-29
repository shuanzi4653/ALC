package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "monitor")
public record MonitorProperties(String mode, String scenario, long initialDelayMs,
                                long fixedDelayMs) {

    public MonitorProperties {
        mode = (mode == null || mode.isBlank() || "sim".equalsIgnoreCase(mode)) ? "live" : mode;
        scenario = scenario == null || scenario.isBlank() ? "live" : scenario;
        initialDelayMs = initialDelayMs > 0 ? initialDelayMs : 6_000;
        fixedDelayMs = fixedDelayMs > 0 ? fixedDelayMs : 600_000;
    }

    public boolean live() {
        return "live".equalsIgnoreCase(mode);
    }
}
