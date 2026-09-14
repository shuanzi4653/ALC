package com.tianchuang.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.config.RuleProperties;
import com.tianchuang.model.WeatherSnapshot;

import org.junit.jupiter.api.Test;

import java.io.File;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * 规则边界回归：直接消费 tests/fixtures/rule-cases.json 这份跨语言 golden cases，
 * 保证 Java 规则与配置（config/rules-v1.json）一致，并为 Python 侧提供同一套期望值。
 * 阈值前/等于/后、多要素叠加、硬禁飞截断、非法输入全部覆盖。
 */
class SfiRuleCasesTest {

    private static final String FIXTURE = "../tests/fixtures/rule-cases.json";

    private final SfiEngine engine = new SfiEngine(new ObservationValidator(), new RuleProperties("v1", true));

    @Test
    void goldenCasesMatchConfiguredRules() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        File fixture = new File(FIXTURE);
        if (!fixture.isFile()) {
            throw new IllegalStateException("缺少规则用例夹具：" + fixture.getAbsolutePath());
        }
        JsonNode root = mapper.readTree(fixture);
        JsonNode cases = root.get("cases");
        int checked = 0;

        for (JsonNode c : cases) {
            String id = c.get("id").asText();
            WeatherSnapshot snap = toSnapshot(c.get("snapshot"));
            SfiEngine.SfiResult r = engine.evaluate(snap);
            JsonNode expect = c.get("expect");

            if (expect.has("rawSfi")) {
                assertEquals(expect.get("rawSfi").asInt(), r.rawSfi(), "[" + id + "] rawSfi");
            }
            if (expect.has("sfi")) {
                assertEquals(expect.get("sfi").asInt(), r.sfi(), "[" + id + "] sfi");
            }
            if (expect.has("level")) {
                assertEquals(expect.get("level").asText(), r.level().name(), "[" + id + "] level");
            }
            if (expect.has("hardBan")) {
                assertEquals(expect.get("hardBan").asBoolean(), r.hardBan(), "[" + id + "] hardBan");
            }
            if (expect.has("penalty")) {
                int penalty = r.checks().stream().mapToInt(SfiEngine.Check::penalty).sum();
                assertEquals(expect.get("penalty").asInt(), penalty, "[" + id + "] penalty");
            }
            checked++;
        }
        assertEquals(cases.size(), checked, "用例数量应与夹具一致");
    }

    @Test
    void invalidCasesAreRejected() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JsonNode root = mapper.readTree(new File(FIXTURE));
        JsonNode invalid = root.get("invalidCases");
        int checked = 0;

        for (JsonNode c : invalid) {
            String id = c.get("id").asText();
            WeatherSnapshot snap = toSnapshot(c.get("snapshot"));
            // 非法输入必须抛校验异常，不得静默判定为适飞
            assertThrows(IllegalArgumentException.class, () -> engine.evaluate(snap), "[" + id + "] 应拒绝非法输入");
            checked++;
        }
        assertEquals(invalid.size(), checked, "非法用例数量应与夹具一致");
    }

    /** 由夹具构造快照：未给出的字段填中性默认值；显式 JSON null 保留为 null（用于缺失校验用例）。 */
    private WeatherSnapshot toSnapshot(JsonNode n) {
        return new WeatherSnapshot(
                text(n, "time", "2026-09-11T02:00+08:00"),
                "sim",
                38.91, 121.61,
                "测试",
                num(n, "tempC", 20.0),
                num(n, "humidity", 0.5),
                num(n, "windSpeed", 5.0),
                num(n, "windGust", 5.0),
                windDegOf(n),
                num(n, "precipMmh", 0.0),
                num(n, "visibilityM", 20000.0),
                num(n, "pressureHpa", 1013.0),
                num(n, "cloudCover", 0.5),
                num(n, "thunderProb", 0.0)
        );
    }

    /** 风向：null 表示未知，0 是有效北风，不能用真假值判断。 */
    private Integer windDegOf(JsonNode n) {
        Double v = num(n, "windDeg", 0.0);
        return v == null ? null : v.intValue();
    }

    /** 取数值：字段缺失 → fallback；显式 null → null；"NaN" → Double.NaN。 */
    private Double num(JsonNode n, String field, Double fallback) {
        if (n == null || !n.has(field)) {
            return fallback;
        }
        JsonNode v = n.get(field);
        if (v.isNull()) {
            return null;
        }
        if (v.isTextual() && "NaN".equalsIgnoreCase(v.asText())) {
            return Double.NaN;
        }
        return v.asDouble();
    }

    private String text(JsonNode n, String field, String fallback) {
        return n != null && n.has(field) ? n.get(field).asText() : fallback;
    }
}
