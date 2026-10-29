package com.tianchuang.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 把 {@code X-ALC-Operator} 从请求头取出来放进 {@link OperatorContext}（0.11.6 / E-3）。
 *
 * <p>顺序要在 {@link WorkspaceFilter} **之前**：两者互不依赖，但身份与工作区
 * 都属于"这一条请求的上下文"，先设谁后设谁没有区别，排在一起是因为读代码的人
 * 应该一眼看到"这一层干的两件事是同一类"。</p>
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
public class OperatorFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        OperatorContext.set(request.getHeader(OperatorContext.HEADER));
        try {
            chain.doFilter(request, response);
        } finally {
            // 线程池会复用线程：不清就让下一个请求背上上一个操作员的名字，
            // 而 journal 会因此记错人 —— 这种错查起来极慢。
            OperatorContext.clear();
        }
    }
}
