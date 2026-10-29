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

/**
 * 计费端点的每日配额闸门。放在 {@link WorkspaceFilter}（{@code @Order(1)}）之后，
 * 因为配额要按工作区分格，而工作区是那一个过滤器绑到线程上的。
 *
 * <p>做成过滤器而不是在控制器里各写一句：那三个端点分属两个控制器，逐个加一定会漏 ——
 * 而漏掉的那个的判据照样全绿（它确实没报错），只是配额对它不生效。过滤器只有一处。</p>
 *
 * <p><b>只拦白名单里的路径</b>（{@code quota.paths}），不做通配。这一条是被前端轮询
 * 逼出来的：{@code /api/traffic/session} 在构建期每 2–3 秒一次，把它并进配额会让
 * "页面自己把自己用光"，症状是构建到一半开始 429、看上去像后端挂了。同理，
 * 读接口（{@code GET /api/quota} 自己、{@code /api/dashboard}）**一律不计费** ——
 * 否则"看一眼还剩多少"这件事本身会消耗额度，判据就没法自己观察自己。</p>
 */
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

    /**
     * 只对**会改状态**的请求计费：白名单命中 **且** 不是安全方法。
     *
     * <p>为什么必须有这一条（2026-10-16）：路径白名单只认 URI、不认方法，而
     * {@code /api/traffic/weather/mode} 是**一个路径两种用法** —— 前端每次打开运行台都
     * GET 它一次（读当前通道），只有操作员真的拨开关时才 POST（改通道）。路径级匹配会让
     * 每次翻页都扣一格工作区额度，于是一个纯演示的下午可以把 120 格用掉大半，而
     * 「额度用完了」这句话会出现在**什么也没干**的人面前。把读与写分开之后，白名单才有
     * 可能同时容纳"改全机状态的写端点"和"页面上天天被读的同一个路径"。</p>
     *
     * <p>顺带修掉一个反向的错：原先 {@code GET /api/agent/ask} 也会扣一格额度 —— 那是一个
     * 405，什么都不会发生，却照样计费。判据读过的是"这个请求能不能花钱/改状态"，
     * 而一个读请求两个都不能。</p>
     *
     * <p>白名单本身仍然只列举、不通配：漏掉的路径不会报错，只会静默不计费（M24 族）。</p>
     */
    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        if (!props.enabled() || !props.paths().contains(path(request))) {
            return true;
        }
        return isSafeMethod(request.getMethod());
    }

    /**
     * 是否为只读方法。{@code HEAD} 与 {@code OPTIONS} 与 {@code GET} 同类：它们在这几个
     * 端点上都不可能触发模型调用或状态变更，所以都不计费。
     */
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

    /**
     * 客户端地址。
     *
     * <p>顺序不可颠倒 —— 这不是风格问题，是安全边界：</p>
     * <ol>
     *   <li>{@code X-Real-IP}：本项目 nginx 里是 {@code proxy_set_header X-Real-IP $remote_addr}
     *       （<b>覆盖</b>写入，见 {@code snippets/AIC-tianchuang-api.conf}）。那里的
     *       {@code $remote_addr} 已被 realip 模块按外层 XFF 还原成真实客户端，所以这个值
     *       不可伪造：客户端自己发的同名头到不了这里。后端只绑回环，也保证了中间只有
     *       这一跳 nginx。</li>
     *   <li>{@code X-Forwarded-For}：<b>必须取最后一段</b>。nginx 的
     *       {@code $proxy_add_x_forwarded_for} 是「客户端发来的 XFF + 真实 $remote_addr」
     *       拼出来的，所以最左边那一段正是调用方自己写进去的。取第一段等于把 IP 配额
     *       交给调用方决定 —— 每换一个伪造前缀就换一格新配额，而"配额生效"这条判据
     *       在单客户端测试下仍然全绿。</li>
     *   <li>{@code getRemoteAddr()}：直连（本机开发、无 nginx）时的落点。</li>
     * </ol>
     */
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
        // ⚠️ 刻意不下发任何 Cookie，也不改任何身份相关的东西：429 只表达"额度用完了"，
        //    不该顺带把调用方变成另一个人。这与 nginx 的 @aic-llm-throttled 落点是同一
        //    口径 —— 两处不一致的话，被挡下来的人身份会悄悄变化，而屏幕上只看到一句
        //    "请求过于频繁"。
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ok", false);
        body.put("code", "QUOTA_EXCEEDED");
        // 两档分开写：区分"你这个工作区用完了"与"你这个出口地址用完了"。
        // 合成一句看起来更简洁，但把"是谁的额度"这件事抹掉了 —— 同一个 NAT 下的人
        // 看到同一句话，会以为是自己的操作出了问题。
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
