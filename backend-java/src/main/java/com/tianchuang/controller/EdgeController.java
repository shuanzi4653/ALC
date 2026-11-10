package com.tianchuang.controller;

import com.tianchuang.service.PythonClient;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * 边缘节点接口透传（V1.0.1）。
 *
 * <p>节点本身走局域网直连 Python（28083/8600），这里只为**前端节点卡**提供单口访问。
 * 只读 + 上报，不提供任何"批准/放行"入口 —— 放行由人决定，见
 * {@code docs/V1.0.1-边缘节点-预留接口清单.md} §7。
 *
 * <p>开关在后端 Python 侧（{@code edge.enabled}），关掉时这些路由统一返回 503，
 * 这里不做二次判断，避免两边开关不一致。
 */
@RestController
@RequestMapping("/api/edge")
public class EdgeController {
    private final PythonClient python;

    public EdgeController(PythonClient python) {
        this.python = python;
    }

    private static String query(Map<String, String> params) {
        return params.entrySet().stream()
                .map(e -> URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8) + "="
                        + URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8))
                .collect(Collectors.joining("&"));
    }

    @GetMapping("/health")
    public ResponseEntity<?> health() throws Exception {
        return python.decisionRequest("/api/edge/health", null);
    }

    @GetMapping("/params")
    public ResponseEntity<?> params() throws Exception {
        return python.decisionRequest("/api/edge/params", null);
    }

    @GetMapping("/frames")
    public ResponseEntity<?> frames(@RequestParam Map<String, String> params) throws Exception {
        String q = query(params);
        return python.decisionRequest("/api/edge/frames" + (q.isEmpty() ? "" : "?" + q), null);
    }

    @GetMapping("/time")
    public ResponseEntity<?> time() throws Exception {
        return python.decisionRequest("/api/edge/time", null);
    }

    @GetMapping("/sites")
    public ResponseEntity<?> sites() throws Exception {
        return python.decisionRequest("/api/edge/sites", null);
    }

    @GetMapping("/nodes")
    public ResponseEntity<?> nodes() throws Exception {
        return python.decisionRequest("/api/edge/nodes", null);
    }

    @GetMapping("/nodes/{node}")
    public ResponseEntity<?> nodeDetail(@PathVariable String node,
                                        @RequestParam Map<String, String> params) throws Exception {
        String q = query(params);
        return python.decisionRequest("/api/edge/nodes/"
                + URLEncoder.encode(node, StandardCharsets.UTF_8) + (q.isEmpty() ? "" : "?" + q), null);
    }

    @GetMapping("/backfill")
    public ResponseEntity<?> backfill(@RequestParam Map<String, String> params) throws Exception {
        String q = query(params);
        return python.decisionRequest("/api/edge/backfill" + (q.isEmpty() ? "" : "?" + q), null);
    }

    @PostMapping("/register")
    public ResponseEntity<?> register(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/api/edge/register", body);
    }

    @PostMapping("/report")
    public ResponseEntity<?> report(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/api/edge/report", body);
    }

    @PostMapping("/report/batch")
    public ResponseEntity<?> reportBatch(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/api/edge/report/batch", body);
    }

    @PostMapping("/heartbeat")
    public ResponseEntity<?> heartbeat(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/api/edge/heartbeat", body);
    }
}
