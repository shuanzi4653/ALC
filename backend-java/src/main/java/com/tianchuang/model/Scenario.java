package com.tianchuang.model;

import java.util.Locale;

public enum Scenario {
    LIVE, CLEAR, UNKNOWN;

    public String key() {
        return name().toLowerCase(Locale.ROOT);
    }

    public boolean needsWeather() {
        return this == LIVE;
    }

    public static Scenario parse(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("scenario 不能为空");
        }
        String cleaned = value.trim().toUpperCase(Locale.ROOT);
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
