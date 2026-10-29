package com.tianchuang.model;

public record WeatherSnapshot(
        String time,
        String source,
        Double lat,
        Double lon,
        String conditionText,
        Double tempC,
        Double humidity,
        Double windSpeed,
        Double windGust,
        Integer windDeg,
        Double precipMmh,
        Double visibilityM,
        Double pressureHpa,
        Double cloudCover,
        Double thunderProb,
        String timeBasis) {

    public static final String TIME_BASIS_OBSERVED = "OBSERVED";

    public static final String TIME_BASIS_NOT_PROVIDED = "NOT_PROVIDED_BY_PROVIDER";

    public static final String TIME_BASIS_UNSPECIFIED = "UNSPECIFIED";
}
