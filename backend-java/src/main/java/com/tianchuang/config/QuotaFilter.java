package com.tianchuang.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.service.QuotaService;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(2)
public class QuotaFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(QuotaFilter.class);

    private final QuotaProperties props;
    private final QuotaService quota;
    private final ObjectMapper mapper;

    public QuotaFilter(QuotaProperties props, QuotaService quota, ObjectMapper mapper) {
        this.props = props;
        this.quota = quota;
        this.mapper = mapper;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        if (!props.enabled() || !props.paths().contains(path(request))) {
            return true;
        }
        return isSafeMethod(request.getMethod());
    }

    private static boolean isSafeMethod(String method) {
        if (method == null) {
            return false;
        }
        return switch (method.toUpperCase()) {
            case "GET", "HEAD", "OPTIONS", "TRACE" -> true;
            default -> false;
        };
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        QuotaService.Verdict verdict = quota.charge(WorkspaceContext.current(), clientAddress(request));
        if (!verdict.allowed()) {
            log.warn("配额已满：dimension={} used={}/{} path={} workspace={}",
                    verdict.dimension(), verdict.used(), verdict.limit(), path(request),
                    WorkspaceContext.current().isEmpty() ? "(未标识)" : WorkspaceContext.current());
            writeQuotaExceeded(response, verdict);
            return;
        }
        chain.doFilter(request, response);
    }

    public static String clientAddress(HttpServletRequest request) {
        String real = trim(request.getHeader("X-Real-IP"));
        if (real != null) {
            return real;
        }
        String forwarded = trim(request.getHeader("X-Forwarded-For"));
        if (forwarded != null) {
            int comma = forwarded.lastIndexOf(',');
            String last = trim(comma < 0 ? forwarded : forwarded.substring(comma + 1));
            if (last != null) {
                return last;
            }
        }
        return trim(request.getRemoteAddr());
    }

    private void writeQuotaExceeded(HttpServletResponse response, QuotaService.Verdict verdict)
            throws IOException {
        response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
        response.setContentType("application/json;charset=UTF-8");
        response.setHeader("Cache-Control", "no-store");
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ok", false);
        body.put("code", "QUOTA_EXCEEDED");
        body.put("message", QuotaService.DIM_IP.equals(verdict.dimension())
                ? "该出口地址今日调用次数已用完，请明天再试"
                : "本站今日调用次数已用完，请明天再试");
        body.put("dimension", verdict.dimension());
        body.put("used", verdict.used());
        body.put("limit", verdict.limit());
        body.put("retryable", false);
        mapper.writeValue(response.getWriter(), body);
    }

    private static String path(HttpServletRequest request) {
        String uri = request.getRequestURI();
        return uri == null ? "" : uri;
    }

    private static String trim(String value) {
        if (value == null) {
            return null;
        }
        String text = value.trim();
        return text.isEmpty() ? null : text;
    }
}
