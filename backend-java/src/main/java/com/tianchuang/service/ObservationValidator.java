package com.tianchuang.service;

import com.tianchuang.model.WeatherSnapshot;
import org.springframework.stereotype.Component;

@Component
public class ObservationValidator {

    public void validate(WeatherSnapshot s) {
        if (s == null) throw new IllegalArgumentException("气象快照不能为空");
        bounded("纬度", s.lat(), -90, 90);
        bounded("经度", s.lon(), -180, 180);
        bounded("温度", s.tempC(), -100, 70);
        bounded("湿度", s.humidity(), 0, 1);
        bounded("平均风速", s.windSpeed(), 0, 150);
        bounded("阵风", s.windGust(), 0, 200);
        bounded("降水强度", s.precipMmh(), 0, 500);
        bounded("能见度", s.visibilityM(), 0, 100_000);
        bounded("气压", s.pressureHpa(), 800, 1_100);
        bounded("云量", s.cloudCover(), 0, 1);
        bounded("雷暴概率", s.thunderProb(), 0, 1);
        if (s.windDeg() != null && (s.windDeg() < 0 || s.windDeg() > 360)) {
            throw new IllegalArgumentException("风向必须在 0–360 度之间");
        }
        boolean declaresNoObservationTime = WeatherSnapshot.TIME_BASIS_NOT_PROVIDED.equals(s.timeBasis());
        boolean hasTime = s.time() != null && !s.time().isBlank();
        if (declaresNoObservationTime && hasTime) {
            throw new IllegalArgumentException(
                    "声明了「来源不提供观测时刻」，却同时给出了观测时间：" + s.time());
        }
        if (!declaresNoObservationTime && !hasTime) {
            throw new IllegalArgumentException("观测时间不能为空");
        }
    }

    private void bounded(String name, Double value, double min, double max) {
        if (value == null) return;
        if (!Double.isFinite(value)) {
            throw new IllegalArgumentException(name + "不是有限数值");
        }
        if (value < min || value > max) {
            throw new IllegalArgumentException(name + "超出有效范围");
        }
    }
}
