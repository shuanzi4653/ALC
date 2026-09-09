package com.tianchuang.ws;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

/**
 * 大屏 WebSocket 推送（/ws/dashboard）
 * 事件类型：dashboard（全量快照）、alert（预警弹窗）
 */
@Component
public class DashboardWebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(DashboardWebSocketHandler.class);

    private final List<WebSocketSession> sessions = new CopyOnWriteArrayList<>();
    private final ObjectMapper mapper = new ObjectMapper();

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        sessions.add(session);
        log.info("大屏客户端接入: {}（当前 {} 个）", session.getId(), sessions.size());
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, org.springframework.web.socket.CloseStatus status) {
        sessions.remove(session);
        log.info("大屏客户端断开: {}（剩余 {} 个）", session.getId(), sessions.size());
    }

    /** 向全部在线大屏广播 JSON 消息 */
    public void broadcast(String json) {
        for (WebSocketSession s : sessions) {
            try {
                if (s.isOpen()) {
                    synchronized (s) {
                        s.sendMessage(new TextMessage(json));
                    }
                }
            } catch (Exception e) {
                log.warn("WS 推送失败 {}: {}", s.getId(), e.getMessage());
            }
        }
    }

    public int clientCount() {
        return sessions.size();
    }
}
