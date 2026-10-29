package com.tianchuang.model;

import java.util.Locale;

/**
 * 监测轮的运行口径。
 *
 * 这三个值不再选择「哪一种模拟天气」，因为本服务已经不存在模拟天气：
 *
 * <ul>
 *   <li>{@code LIVE} —— 正常轮次，气象取自真实来源（Open-Meteo / 和风）；</li>
 *   <li>{@code CLEAR} —— 本轮不声明任何不利天气，气象通道不产出几何；</li>
 *   <li>{@code UNKNOWN} —— 气象源不可用，所有班次一律暂停放行。</li>
 * </ul>
 *
 * 原来的 {@code WIND / RAIN / STORM} 是合成气象剧本，已随模拟生成器一并移除。
 * 保留它们会让「本系统不会编造气象」这句话在接口层面变成假的。
 */
public enum Scenario {
    LIVE, CLEAR, UNKNOWN;

    public String key() {
        return name().toLowerCase(Locale.ROOT);
    }

    /** 该口径是否需要向真实源取数。 */
    public boolean needsWeather() {
        return this == LIVE;
    }

    public static Scenario parse(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("scenario 不能为空");
        }
        String cleaned = value.trim().toUpperCase(Locale.ROOT);
        // 历史运行记录里可能存着已退役的合成剧本名。把它们的含义映射到新口径，
        // 而不是让一次读取直接失败：旧记录本来就代表「当时按合成天气跑的一轮」，
        // 语义上最接近「没有真实气象可用」。
        switch (cleaned) {
            case "WIND", "RAIN", "STORM" -> {
                return UNKNOWN;
            }
            default -> {
            }
        }
        try {
            return valueOf(cleaned);
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("未知 scenario，允许值：live, clear, unknown");
        }
    }
}
