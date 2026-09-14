package com.tianchuang.service;

import com.tianchuang.model.WeatherSnapshot;
import org.springframework.stereotype.Component;

/** 在规则计算前拒绝缺失、非有限值及明显错误的单位/范围。 */
@Component
public class ObservationValidator {

    public void validate(WeatherSnapshot s) {
        if (s == null) throw new IllegalArgumentException("气象快照不能为空");
        required("纬度", s.lat(), -90, 90);
        required("经度", s.lon(), -180, 180);
        required("温度", s.tempC(), -100, 70);
        required("湿度", s.humidity(), 0, 1);
        required("平均风速", s.windSpeed(), 0, 150);
        required("阵风", s.windGust(), 0, 200);
        required("降水强度", s.precipMmh(), 0, 500);
        required("能见度", s.visibilityM(), 0, 100_000);
        required("气压", s.pressureHpa(), 800, 1_100);
        required("云量", s.cloudCover(), 0, 1);
        required("雷暴概率", s.thunderProb(), 0, 1);
        if (s.windDeg() != null && (s.windDeg() < 0 || s.windDeg() > 359)) {
            throw new IllegalArgumentException("风向必须在 0–359 度之间");
        }
        if (s.time() == null || s.time().isBlank()) {
            throw new IllegalArgumentException("观测时间不能为空");
        }
    }

    private void required(String name, Double value, double min, double max) {
        if (value == null || !Double.isFinite(value) || value < min || value > max) {
            throw new IllegalArgumentException(name + "缺失或超出有效范围");
        }
    }
}
