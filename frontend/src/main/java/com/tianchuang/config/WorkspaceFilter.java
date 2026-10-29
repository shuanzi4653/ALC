package com.tianchuang.config;

import java.io.IOException;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 把匿名工作区绑到这次请求上（解析规则见 {@link WorkspaceContext}）。
 *
 * <p>做成过滤器而不是给每个控制器加一个 {@code @RequestHeader} 参数：这一侧有十几个
 * 控制器，逐个加参数一定会漏掉一个 —— 而漏掉的那个会安静地按"未标识"读全局数据，
 * 并且它自己的判据照样全绿（它确实没报错）。过滤器只有一处，漏不掉。</p>
 *
 * <p>取值顺序：头 → Cookie → 查询参数。头排第一是因为它以 {@code Authorization} 式的
 * 方式随每个 fetch 走；Cookie 是 WebSocket 握手唯一的载体；查询参数是最后退路
 * （手工 curl 排查时最方便）。</p>
 */
@Component
@Order(1)
public class WorkspaceFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        WorkspaceContext.set(resolve(request));
        try {
            chain.doFilter(request, response);
        } finally {
            WorkspaceContext.clear();
        }
    }

    /** 供 WebSocket 握手复用：握手后的消息不再经过过滤器，工作区要从会话上自己取。 */
    public static String resolve(HttpServletRequest request) {
        String fromHeader = WorkspaceContext.normalize(request.getHeader(WorkspaceContext.HEADER));
        if (!WorkspaceContext.UNIDENTIFIED.equals(fromHeader)) {
            return fromHeader;
        }
        if (request.getCookies() != null) {
            for (Cookie cookie : request.getCookies()) {
                if (WorkspaceContext.COOKIE.equals(cookie.getName())) {
                    String fromCookie = WorkspaceContext.normalize(cookie.getValue());
                    if (!WorkspaceContext.UNIDENTIFIED.equals(fromCookie)) {
                        return fromCookie;
                    }
                }
            }
        }
        return WorkspaceContext.normalize(request.getParameter(WorkspaceContext.QUERY));
    }
}
