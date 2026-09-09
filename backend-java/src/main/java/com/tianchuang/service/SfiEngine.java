package com.tianchuang.service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.tianchuang.model.FlightLevel;
import com.tianchuang.model.WeatherSnapshot;

import org.springframework.stereotype.Service;

/**
 * 轨1：数据驱动规则基线（L1，必做层）
 * 依据计划书 5.2 节适飞指数阈值体系，输出 SFI（0-100）与四级窗口等级。
 * 特点：全程可解释（逐要素扣分明细），永不失灵。
 */
@Service
public class SfiEngine {

    /** 要素检查结果 */
    public record Check(String factor, double value, String unit, boolean banned,
                        boolean warn, int penalty, String note) {
    }

    public record SfiResult(int sfi, FlightLevel level, List<Check> checks) {
    }

    public SfiResult evaluate(WeatherSnapshot s) {
        List<Check> checks = new ArrayList<>();
        int penalty = 0;

        // 平均风速：≤8 适飞 / ≥12 禁飞
        double w = s.windSpeed();
        checks.add(new Check("平均风速", w, "m/s", w >= 12, w >= 8,
                w >= 12 ? 40 : w >= 8 ? 22 : 0,
                w >= 12 ? "达禁飞阈值" : w >= 8 ? "超适飞阈值" : "正常"));
        penalty += checks.get(checks.size() - 1).penalty();

        // 阵风：≤12 适飞 / ≥18 禁飞
        double g = s.windGust();
        checks.add(new Check("阵风风速", g, "m/s", g >= 18, g >= 12,
                g >= 18 ? 30 : g >= 12 ? 16 : 0,
                g >= 18 ? "达禁飞阈值" : g >= 12 ? "超适飞阈值" : "正常"));
        penalty += checks.get(checks.size() - 1).penalty();

        // 降水：0 适飞 / ≥5 禁飞
        double p = s.precipMmh();
        checks.add(new Check("降水强度", p, "mm/h", p >= 5, p >= 1,
                p >= 5 ? 35 : p >= 1 ? 15 : 0,
                p >= 5 ? "达禁飞阈值" : p >= 1 ? "出现降水" : "无降水"));
        penalty += checks.get(checks.size() - 1).penalty();

        // 能见度：≥5km 适飞 / ≤1km 禁飞
        double v = s.visibilityM();
        checks.add(new Check("能见度", v / 1000, "km", v <= 1000, v <= 5000,
                v <= 1000 ? 30 : v <= 5000 ? 12 : 0,
                v <= 1000 ? "低于禁飞阈值" : v <= 5000 ? "偏低" : "良好"));
        penalty += checks.get(checks.size() - 1).penalty();

        // 雷暴概率：≤20% 适飞 / ≥60% 禁飞
        double t = s.thunderProb();
        checks.add(new Check("雷暴概率", t * 100, "%", t >= 0.6, t >= 0.2,
                t >= 0.6 ? 35 : t >= 0.2 ? 12 : 0,
                t >= 0.6 ? "过高" : t >= 0.2 ? "存在风险" : "低"));
        penalty += checks.get(checks.size() - 1).penalty();

        // 温度：-10~40 适飞 / <-20 或 >45 禁飞
        double tc = s.tempC();
        boolean tempBan = tc < -20 || tc > 45;
        boolean tempWarn = tc < -10 || tc > 40;
        checks.add(new Check("温度", tc, "℃", tempBan, tempWarn,
                tempBan ? 30 : tempWarn ? 10 : 0,
                tempBan ? "超出安全范围" : tempWarn ? "接近边界" : "正常"));
        penalty += checks.get(checks.size() - 1).penalty();

        int sfi = Math.max(0, Math.min(100, 100 - penalty));
        return new SfiResult(sfi, FlightLevel.fromSfi(sfi), checks);
    }

    /** 转为可序列化 Map（供前端/存储） */
    public Map<String, Object> toMap(SfiResult r) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("sfi", r.sfi());
        m.put("level", r.level().name());
        m.put("levelLabel", r.level().label);
        m.put("color", r.level().color);
        m.put("checks", r.checks().stream().map(c -> {
            Map<String, Object> cm = new LinkedHashMap<>();
            cm.put("factor", c.factor());
            cm.put("value", round(c.value()));
            cm.put("unit", c.unit());
            cm.put("banned", c.banned());
            cm.put("warn", c.warn());
            cm.put("penalty", c.penalty());
            cm.put("note", c.note());
            return cm;
        }).toList());
        return m;
    }

    private double round(double v) {
        return Math.round(v * 10.0) / 10.0;
    }
}
