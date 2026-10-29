package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 历史数据治理配置（E02）。
 * retention-days：历史保留天数，超期记录由清理任务回收；
 * max-page-size：单页上限，防止一次拉全表；cleanup-cron：清理任务执行时间。
 */
@ConfigurationProperties(prefix = "history")
public record HistoryProperties(Integer retentionDays, Integer maxPageSize, String cleanupCron) {

    public HistoryProperties {
        retentionDays = retentionDays == null || retentionDays <= 0 ? 30 : retentionDays;
        maxPageSize = maxPageSize == null || maxPageSize <= 0 ? 100 : maxPageSize;
        cleanupCron = cleanupCron == null || cleanupCron.isBlank() ? "0 30 3 * * *" : cleanupCron;
    }
}
