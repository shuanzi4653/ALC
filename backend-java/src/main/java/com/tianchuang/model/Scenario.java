package com.tianchuang.model;

import java.util.Locale;

/** 支持的确定性模拟剧本。 */
public enum Scenario {
    CLEAR, WIND, RAIN, STORM;

    public String key() {
        return name().toLowerCase(Locale.ROOT);
    }

    public static Scenario parse(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("scenario 不能为空");
        }
        try {
            return valueOf(value.trim().toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("未知 scenario，允许值：clear, wind, rain, storm");
        }
    }
}
