package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 监测调度配置。所有时长均使用毫秒，避免注解单位混淆。
 *
 * 这里**没有** allowSimFallback：本服务已不存在模拟气象，因此「取不到数据时是否
 * 用模拟数据顶上」这个问题本身不再成立。取不到真实数据时，唯一的降级方向是另一个
 * 真实来源，两条都失败就把本轮判为失败。
 */
@ConfigurationProperties(prefix = "monitor")
public record MonitorProperties(String mode, String scenario, long initialDelayMs,
                                long fixedDelayMs) {

    public MonitorProperties {
        // 真实来源是唯一选项，因此 mode 不再是开关，只是运行口径的记录。历史配置里
        // 若残留 "sim"，同样归一为 live——不能让一个已经废弃的模式名把服务锁在半年前
        // 的行为上。
        mode = (mode == null || mode.isBlank() || "sim".equalsIgnoreCase(mode)) ? "live" : mode;
        scenario = scenario == null || scenario.isBlank() ? "live" : scenario;
        initialDelayMs = initialDelayMs > 0 ? initialDelayMs : 6_000;
        fixedDelayMs = fixedDelayMs > 0 ? fixedDelayMs : 600_000;
    }

    public boolean live() {
        return "live".equalsIgnoreCase(mode);
    }
}
