package com.tianchuang.model;

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
