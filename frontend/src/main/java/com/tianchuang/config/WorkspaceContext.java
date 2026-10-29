package com.tianchuang.config;

import java.util.function.Supplier;
import java.util.regex.Pattern;

/**
 * 匿名工作区：把同一进程里的可变状态按「哪个浏览器」分开。
 *
 * <p>界面不再有登录门（2026-10-14 用户决定），于是服务端<b>没有</b>任何能区分调用方的
 * 东西 —— 而 Python 侧的计划键原本只由 (种子, 情景, 气象通道, 快照) 算出，所以两个浏览器
 * 用默认参数打开就是<b>同一份计划、同一份操作日志、同一个口径开关</b>：屏幕上看起来是
 * 两个用户，服务端看起来只有一个人。</p>
 *
 * <p>这里是"谁"这件事在 Java 侧的<b>唯一</b>来源：请求头 {@code X-ALC-Workspace}
 * （前端生成并存在本浏览器），Cookie {@code alc_ws} 与查询参数 {@code ?ws=} 作为退路
 * —— WebSocket 握手在浏览器里发不了自定义头。</p>
 *
 * <p><b>缺席时落回空串，而空串是「未标识」，不是一个默认工作区。</b>没有标识的调用方
 * （巡检探针、curl、既有单元测试）看到的就是改造之前的那一份全局数据；把"没带标识"与
 * "带了标识"并进同一个桶，会让"改造前行为保持"这条判据失去意义 —— 判据必须能区分这两
 * 种情况，否则它量不出回归。</p>
 */
public final class WorkspaceContext {

    public static final String HEADER = "X-ALC-Workspace";
    public static final String COOKIE = "alc_ws";
    public static final String QUERY = "ws";
    public static final String UNIDENTIFIED = "";

    /**
     * 6..64 位安全字符。<b>不纠正、只拒绝</b>：把非法值"清洗"成合法值，会让两个不同的
     * 客户端被清洗进同一个空间（例如都变成同一个前缀），那是最难发现的一类串号。
     */
    private static final Pattern PATTERN = Pattern.compile("^[A-Za-z0-9_-]{6,64}$");

    private static final ThreadLocal<String> CURRENT = ThreadLocal.withInitial(() -> UNIDENTIFIED);

    private WorkspaceContext() {
    }

    /** 合法则原样返回，否则落回「未标识」。 */
    public static String normalize(String value) {
        if (value == null) {
            return UNIDENTIFIED;
        }
        String text = value.trim();
        return PATTERN.matcher(text).matches() ? text : UNIDENTIFIED;
    }

    public static String current() {
        return CURRENT.get();
    }

    public static void set(String value) {
        CURRENT.set(normalize(value));
    }

    /**
     * 清掉当前线程的绑定。<b>必须在请求结束时调用</b>：Tomcat 的线程是复用的，泄漏出去的
     * 工作区会让下一个请求在别人的命名空间里跑，症状是随机的、只在并发下出现。
     */
    public static void clear() {
        CURRENT.remove();
    }

    /** 在一段代码里以指定工作区运行（用于广播：同一份数据要按每个在线工作区各算一次）。 */
    public static <T> T call(String workspace, Supplier<T> body) {
        String previous = current();
        set(workspace);
        try {
            return body.get();
        } finally {
            set(previous);
        }
    }
}
