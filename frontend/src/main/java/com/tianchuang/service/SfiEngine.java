package com.tianchuang.service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.tianchuang.model.FlightLevel;
import com.tianchuang.model.RuleSpec;
import com.tianchuang.model.WeatherSnapshot;
import com.tianchuang.config.RuleProperties;

import org.springframework.stereotype.Service;

/**
 * 轨1：数据驱动规则基线（L1，必做层）
 * 阈值、比较方向、扣分与等级边界全部来自 {@link RuleProperties}（config/rules-v1.json），
 * 代码不硬编码数值，保证规则可审计、可版本化。
 * 特点：全程可解释（逐要素扣分明细），永不失灵。
 */
@Service
public class SfiEngine {

    private final ObservationValidator validator;
    private final RuleProperties rules;

    public SfiEngine(ObservationValidator validator, RuleProperties rules) {
        this.validator = validator;
        this.rules = rules;
    }

    /** 要素检查结果 */
    public record Check(String factor, double value, String unit, boolean banned,
                        boolean warn, int penalty, String note) {
    }

    public record SfiResult(int sfi, int rawSfi, FlightLevel level, boolean hardBan,
                            String ruleVersion, List<Check> checks,
                            List<String> unavailableOptional) {
    }    public SfiResult evaluate(WeatherSnapshot s) {
        validator.validate(s);
        List<Check> checks = new ArrayList<>();
        int penalty = 0;
        List<String> unavailableOptional = new ArrayList<>();

        for (RuleSpec.FactorRule f : rules.factors()) {
            Double raw = rawValue(f.key(), s);
            if (raw == null) {
                // 该要素取不到值。两条路要分开走，否则「源本就不提供」会被当成故障：
                //   required  → 本该有却没有，本轮不可信，交由校验层拒绝；
                //   !required → 源不发布此要素（如雷暴概率），弃权即是正确行为。
                if (f.required()) {
                    throw new IllegalArgumentException(f.label() + "缺失或超出有效范围");
                }
                unavailableOptional.add(f.label());
                continue;
            }
            double v = raw;
            boolean banned = f.banned(v);
            boolean warn = !banned && f.warn(v);
            int p = banned ? f.penaltyBan() : warn ? f.penaltyWarn() : 0;
            String note = banned ? f.noteBan() : warn ? f.noteWarn() : f.noteOk();
            checks.add(new Check(f.label(), f.display(v), f.unit(), banned, warn, p, note));
            penalty += p;
        }

        int rawSfi = Math.max(0, Math.min(100, 100 - penalty));
        boolean hardBan = rules.hardBanEnabled() && checks.stream().anyMatch(Check::banned);
        int sfi = hardBan ? Math.min(rawSfi, rules.hardBanSfiCap()) : rawSfi;
        FlightLevel level = hardBan ? FlightLevel.BAN : levelFromSfi(sfi);
        return new SfiResult(sfi, rawSfi, level, hardBan, rules.version(), checks,
                List.copyOf(unavailableOptional));
    }

    /**
     * 不作气象声明的降级结果：没有任何要素可判，因此**不产出 checks、不扣分**。
     *
     * <p>它与「满分适飞」的区别由调用方按 {@code unavailableOptional} 的「全部要素」如实标注
     * （{@code MonitorService} 的 CLEAR/UNKNOWN 分支即如此）。之所以不能用 {@code evaluate()}
     * 代劳——全 null 快照会让必需要素校验直接拒绝本轮，这正是修复前的故障形态。
     */
    public SfiResult abstain() {
        return new SfiResult(100, 100, FlightLevel.FIT, false, rules.version(), List.of(),
                rules.factors().stream().map(RuleSpec.FactorRule::label).toList());
    }

    /** 按配置的等级边界判定（不再使用硬编码 80/60/40）。 */
    private FlightLevel levelFromSfi(int sfi) {
        RuleSpec.LevelBounds b = rules.levels();
        if (sfi >= b.fit()) return FlightLevel.FIT;
        if (sfi >= b.caution()) return FlightLevel.CAUTION;
        if (sfi >= b.danger()) return FlightLevel.DANGER;
        return FlightLevel.BAN;
    }

    /** 从观测快照提取规则要素原始值；未知返回 null（不补零、不视为安全）。 */
    private Double rawValue(String key, WeatherSnapshot s) {
        return switch (key) {
            case "windSpeed" -> s.windSpeed();
            case "windGust" -> s.windGust();
            case "precipMmh" -> s.precipMmh();
            case "visibilityM" -> s.visibilityM();
            case "thunderProb" -> s.thunderProb();
            case "tempC" -> s.tempC();
            default -> null;
        };
    }

    /** 转为可序列化 Map（供前端/存储） */
    public Map<String, Object> toMap(SfiResult r) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("sfi", r.sfi());
        m.put("rawSfi", r.rawSfi());
        m.put("level", r.level().name());
        m.put("levelLabel", r.level().label);
        m.put("color", r.level().color);
        m.put("hardBan", r.hardBan());
        m.put("ruleVersion", r.ruleVersion());
        // 明确列出「源不提供因而弃权」的要素：它既不是「已检查且正常」，
        // 也不是「检查失败」，界面上必须能与二者区分。
        m.put("unavailableOptional", r.unavailableOptional());
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
