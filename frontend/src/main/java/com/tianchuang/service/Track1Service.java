package com.tianchuang.service;

import java.util.LinkedHashMap;
import java.util.Map;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.model.FlightLevel;
import com.tianchuang.model.WeatherSnapshot;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 轨1 一次完整裁决：规则（硬底线）→ 模型（能力增量）→ 融合（安全优先）。
 *
 * <p><b>为什么把三件事收在一个服务里，而不是让前端各发两个请求再自己比档位：</b>
 * 因为"模型能不能让结论更乐观"是一条安全规则，不是一段展示逻辑。放在前端比档位，
 * 意味着<b>另一处</b>（报告、导出、以后的小程序）要把同一条规则再实现一遍，
 * 而两处实现的分歧在界面上表现为"同一个班次，两个页面两个档"。</p>
 *
 * <p><b>模型故障不许拖垮规则。</b>Python 挂掉、模型文件缺失、响应超时 —— 三种情况都让
 * {@code model} 为 null，裁决落 {@code MODEL_UNAVAILABLE}，规则结果照常返回。
 * 反过来（规则故障）则整条请求失败：没有规则底线的档位不是"保守"，是"没有依据"。</p>
 */
@Service
public class Track1Service {

    private static final Logger log = LoggerFactory.getLogger(Track1Service.class);

    private final SfiEngine rules;
    private final PythonClient python;
    private final FusionService fusion;
    private final MlInferenceRecorder recorder;
    private final ObjectMapper mapper = new ObjectMapper()
            // 前端把整份 `weather.snapshot` 递进来时会带上 rainMmh / month 这类模型用不到的键。
            // 严格模式会因此 400 —— 而那不是"输入错了"，只是多给了东西。
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    public Track1Service(SfiEngine rules, PythonClient python, FusionService fusion,
                         MlInferenceRecorder recorder) {
        this.rules = rules;
        this.python = python;
        this.fusion = fusion;
        this.recorder = recorder;
    }

    /**
     * @param body 至少含 {@code snapshot}；可含 {@code timeBasis} / {@code hour} / {@code month}
     * @throws IllegalArgumentException 规则要素缺失或越界 —— 调用方应转 422，**不要**降级成 FIT
     */
    public Map<String, Object> arbitrate(Map<String, Object> body) throws Exception {
        Map<String, Object> request = body == null ? Map.of() : body;
        @SuppressWarnings("unchecked")
        Map<String, Object> snapshot = request.get("snapshot") instanceof Map
                ? (Map<String, Object>) request.get("snapshot") : Map.of();
        if (snapshot.isEmpty()) {
            throw new IllegalArgumentException("snapshot 为空：没有要素就没有档位");
        }

        // 前端递进来的是一份"读数"，没有观测时刻声明。不声明会被校验层按"该有却没有"拒绝，
        // 而这里缺的其实只是"来源不提供"这句话 —— 补上它，而不是伪造一个本机时刻。
        Map<String, Object> snapDoc = new LinkedHashMap<>(snapshot);
        if (request.get("timeBasis") instanceof String basis) {
            snapDoc.put("timeBasis", basis);
        } else if (!snapDoc.containsKey("time")) {
            snapDoc.put("timeBasis", WeatherSnapshot.TIME_BASIS_NOT_PROVIDED);
        }

        WeatherSnapshot snap = mapper.convertValue(snapDoc, WeatherSnapshot.class);
        SfiEngine.SfiResult ruleResult = rules.evaluate(snap);

        Map<String, Object> model = requestModel(request, snapshot);
        FlightLevel modelLevel = model == null ? null : flightLevelOf(model.get("level"));
        Double modelConfidence = model == null ? null : numberOrNull(model.get("confidence"));

        FusionService.Track1Result decided = fusion.arbitrateTrack1(
                ruleResult.level(), modelLevel, modelConfidence);

        // 注意：这里处处用 LinkedHashMap 而不是 `Map.of` —— `Map.of` 拒绝 null 值，
        // 而"模型没参与"这件事天然要用 null 表达（confidence 为 null ≠ 0）。
        // 用 `Map.of` 的写法会在"模型缺席"这条路径上抛 NPE：即**最需要它工作的时候**崩。
        Map<String, Object> out = new LinkedHashMap<>();
        Map<String, Object> rule = new LinkedHashMap<>();
        rule.put("level", ruleResult.level().name());
        rule.put("levelLabel", ruleResult.level().label);
        rule.put("sfi", ruleResult.sfi());
        rule.put("rawSfi", ruleResult.rawSfi());
        rule.put("hardBan", ruleResult.hardBan());
        rule.put("ruleVersion", ruleResult.ruleVersion());
        rule.put("reasons", ruleResult.checks().stream()
                .filter(c -> c.banned() || c.warn())
                .map(c -> c.factor() + " " + c.value() + c.unit() + " " + c.note())
                .toList());
        rule.put("checks", ruleResult.checks());
        rule.put("unavailableOptional", ruleResult.unavailableOptional());
        out.put("rule", rule);

        out.put("model", model);

        Map<String, Object> arbitration = new LinkedHashMap<>();
        arbitration.put("decision", decided.decision().name());
        arbitration.put("decisionLabel", decided.decisionLabel());
        arbitration.put("level", decided.level().name());
        arbitration.put("levelLabel", decided.level().label);
        // 模型未参与时留 null，不写 0：界面上「置信度 0%」与「没有模型」是两句话。
        arbitration.put("confidence", decided.confidence());
        out.put("arbitration", arbitration);

        // 留痕：把规则档位一并交给 recorder，让它能算出"一致 / 不一致 / 不可比"。
        Map<String, Object> forRecorder = new LinkedHashMap<>(request);
        forRecorder.put("ruleLevel", ruleResult.level().name());
        recorder.record(forRecorder, model == null
                ? Map.of("available", false, "status", "MODEL_UNAVAILABLE")
                : model);
        return out;
    }

    /**
     * 问模型。**任何失败都返回 null**，不抛、不降级成一个档位。
     *
     * <p>三条失败路径分开记日志，因为排查方向完全不同：Python 不通（网络/进程）、
     * 模型文件缺失（部署）、响应结构不符（版本错配）。</p>
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> requestModel(Map<String, Object> request, Map<String, Object> snapshot) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("snapshot", snapshot);
        if (request.get("hour") != null) payload.put("hour", request.get("hour"));
        if (request.get("month") != null) payload.put("month", request.get("month"));
        try {
            var resp = python.decisionRequest("/track1/ml", payload);
            if (resp.getStatusCode().is2xxSuccessful() && resp.getBody() instanceof Map<?, ?> body) {
                return (Map<String, Object>) body;
            }
            log.warn("轨1 模型调用被拒（HTTP {}）：本轮按「模型未参与」处理",
                    resp.getStatusCode().value());
            return null;
        } catch (Exception ex) {
            log.warn("轨1 模型调用失败（{}）：本轮按「模型未参与」处理", ex.toString());
            return null;
        }
    }

    private FlightLevel flightLevelOf(Object value) {
        if (!(value instanceof String text)) return null;
        try {
            return FlightLevel.valueOf(text.trim().toUpperCase());
        } catch (IllegalArgumentException ex) {
            // 未知档位 = 不可用。**不要**默认成 FIT —— 那会把"模型说了个我们不认识的词"
            // 变成"模型认为适飞"。
            return null;
        }
    }

    private Double numberOrNull(Object value) {
        if (value instanceof Number n) return n.doubleValue();
        return null;
    }
}
