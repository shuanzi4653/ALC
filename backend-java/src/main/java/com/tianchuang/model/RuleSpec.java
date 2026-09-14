package com.tianchuang.model;

import java.util.List;

/**
 * 版本化规则配置（对应 config/rules-v1.json）。
 * 阈值、比较方向、扣分与等级边界均由配置驱动，Java 与 Python 读取同一文件以保持一致。
 */
public record RuleSpec(String version, boolean hardBanEnabled, int hardBanSfiCap,
                       LevelBounds levels, List<FactorRule> factors) {

    /** 等级边界：sfi >= fit → 适飞；>= caution → 谨慎；>= danger → 危险；否则禁飞。 */
    public record LevelBounds(int fit, int caution, int danger) {
        public LevelBounds {
            fit = fit <= 0 ? 80 : fit;
            caution = caution <= 0 ? 60 : caution;
            danger = danger <= 0 ? 40 : danger;
        }
    }

    /**
     * 单要素规则。
     * direction=high：value >= banValue 禁飞，>= warnValue 警戒（风速/阵风/降水/雷暴概率）
     * direction=low ：value <= banValue 禁飞，<= warnValue 警戒（能见度）
     * direction=range：value 落在 [warnLow,warnHigh] 外警戒，落在 [banLow,banHigh] 外禁飞（温度）
     */
    public record FactorRule(
            String key, String label, String unit, String direction,
            Double warnValue, Double banValue,
            Double warnLow, Double warnHigh, Double banLow, Double banHigh,
            int penaltyWarn, int penaltyBan,
            Double displayDivisor, Double displayMultiplier,
            String noteOk, String noteWarn, String noteBan) {

        public FactorRule {
            direction = direction == null || direction.isBlank() ? "high" : direction;
            displayDivisor = displayDivisor == null || displayDivisor == 0 ? 1.0 : displayDivisor;
            displayMultiplier = displayMultiplier == null || displayMultiplier == 0 ? 1.0 : displayMultiplier;
            noteOk = noteOk == null ? "正常" : noteOk;
            noteWarn = noteWarn == null ? "警戒" : noteWarn;
            noteBan = noteBan == null ? "达禁飞阈值" : noteBan;
        }

        /** 是否命中禁飞阈值 */
        public boolean banned(double v) {
            return switch (direction) {
                case "low" -> banValue != null && v <= banValue;
                case "range" -> (banLow != null && v < banLow) || (banHigh != null && v > banHigh);
                default -> banValue != null && v >= banValue;
            };
        }

        /** 是否命中警戒阈值（禁飞时不再重复计警戒） */
        public boolean warn(double v) {
            return switch (direction) {
                case "low" -> warnValue != null && v <= warnValue;
                case "range" -> (warnLow != null && v < warnLow) || (warnHigh != null && v > warnHigh);
                default -> warnValue != null && v >= warnValue;
            };
        }

        /** 按单位换算后的展示值（能见度 → km，雷暴概率 → %） */
        public double display(double raw) {
            return raw / displayDivisor * displayMultiplier;
        }
    }

    public RuleSpec {
        version = version == null || version.isBlank() ? "v1" : version;
        hardBanSfiCap = hardBanSfiCap <= 0 ? 39 : hardBanSfiCap;
        levels = levels == null ? new LevelBounds(80, 60, 40) : levels;
        factors = factors == null || factors.isEmpty() ? defaultFactors() : List.copyOf(factors);
    }

    /**
     * 内置兜底规则：与 v1 初始阈值等价。
     * 仅在配置文件缺失/解析失败，或测试手工构造时使用；正常运行时以 JSON 为准。
     */
    public static RuleSpec defaults(String version, boolean hardBanEnabled) {
        return new RuleSpec(version, hardBanEnabled, 39, new LevelBounds(80, 60, 40), defaultFactors());
    }

    public static List<FactorRule> defaultFactors() {
        return List.of(
                new FactorRule("windSpeed", "平均风速", "m/s", "high",
                        8.0, 12.0, null, null, null, null, 22, 40, null, null,
                        "正常", "超适飞阈值", "达禁飞阈值"),
                new FactorRule("windGust", "阵风风速", "m/s", "high",
                        12.0, 18.0, null, null, null, null, 16, 30, null, null,
                        "正常", "超适飞阈值", "达禁飞阈值"),
                new FactorRule("precipMmh", "降水强度", "mm/h", "high",
                        1.0, 5.0, null, null, null, null, 15, 35, null, null,
                        "无降水", "出现降水", "达禁飞阈值"),
                new FactorRule("visibilityM", "能见度", "km", "low",
                        5000.0, 1000.0, null, null, null, null, 12, 30, 1000.0, null,
                        "良好", "偏低", "低于禁飞阈值"),
                new FactorRule("thunderProb", "雷暴概率", "%", "high",
                        0.2, 0.6, null, null, null, null, 12, 35, null, 100.0,
                        "低", "存在风险", "过高"),
                new FactorRule("tempC", "温度", "℃", "range",
                        null, null, -10.0, 40.0, -20.0, 45.0, 10, 30, null, null,
                        "正常", "接近边界", "超出安全范围")
        );
    }
}
