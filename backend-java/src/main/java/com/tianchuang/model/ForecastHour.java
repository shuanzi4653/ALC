package com.tianchuang.model;

public record ForecastHour(
        String time,
        double tempC,
        double windSpeed,
        double windGust,
        double precipMmh,
        double visibilityM,
        double thunderProb) {
}
