package com.tianchuang.controller;

import com.tianchuang.service.MlInferenceRecorder;
import com.tianchuang.service.PythonClient;
import com.tianchuang.service.Track1Service;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class DecisionController {
    private final PythonClient python;
    private final MlInferenceRecorder mlRecorder;
    private final Track1Service track1;
    public DecisionController(PythonClient python, MlInferenceRecorder mlRecorder, Track1Service track1) {
        this.python = python;
        this.mlRecorder = mlRecorder;
        this.track1 = track1;
    }
    @GetMapping("/traffic/{resource:network|session|weather|operations|journal}")
    public ResponseEntity<?> traffic(@PathVariable String resource, @RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue())).collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/" + resource + "?" + query, null);
    }
    @PostMapping("/traffic/{resource:command|explain}")
    public ResponseEntity<?> trafficAction(@PathVariable String resource, @RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/" + resource, body);
    }
    @PostMapping("/traffic/operations/{action:note|disposal|dispose}")
    public ResponseEntity<?> operationsWrite(@PathVariable String action, @RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/operations/" + action, body);
    }
    @GetMapping("/traffic/weather/mode")
    public ResponseEntity<?> weatherModeStatus() throws Exception {
        return python.decisionRequest("/traffic/weather/mode", null);
    }
    @PostMapping("/traffic/weather/mode")
    public ResponseEntity<?> weatherModeSet(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/weather/mode", body);
    }
    @GetMapping("/traffic/weather/observations")
    public ResponseEntity<?> weatherObservations(@RequestParam(required = false) Boolean force) throws Exception {
        return python.decisionRequest("/traffic/weather/observations" + (Boolean.TRUE.equals(force) ? "?force=true" : ""), null);
    }
    @GetMapping("/traffic/weather/cities")
    public ResponseEntity<?> weatherCities(@RequestParam(required = false) Boolean force) throws Exception {
        return python.decisionRequest("/traffic/weather/cities" + (Boolean.TRUE.equals(force) ? "?force=true" : ""), null);
    }

    @GetMapping("/traffic/weather/models")
    public ResponseEntity<?> weatherModels(@RequestParam(required = false) Boolean force) throws Exception {
        return python.decisionRequest("/traffic/weather/models" + (Boolean.TRUE.equals(force) ? "?force=true" : ""), null);
    }
    @PostMapping("/traffic/radar/tiles")
    public ResponseEntity<?> radarTilesRelay(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/radar/tiles", body);
    }
    @PostMapping("/track1/ml")
    public ResponseEntity<?> track1Ml(@RequestBody Map<String, Object> body) throws Exception {
        ResponseEntity<?> resp = python.decisionRequest("/track1/ml", body);
        mlRecorder.record(body, resp.getBody());
        return resp;
    }
    @GetMapping("/track1/ml/status")
    public ResponseEntity<?> track1MlStatus() throws Exception {
        return python.decisionRequest("/track1/ml/status", null);
    }
    @GetMapping("/track1/ml/summary")
    public ResponseEntity<?> track1MlSummary(@RequestParam(required = false) Integer hours) {
        int window = (hours == null || hours <= 0) ? 24 : Math.min(hours, 720);
        return ResponseEntity.ok(mlRecorder.summary(window));
    }
    @PostMapping("/track1/arbitrate")
    public ResponseEntity<?> track1Arbitrate(@RequestBody Map<String, Object> body) {
        try {
            return ResponseEntity.ok(track1.arbitrate(body));
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.unprocessableEntity().body(Map.of(
                    "code", "TRACK1_RULE_ABSTAINED",
                    "message", String.valueOf(ex.getMessage()),
                    "retryable", false));
        } catch (Exception ex) {
            return ResponseEntity.status(502).body(Map.of(
                    "code", "TRACK1_UPSTREAM_FAILED",
                    "message", "轨1 推理失败：" + ex.getClass().getSimpleName(),
                    "retryable", true));
        }
    }
    @GetMapping("/observations")
    public ResponseEntity<?> observations() throws Exception { return python.decisionRequest("/observations", null); }

    @GetMapping("/traffic/v2/{resource:overview|corridors|modelcard|counterfactual|divergences|explain}")
    public ResponseEntity<?> trafficV2(@PathVariable String resource,
                                       @RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/v2/" + resource + (query.isEmpty() ? "" : "?" + query), null);
    }

    @GetMapping("/traffic/health")
    public ResponseEntity<?> trafficHealth() throws Exception {
        return python.decisionRequest("/traffic/health", null);
    }

    @GetMapping("/traffic/metrics")
    public ResponseEntity<String> trafficMetrics() throws Exception {
        return python.rawGet("/traffic/metrics");
    }

    @GetMapping("/traffic/flights")
    public ResponseEntity<?> trafficFlights(@RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/flights" + (query.isEmpty() ? "" : "?" + query), null);
    }

    @GetMapping("/traffic/flights/points")
    public ResponseEntity<?> trafficFlightsPoints(@RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/flights/points" + (query.isEmpty() ? "" : "?" + query), null);
    }

    @GetMapping("/traffic/flight/{id}")
    public ResponseEntity<?> trafficFlight(@PathVariable String id,
                                           @RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/flight/" + encode(id)
                + (query.isEmpty() ? "" : "?" + query), null);
    }

    @GetMapping("/traffic/v2/corridor/{id}")
    public ResponseEntity<?> trafficV2Corridor(@PathVariable String id,
                                               @RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/v2/corridor/" + encode(id)
                + (query.isEmpty() ? "" : "?" + query), null);
    }

    @PostMapping("/traffic/v2/decision")
    public ResponseEntity<?> trafficV2Decision(@RequestBody Map<String, Object> body) throws Exception {
        Object note = body.get("note");
        if (note == null || String.valueOf(note).isBlank()) {
            return ResponseEntity.unprocessableEntity().body(Map.of(
                    "code", "DECISION_NOTE_REQUIRED",
                    "message", "否决或回滚必须填写理由",
                    "retryable", false));
        }
        return python.decisionRequest("/traffic/v2/decision", body);
    }

    @GetMapping("/workspace/frame")
    public ResponseEntity<?> frame(@RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue())).collect(Collectors.joining("&"));
        return python.decisionRequest("/workspace/frame?" + query, null);
    }
    @PostMapping("/tasks/evaluate")
    public ResponseEntity<?> evaluate(@RequestBody Map<String, Object> body) throws Exception { return python.decisionRequest("/tasks/evaluate", body); }
    @PostMapping("/decisions/explain")
    public ResponseEntity<?> explain(@RequestBody Map<String, Object> body) throws Exception { return python.decisionRequest("/decisions/explain", body); }
    @GetMapping("/decisions")
    public ResponseEntity<?> history() throws Exception { return python.decisionRequest("/decisions", null); }
    @GetMapping("/decisions/{id:[a-f0-9]{64}}")
    public ResponseEntity<?> decision(@PathVariable String id) throws Exception { return python.decisionRequest("/decisions/" + id, null); }
    @GetMapping("/replays/{id:[a-f0-9]{64}}")
    public ResponseEntity<?> replay(@PathVariable String id) throws Exception { return python.decisionRequest("/replays/" + id, null); }
    @GetMapping("/system/version")
    public Map<String, Object> version() throws Exception {
        Map<String, Object> out = new java.util.LinkedHashMap<>();
        out.put("version", productVersion());
        out.put("mode", "LOCAL_SOURCE");
        out.put("python", python.decisionRequest("/health", null).getBody());
        return out;
    }

    private String productVersion() {
        try {
            java.nio.file.Path p = java.nio.file.Path.of("VERSION");
            if (java.nio.file.Files.isRegularFile(p)) {
                String v = java.nio.file.Files.readString(p, StandardCharsets.UTF_8).trim();
                if (!v.isEmpty()) return v;
            }
        } catch (Exception ignored) {
        }
        return "unknown";
    }
    private String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
}
