package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 监测调度配置：sim=模拟数据 | live=和风真实API */
@ConfigurationProperties(prefix = "monitor")
public record MonitorProperties(String mode, String scenario, int intervalMinutes) {

    public boolean live() {
        return "live".equalsIgnoreCase(mode);
    }
}
