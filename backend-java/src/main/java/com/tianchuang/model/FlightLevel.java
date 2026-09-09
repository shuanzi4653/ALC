package com.tianchuang.model;

/**
 * 适飞指数等级（四级窗口）
 */
public enum FlightLevel {
    FIT("适飞", 90, "#2e8b57"),
    CAUTION("谨慎", 70, "#d98a2b"),
    DANGER("危险", 50, "#d85a30"),
    BAN("禁飞", 25, "#c0392b");

    public final String label;
    public final int refSfi;
    public final String color;

    FlightLevel(String label, int refSfi, String color) {
        this.label = label;
        this.refSfi = refSfi;
        this.color = color;
    }

    /** 风险概率映射（用于双轨加权融合） */
    public double riskProb() {
        return switch (this) {
            case FIT -> 0.10;
            case CAUTION -> 0.40;
            case DANGER -> 0.70;
            case BAN -> 0.95;
        };
    }

    public static FlightLevel fromSfi(int sfi) {
        if (sfi >= 80) return FIT;
        if (sfi >= 60) return CAUTION;
        if (sfi >= 40) return DANGER;
        return BAN;
    }
}
