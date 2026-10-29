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
