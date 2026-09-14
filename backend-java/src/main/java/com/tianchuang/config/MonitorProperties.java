package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 监测调度与数据源降级策略。所有时长均使用毫秒，避免注解单位混淆。 */
@ConfigurationProperties(prefix = "monitor")
public record MonitorProperties(String mode, String scenario, long initialDelayMs,
                                long fixedDelayMs, boolean allowSimFallback) {

    public MonitorProperties {
        mode = mode == null || mode.isBlank() ? "sim" : mode;
        scenario = scenario == null || scenario.isBlank() ? "clear" : scenario;
        initialDelayMs = initialDelayMs > 0 ? initialDelayMs : 6_000;
        fixedDelayMs = fixedDelayMs > 0 ? fixedDelayMs : 600_000;
    }

    public boolean live() {
        return "live".equalsIgnoreCase(mode);
    }
}
