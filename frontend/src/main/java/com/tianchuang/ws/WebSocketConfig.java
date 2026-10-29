package com.tianchuang.ws;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

/**
 * WebSocket 端点注册
 *
 * <p>允许的来源（Origin）白名单。2026-10-14 起公网入口是域名
 * {@code https://tianchuang.shuanzi.site}（Nginx 443 终结 TLS 后反代到
 * 127.0.0.1:28081），因此必须显式放通该来源，否则浏览器握手会被判跨域而
 * 拒绝（403），前端表现为「连接状态」一直重连。
 *
 * <p>回环两条保留：SSH 隧道调试与 Nginx 侧万一回退到归一化 Origin 时仍可用。
 * 注意 Nginx 现在是把**真实 Origin 透传**过来的（见
 * {@code .run/cloud/AIC-tianchuang-api.conf} 里 {@code proxy_set_header Origin
 * $http_origin;}），所以这里加上域名是必要项、不是可选优化。
 *
 * <p>无 Origin 头的非浏览器请求（curl / 探针）由 Spring 侧直接放行，不在此表约束内。
 */
@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final DashboardWebSocketHandler handler;

    public WebSocketConfig(DashboardWebSocketHandler handler) {
        this.handler = handler;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(handler, "/ws/dashboard")
                .setAllowedOriginPatterns(
                        "https://tianchuang.shuanzi.site",
                        "http://127.0.0.1:*",
                        "http://localhost:*");
    }
}
