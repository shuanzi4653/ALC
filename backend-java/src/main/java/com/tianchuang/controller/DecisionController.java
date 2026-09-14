package com.tianchuang.controller;

import com.tianchuang.service.PythonClient;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Local facade; no arbitrary URL proxy and no external publication. */
@RestController
@RequestMapping("/api")
public class DecisionController {
    private final PythonClient python;
    public DecisionController(PythonClient python) { this.python = python; }
    @GetMapping("/traffic/{resource:network|session|weather|operations}")
    public ResponseEntity<?> traffic(@PathVariable String resource, @RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue())).collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/" + resource + "?" + query, null);
    }
    @PostMapping("/traffic/{resource:command|explain}")
    public ResponseEntity<?> trafficAction(@PathVariable String resource, @RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/" + resource, body);
    }
    @GetMapping("/observations")
    public ResponseEntity<?> observations() throws Exception { return python.decisionRequest("/observations", null); }
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
    public Map<String, Object> version() throws Exception { return Map.of("version", "1.2.0", "mode", "LOCAL_SOURCE", "python", python.decisionRequest("/health", null).getBody()); }
    private String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
}
