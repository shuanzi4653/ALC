package com.tianchuang.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.tianchuang.config.RuleProperties;
import com.tianchuang.model.FlightLevel;
import com.tianchuang.model.WeatherSnapshot;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SfiEngineTest {
    private SfiEngine engine;

    @BeforeEach
    void setUp() {
        engine = new SfiEngine(new ObservationValidator(), new RuleProperties("test-v1", true));
    }

    @Test
    void clearWeatherIsFit() {
        var result = engine.evaluate(snapshot(4, 7, 0, 12_000, 0.05, 25));
        assertThat(result.level()).isEqualTo(FlightLevel.FIT);
        assertThat(result.sfi()).isEqualTo(100);
        assertThat(result.hardBan()).isFalse();
        assertThat(result.ruleVersion()).isEqualTo("test-v1");
    }

    @Test
    void rainfallAtHardThresholdForcesBanAndPreservesRawScore() {
        var result = engine.evaluate(snapshot(4, 7, 5, 12_000, 0.05, 25));
        assertThat(result.rawSfi()).isEqualTo(65);
        assertThat(result.sfi()).isEqualTo(39);
        assertThat(result.level()).isEqualTo(FlightLevel.BAN);
        assertThat(result.hardBan()).isTrue();
    }

    @Test
    void valuesImmediatelyBeforeThresholdDoNotHardBan() {
        var result = engine.evaluate(snapshot(11.9, 17.9, 4.99, 1001, 0.59, 45));
        assertThat(result.hardBan()).isFalse();
        assertThat(result.level()).isNotEqualTo(FlightLevel.FIT);
    }

    @Test
    void temperatureLimitsAreCheckedOnBothSides() {
        assertThat(engine.evaluate(snapshot(4, 7, 0, 12_000, 0.05, -20.1)).hardBan()).isTrue();
        assertThat(engine.evaluate(snapshot(4, 7, 0, 12_000, 0.05, 45.1)).hardBan()).isTrue();
    }

    @Test
    void missingOrNonFiniteValuesAreRejectedInsteadOfAssumedSafe() {
        WeatherSnapshot missingWind = new WeatherSnapshot("2026-09-09T10:00:00+08:00", "test",
                38.91, 121.61, "晴", 25.0, 0.5, null, 7.0, null,
                0.0, 12_000.0, 1010.0, 0.2, 0.05);
        assertThatThrownBy(() -> engine.evaluate(missingWind)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> engine.evaluate(snapshot(Double.NaN, 7, 0, 12_000, 0.05, 25)))
                .isInstanceOf(IllegalArgumentException.class);
    }

    private WeatherSnapshot snapshot(double wind, double gust, double rain,
                                     double visibility, double thunder, double temp) {
        return new WeatherSnapshot("2026-09-09T10:00:00+08:00", "test", 38.91, 121.61,
                "测试", temp, 0.6, wind, gust, 180, rain, visibility, 1010.0, 0.6, thunder);
    }
}
