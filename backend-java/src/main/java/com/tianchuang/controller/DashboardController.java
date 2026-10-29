package com.tianchuang.controller;

import java.util.List;
import java.util.Map;

import com.tianchuang.config.QweatherProperties;
import com.tianchuang.entity.AgentChatEntity;
import com.tianchuang.repository.AgentChatRepo;
import com.tianchuang.repository.PushLogRepo;
import com.tianchuang.service.MonitorService;
import com.tianchuang.service.PythonClient;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class DashboardController {

    private static final Logger log = LoggerFactory.getLogger(DashboardController.class);

    private final MonitorService monitor;
    private final PythonClient python;
    private final QweatherProperties qw;
    private final AgentChatRepo chatRepo;
    private final PushLogRepo pushLogRepo;

    public DashboardController(MonitorService monitor, PythonClient python,
                               QweatherProperties qw, AgentChatRepo chatRepo,
                               PushLogRepo pushLogRepo) {
        this.monitor = monitor;
        this.python = python;
        this.qw = qw;
        this.chatRepo = chatRepo;
        this.pushLogRepo = pushLogRepo;
    }

    @GetMapping("/dashboard")
    public Map<String, Object> dashboard() {
        return monitor.buildDashboard();
    }

    @PostMapping("/monitor/run-now")
    public ResponseEntity<Map<String, Object>> runNow() throws Exception {
        return ResponseEntity.ok(monitor.runOnce());
    }

    @PostMapping("/scenario/switch")
    public ResponseEntity<Map<String, Object>> switchScenario(@RequestParam String scenario) throws Exception {
        return ResponseEntity.ok(monitor.switchScenario(scenario));
    }

    @GetMapping("/config/status")
    public Map<String, Object> configStatus() {
        boolean qweatherReady = qw.jwtReady();
        Map<String, Object> dashboard = monitor.buildDashboard();
        return Map.of(
                "qweatherReady", qweatherReady,
                "configuredMode", dashboard.get("configuredMode"),
                "effectiveSource", String.valueOf(dashboard.getOrDefault("effectiveSource", "-")),
                "dataStatus", dashboard.get("dataStatus"),
                "lastSuccessAt", String.valueOf(dashboard.getOrDefault("lastRunAt", "")),
                "degraded", Boolean.TRUE.equals(dashboard.get("degraded")),
                "note", qweatherReady ? "和风凭据配置项完整，实际可用性以最近成功观测为准"
                        : "和风凭据未完整配置");
    }

    public record AskBody(String question) {
    }

    @PostMapping("/agent/ask")
    public ResponseEntity<Map<String, Object>> ask(@RequestBody AskBody body) {
        if (body == null || body.question() == null || body.question().isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "问题不能为空"));
        }
        long t0 = System.currentTimeMillis();
        Map<String, Object> dash = monitor.buildDashboard();
        String context = buildContext(dash);
        try {
            Map<String, Object> result = python.ask(body.question().trim(), context);
            AgentChatEntity e = new AgentChatEntity();
            e.question = body.question().trim();
            e.answer = String.valueOf(result.get("answer"));
            e.source = String.valueOf(result.get("source"));
            e.latencyMs = (int) (System.currentTimeMillis() - t0);
            e.workspace = com.tianchuang.config.WorkspaceContext.current();
            chatRepo.save(e);
            return ResponseEntity.ok(result);
        } catch (Exception e) {
            log.warn("智能体问答失败: {}", e.getMessage());
            return ResponseEntity.internalServerError().body(
                    Map.of("answer", "智能体服务暂时不可用，请稍后重试。", "source", "error"));
        }
    }

    @GetMapping("/push/logs")
    public List<?> pushLogs() {
        return pushLogRepo.findTop50ByOrderByTsDesc();
    }

    private String buildContext(Map<String, Object> dash) {
        Object current = dash.get("current");
        if (current instanceof Map<?, ?> c) {
            Object snap = c.get("snapshot");
            return "区域 " + dash.get("region") + "，适飞指数 " + c.get("sfi")
                    + "（" + c.get("level") + "），实时要素：" + snap;
        }
        return "暂无监测数据";
    }
}
