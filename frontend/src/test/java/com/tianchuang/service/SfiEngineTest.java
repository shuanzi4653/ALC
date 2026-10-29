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
    void absentOptionalFactorAbstainsInsteadOfFailingTheRound() {
        // 真实源的形状：open-meteo 不发布雷暴字段，thunderProb 恒为 null，其余齐全。
        // 回归判据（0.9.25）：修复前这会抛 IllegalArgumentException，
        // 让每一轮监测以 INVALID_INPUT 失败、/api/health/ready 永久 503。
        WeatherSnapshot realSourceShape = new WeatherSnapshot("2026-09-09T10:00:00+08:00", "test",
                38.91, 121.61, "晴", 15.6, 0.52, 2.27, 4.6, 248,
                0.0, 8760.0, 1013.4, 0.0, null,
                WeatherSnapshot.TIME_BASIS_OBSERVED);
        var result = engine.evaluate(realSourceShape);
        assertThat(result.hardBan()).isFalse();
        // 缺席的可选要素不产出 check（扣不了分），但要被点名，界面才能如实说「源不提供」。
        assertThat(result.checks()).noneMatch(c -> c.factor().equals("雷暴概率"));
        assertThat(result.unavailableOptional()).containsExactly("雷暴概率");
        assertThat(result.checks()).anyMatch(c -> c.factor().equals("平均风速"));
    }

    @Test
    void absentRequiredFactorStillRejectsTheRound() {
        // 必需要素缺席＝本该有却没有，本轮不可信——这条契约不能被上一条放松。
        WeatherSnapshot missingWind = new WeatherSnapshot("2026-09-09T10:00:00+08:00", "test",
                38.91, 121.61, "晴", 25.0, 0.5, null, 7.0, null,
                0.0, 12_000.0, 1010.0, 0.2, 0.05,
                WeatherSnapshot.TIME_BASIS_OBSERVED);
        assertThatThrownBy(() -> engine.evaluate(missingWind))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("平均风速");
    }

    @Test
    void clearScenarioAllAbsentSnapshotDoesNotThrow() {
        // CLEAR/UNKNOWN 分支构造全 null 快照：所有要素都缺席。
        // 必需要素全缺席，故这条路径仍会被拒绝——因此必须显式走「不作气象声明」的降级，
        // 不能直接丢给规则引擎（见 MonitorService 的 CLEAR 分支处理）。
        WeatherSnapshot none = new WeatherSnapshot("2026-09-09T10:00:00+08:00", "none",
                38.91, 121.61, null, null, null, null, null, null,
                null, null, null, null, null,
                WeatherSnapshot.TIME_BASIS_OBSERVED);
        assertThatThrownBy(() -> engine.evaluate(none))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void nonFiniteAndOutOfRangeValuesAreRejectedEvenForOptionalFactors() {
        // NaN 是「声称了值却站不住脚」，与缺席不同，必须拒绝。
        assertThatThrownBy(() -> engine.evaluate(snapshot(Double.NaN, 7, 0, 12_000, 0.05, 25)))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> engine.evaluate(snapshot(Double.POSITIVE_INFINITY, 7, 0, 12_000, 0.05, 25)))
                .isInstanceOf(IllegalArgumentException.class);
        // 越界值即便非空也必须拒绝：湿度 1.5 不可能成立。
        WeatherSnapshot badHumidity = new WeatherSnapshot("2026-09-09T10:00:00+08:00", "test",
                38.91, 121.61, "晴", 25.0, 1.5, 4.0, 7.0, 180,
                0.0, 12_000.0, 1010.0, 0.2, 0.05,
                WeatherSnapshot.TIME_BASIS_OBSERVED);
        assertThatThrownBy(() -> engine.evaluate(badHumidity)).isInstanceOf(IllegalArgumentException.class);
    }

    private WeatherSnapshot snapshot(double wind, double gust, double rain,
                                     double visibility, double thunder, double temp) {
        return new WeatherSnapshot("2026-09-09T10:00:00+08:00", "test", 38.91, 121.61,
                "测试", temp, 0.6, wind, gust, 180, rain, visibility, 1010.0, 0.6, thunder,
                WeatherSnapshot.TIME_BASIS_OBSERVED);
    }
}
