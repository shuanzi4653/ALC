package com.tianchuang.controller;

import com.tianchuang.service.MonitorService;
import com.tianchuang.ws.DashboardWebSocketHandler;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/health")
public class HealthController {
    private final MonitorService monitor;
    private final DashboardWebSocketHandler ws;

    public HealthController(MonitorService monitor, DashboardWebSocketHandler ws) {
        this.monitor = monitor;
        this.ws = ws;
    }

    @GetMapping("/live")
    public Map<String, Object> live() {
        return Map.of("status", "UP", "service", "tianchuang-java");
    }

    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        Map<String, Object> dashboard = monitor.buildDashboard();
        boolean ready = dashboard.get("current") != null && "FRESH".equals(dashboard.get("dataStatus"));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", ready ? "READY" : "NOT_READY");
        result.put("runId", dashboard.get("runId"));
        result.put("runStatus", dashboard.get("status"));
        result.put("dataStatus", dashboard.get("dataStatus"));
        result.put("effectiveSource", dashboard.get("effectiveSource"));
        result.put("degraded", dashboard.get("degraded"));
        result.put("lastAttempt", dashboard.get("lastAttempt"));
        result.put("websocketClients", ws.clientCount());
        return ResponseEntity.status(ready ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE).body(result);
    }
}
