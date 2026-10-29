package com.tianchuang.config;

import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "quota")
public record QuotaProperties(Boolean enabled, Integer workspacePerDay, Integer ipPerDay,
                              List<String> paths, String zone, Integer keepDays, String cleanupCron) {

    public static final List<String> DEFAULT_PATHS = List.of(
            "/api/agent/ask",
            "/api/traffic/explain",
            "/api/decisions/explain",
            "/api/monitor/run-now",
            "/api/scenario/switch",
            "/api/traffic/weather/mode");

    public QuotaProperties {
        enabled = enabled == null || enabled;
        workspacePerDay = workspacePerDay == null || workspacePerDay <= 0 ? 120 : workspacePerDay;
        ipPerDay = ipPerDay == null || ipPerDay <= 0 ? 600 : ipPerDay;
        paths = paths == null || paths.isEmpty() ? DEFAULT_PATHS : List.copyOf(paths);
        zone = zone == null || zone.isBlank() ? "Asia/Shanghai" : zone;
        keepDays = keepDays == null || keepDays <= 0 ? 7 : keepDays;
        cleanupCron = cleanupCron == null || cleanupCron.isBlank() ? "0 45 3 * * *" : cleanupCron;
    }
}
