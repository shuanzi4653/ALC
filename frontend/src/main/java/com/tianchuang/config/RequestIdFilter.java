package com.tianchuang.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/**
 * 每个请求一个 {@code X-Request-Id}（0.11.6 / E-2）。
 *
 * <p><b>为什么要放在 Java 这一层</b>：入口是 Java（nginx → 8085 → Python 8600），
 * 我在 Python 侧加的中间件对外的响应头里看不到 —— 它加在 Java **后面**。
 * 一次请求穿过三层，只有最外那层加的头才会被浏览器看到，所以这里才是正确的位置。
 *
 * <p>已有 {@code X-Request-Id} 就沿用（nginx 或客户端可能带了），这样
 * 「用户报的那一次请求」能在三层日志里串成一条。
 *
 * <p>同时写进 MDC：日志格式里加 {@code %X{requestId}} 之后，一行日志就能看出
 * 它属于哪一次请求 —— 没有它，「这个 500 是哪个请求造成的」只能靠时间戳猜。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestIdFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Request-Id";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String incoming = request.getHeader(HEADER);
        String requestId = (incoming != null && !incoming.isBlank())
                ? incoming.trim()
                : UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        response.setHeader(HEADER, requestId);
        MDC.put("requestId", requestId);
        try {
            chain.doFilter(request, response);
        } finally {
            // 必须清：线程池会复用线程，不清就让下一个请求背上上一个的 id
            MDC.remove("requestId");
        }
    }
}
