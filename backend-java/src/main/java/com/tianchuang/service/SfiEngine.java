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

@Service
public class SfiEngine {

    private final ObservationValidator validator;
    private final RuleProperties rules;

    public SfiEngine(ObservationValidator validator, RuleProperties rules) {
        this.validator = validator;
        this.rules = rules;
    }

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

    public SfiResult abstain() {
        return new SfiResult(100, 100, FlightLevel.FIT, false, rules.version(), List.of(),
                rules.factors().stream().map(RuleSpec.FactorRule::label).toList());
    }

    private FlightLevel levelFromSfi(int sfi) {
        RuleSpec.LevelBounds b = rules.levels();
        if (sfi >= b.fit()) return FlightLevel.FIT;
        if (sfi >= b.caution()) return FlightLevel.CAUTION;
        if (sfi >= b.danger()) return FlightLevel.DANGER;
        return FlightLevel.BAN;
    }

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

    public Map<String, Object> toMap(SfiResult r) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("sfi", r.sfi());
        m.put("rawSfi", r.rawSfi());
        m.put("level", r.level().name());
        m.put("levelLabel", r.level().label);
        m.put("color", r.level().color);
        m.put("hardBan", r.hardBan());
        m.put("ruleVersion", r.ruleVersion());
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
