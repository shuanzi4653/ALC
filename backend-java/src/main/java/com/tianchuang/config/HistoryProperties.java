package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "history")
public record HistoryProperties(Integer retentionDays, Integer maxPageSize, String cleanupCron) {

    public HistoryProperties {
        retentionDays = retentionDays == null || retentionDays <= 0 ? 30 : retentionDays;
        maxPageSize = maxPageSize == null || maxPageSize <= 0 ? 100 : maxPageSize;
        cleanupCron = cleanupCron == null || cleanupCron.isBlank() ? "0 30 3 * * *" : cleanupCron;
    }
}
