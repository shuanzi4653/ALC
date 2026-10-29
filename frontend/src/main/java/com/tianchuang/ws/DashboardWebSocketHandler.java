package com.tianchuang.ws;

import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import com.tianchuang.service.PushService;

/**
 * 大屏 WebSocket 推送（/ws/dashboard）
 * 事件类型：dashboard（全量快照）、alert（预警弹窗）
 */
@Component
public class DashboardWebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(DashboardWebSocketHandler.class);

    private final List<WebSocketSession> sessions = new CopyOnWriteArrayList<>();
    /**
     * 每个连接属于哪个匿名工作区。
     *
     * <p>握手之后的消息不再经过 {@code WorkspaceFilter}，而 WebSocket 握手在浏览器里
     * <b>发不了自定义头</b> —— 所以工作区只能从握手时带上的 Cookie 或 {@code ?ws=} 里取，
     * 并且要**存在会话上**：每次推送时再去解析一遍 URI 会把"连接时的身份"与"推送时的
     * 身份"变成两件事。</p>
     */
    private final Map<String, String> workspaceBySession = new ConcurrentHashMap<>();
    private final ObjectMapper mapper;
    private final PushService pushService;

    public DashboardWebSocketHandler(ObjectMapper mapper, PushService pushService) {
        this.mapper = mapper;
        this.pushService = pushService;
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        try {
            var root = mapper.readTree(message.getPayload());
            if (root.path("version").asInt() == 1 && "alert_ack".equals(root.path("type").asText())) {
                long eventId = root.path("payload").path("eventId").asLong(-1);
                if (eventId > 0) pushService.recordScreenAck(eventId, session.getId());
            }
        } catch (Exception e) {
            log.debug("忽略无法识别的 WS 客户端消息 session={}", session.getId());
        }
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        sessions.add(session);
        workspaceBySession.put(session.getId(), workspaceOf(session));
        log.info("大屏客户端接入: {}（当前 {} 个）", session.getId(), sessions.size());
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, org.springframework.web.socket.CloseStatus status) {
        sessions.remove(session);
        workspaceBySession.remove(session.getId());
        log.info("大屏客户端断开: {}（剩余 {} 个）", session.getId(), sessions.size());
    }

    /**
     * 握手时的身份：查询参数 → Cookie。规则与 HTTP 侧一致，见
     * {@link com.tianchuang.config.WorkspaceContext}。
     */
    private String workspaceOf(WebSocketSession session) {
        try {
            String query = session.getUri() == null ? null : session.getUri().getQuery();
            if (query != null) {
                for (String pair : query.split("&")) {
                    int eq = pair.indexOf('=');
                    if (eq > 0 && com.tianchuang.config.WorkspaceContext.QUERY.equals(pair.substring(0, eq))) {
                        String value = com.tianchuang.config.WorkspaceContext.normalize(pair.substring(eq + 1));
                        if (!com.tianchuang.config.WorkspaceContext.UNIDENTIFIED.equals(value)) {
                            return value;
                        }
                    }
                }
            }
            String cookie = session.getHandshakeHeaders().getFirst("cookie");
            if (cookie != null) {
                for (String piece : cookie.split(";")) {
                    String trimmed = piece.trim();
                    if (trimmed.startsWith(com.tianchuang.config.WorkspaceContext.COOKIE + "=")) {
                        String value = com.tianchuang.config.WorkspaceContext
                                .normalize(trimmed.substring(com.tianchuang.config.WorkspaceContext.COOKIE.length() + 1));
                        if (!com.tianchuang.config.WorkspaceContext.UNIDENTIFIED.equals(value)) {
                            return value;
                        }
                    }
                }
            }
        } catch (Exception e) {
            log.debug("解析 WS 工作区失败，按未标识处理: {}", e.getMessage());
        }
        return com.tianchuang.config.WorkspaceContext.UNIDENTIFIED;
    }

    /** 当前在线的工作区（去重）。广播要按它逐个生成载荷，见 {@code MonitorService#broadcastDashboard}。 */
    public java.util.Set<String> onlineWorkspaces() {
        return new java.util.LinkedHashSet<>(workspaceBySession.values());
    }

    /** 只发给某个工作区的连接。 */
    public int broadcastDashboardTo(String workspace, String runId, Map<String, Object> dashboard) {
        try {
            String json = mapper.writeValueAsString(Map.of(
                    "type", "dashboard", "version", 1, "runId", runId, "payload", dashboard));
            int delivered = 0;
            for (WebSocketSession s : sessions) {
                if (!workspace.equals(workspaceBySession.getOrDefault(s.getId(),
                        com.tianchuang.config.WorkspaceContext.UNIDENTIFIED))) {
                    continue;
                }
                try {
                    if (s.isOpen()) {
                        synchronized (s) {
                            s.sendMessage(new TextMessage(json));
                            delivered++;
                        }
                    }
                } catch (Exception e) {
                    log.warn("WS 推送失败 {}: {}", s.getId(), e.getMessage());
                }
            }
            return delivered;
        } catch (Exception e) {
            log.warn("Dashboard WS 序列化失败: {}", e.getMessage());
            return 0;
        }
    }

    /** 向全部在线大屏广播 JSON 消息 */
    public int broadcast(String json) {
        int delivered = 0;
        for (WebSocketSession s : sessions) {
            try {
                if (s.isOpen()) {
                    synchronized (s) {
                        s.sendMessage(new TextMessage(json));
                        delivered++;
                    }
                }
            } catch (Exception e) {
                log.warn("WS 推送失败 {}: {}", s.getId(), e.getMessage());
            }
        }
        return delivered;
    }

    public int clientCount() {
        return sessions.size();
    }

    public void broadcastDashboard(String runId, Map<String, Object> dashboard) {
        try {
            broadcast(mapper.writeValueAsString(Map.of(
                    "type", "dashboard", "version", 1, "runId", runId, "payload", dashboard)));
        } catch (Exception e) {
            log.warn("Dashboard WS 序列化失败: {}", e.getMessage());
        }
    }

    public int broadcastAlert(String runId, Map<String, Object> alert) {
        try {
            return broadcast(mapper.writeValueAsString(Map.of(
                    "type", "alert", "version", 1, "runId", runId, "payload", alert)));
        } catch (Exception e) {
            log.warn("Alert WS 序列化失败: {}", e.getMessage());
            return 0;
        }
    }
}
