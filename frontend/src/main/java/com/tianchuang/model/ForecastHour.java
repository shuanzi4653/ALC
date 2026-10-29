package com.tianchuang.model;

/**
 * 标准化逐小时预报
 */
public record ForecastHour(
        String time,
        double tempC,
        double windSpeed,
        double windGust,
        double precipMmh,
        double visibilityM,
        double thunderProb) {
}
