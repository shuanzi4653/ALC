package com.tianchuang.config;

/**
 * 操作身份：把「这一次请求是谁在操作」带到 Python 侧（0.11.6 / E-3）。
 *
 * <p><b>它不是认证。</b>没有密码、没有会话、没有签名 —— 它只是一个自报的家门。
 * 之所以值得加，是因为现在<b>任何人都能点"否决"</b>（{@code security.enabled}
 * 默认 false、{@code permitAllChain} 全放行），而 journal 里只记了"有人否决"，
 * 没记"谁"。加了之后：能追溯，但仍然不假装它是凭据。</p>
 *
 * <p><b>为什么不放进 Cookie</b>：Cookie 会引出"过期 → 401 → 跳登录页"那整条链路，
 * 而 2026-10-14 拆掉登录门的原因就是现场撞 401 是致命的。请求头不会过期。</p>
 *
 * <p>与 {@link WorkspaceContext} 同构：ThreadLocal + 一个 Filter + 在
 * {@code PythonClient.builder()} 里统一透传。<b>必须走那个唯一出口</b> ——
 * 六个方法各自加头，迟早有一个忘掉，而忘掉的那条链路会安静地按"观察员"降级。</p>
 */
public final class OperatorContext {

    public static final String HEADER = "X-ALC-Operator";

    private static final ThreadLocal<String> CURRENT = new ThreadLocal<>();

    private OperatorContext() {
    }

    public static void set(String operator) {
        if (operator == null || operator.isBlank()) CURRENT.remove();
        else CURRENT.set(operator.trim());
    }

    /** 没有请求上下文时返回 null（不是空串）—— 让调用方看得见"没人"这件事。 */
    public static String current() {
        return CURRENT.get();
    }

    public static void clear() {
        CURRENT.remove();
    }
}
