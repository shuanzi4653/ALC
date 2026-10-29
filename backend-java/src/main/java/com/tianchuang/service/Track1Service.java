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

@Service
public class Track1Service {

    private static final Logger log = LoggerFactory.getLogger(Track1Service.class);

    private final SfiEngine rules;
    private final PythonClient python;
    private final FusionService fusion;
    private final MlInferenceRecorder recorder;
    private final ObjectMapper mapper = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    public Track1Service(SfiEngine rules, PythonClient python, FusionService fusion,
                         MlInferenceRecorder recorder) {
        this.rules = rules;
        this.python = python;
        this.fusion = fusion;
        this.recorder = recorder;
    }

    public Map<String, Object> arbitrate(Map<String, Object> body) throws Exception {
        Map<String, Object> request = body == null ? Map.of() : body;
        @SuppressWarnings("unchecked")
        Map<String, Object> snapshot = request.get("snapshot") instanceof Map
                ? (Map<String, Object>) request.get("snapshot") : Map.of();
        if (snapshot.isEmpty()) {
            throw new IllegalArgumentException("snapshot 为空：没有要素就没有档位");
        }

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
        arbitration.put("confidence", decided.confidence());
        out.put("arbitration", arbitration);

        Map<String, Object> forRecorder = new LinkedHashMap<>(request);
        forRecorder.put("ruleLevel", ruleResult.level().name());
        recorder.record(forRecorder, model == null
                ? Map.of("available", false, "status", "MODEL_UNAVAILABLE")
                : model);
        return out;
    }

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
            return null;
        }
    }

    private Double numberOrNull(Object value) {
        if (value instanceof Number n) return n.doubleValue();
        return null;
    }
}
