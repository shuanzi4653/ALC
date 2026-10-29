package com.tianchuang.config;

import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 大模型 / 写全机端点的每日配额（2026-10-14 拆掉登录门之后取代会话门）。
 *
 * <p>拆门之后服务端不再认识"谁" —— 于是任何拿到链接的人都能 POST
 * {@code /api/agent/ask}（烧 DeepSeek 额度）或 {@code /api/monitor/run-now}
 * （改全机状态）。nginx 的 {@code limit_req} 只约束<b>频率</b>（20 r/m/源 IP），
 * 约束不了<b>总量</b>：慢速持续调用照样能在一天里把额度烧完。本配置就是补这一格。</p>
 *
 * <p><b>两个维度都要算，缺一不可。</b>工作区标识由前端生成、存在客户端，所以
 * 「换一个工作区」就等于「换一格新配额」—— 只按工作区计数的话，一个循环里改
 * {@code X-ALC-Workspace} 就能无限调用，而那条判据（"超限会 429"）在单用户测试下
 * <p>反过来只按 IP 也不成立：同一 NAT / 校园网 / 机房里可能有多个真实
 * 用户，按 IP 卡死会把他们一起拒掉。所以 IP 那一格是<b>兜底</b>，必须显著大于工作区
 * 那一格。</p>
 *
 * <p><b>这一段的唯一来源是这里的默认值</b>（编进产物、任何机器上都一样、可从仓库复现）。
 * 刻意<b>不</b>往 {@code config/application.yml} 再抄一份：抄一份就有两个来源，本地改了、
 * 服务器没改，就是一次静默漂移 —— 而这个项目已经吃过多次"两处写同一个数"的账（M70/M81）。
 * 要按部署环境调，走已有的覆盖机制（`.env` 里 {@code QUOTA_WORKSPACE_PER_DAY} /
 * {@code QUOTA_IP_PER_DAY} 等，Spring 松绑定直接映射到 {@code quota.*}）。
 * <b>生效值随时用 {@code GET /api/quota} 读</b> —— 它报的是实际在用的 limit，
 * 而不是某个文件里的字面量（"配置写了"与"配置生效"是两件事）。</p>
 */
@ConfigurationProperties(prefix = "quota")
public record QuotaProperties(Boolean enabled, Integer workspacePerDay, Integer ipPerDay,
                              List<String> paths, String zone, Integer keepDays, String cleanupCron) {

    /**
     * 计费端点：**每一个会花钱或会改全机状态的写端点**。
     *
     * <p>改这里就要同步改 {@code conf.d/AIC-tianchuang-upstream.conf} 的 map ——
     * 两份名单必须**逐条相同**。2026-10-16 之前它们只有三条，而当天按"这个端点能不能
     * 花钱/改全机状态"把公开面上的写端点过了一遍，补上两条漏掉的：</p>
     *
     * <ul>
     *   <li>{@code /api/decisions/explain} —— <b>第二个 explain 入口，同样调用大模型</b>。
     *       它与 {@code /api/traffic/explain} 并列存在（分别走 {@code decision_service} 与
     *       {@code traffic_operations} 两套证据），第一条在名单里、第二条不在。漏掉的那条
     *       判据照样全绿——它确实没报错，只是配额对它不生效。</li>
     *   <li>{@code /api/scenario/switch} —— 与 {@code run-now} 同源，都会跑一整轮监测
     *       （含轨2 大模型），只是入口不同。</li>
     *   <li>{@code /api/traffic/weather/mode} —— 改的是**全机共用**的气象通道，不是调用方
     *       自己那份会话。注意它是"一个路径两种用法"：读用 GET、改用 POST，所以计费闸门
     *       按方法区分（见 {@code QuotaFilter#shouldNotFilter}），否则每次打开运行台都会
     *       扣一格。</li>
     * </ul>
     *
     * <p><b>刻意不在名单里的两类</b>（写下来，因为"没写"和"想过之后没写"在代码上长得一样）：</p>
     * <ul>
     *   <li>会话内写操作 {@code /api/traffic/command} 与 {@code /api/traffic/operations/*}：
     *       它们只改调用方自己那次计划，不花钱、不外溢；而 120 格/天的工作区额度是给
     *       "正常值班操作"用的，把它们并进来会让一次正常演示自己把自己挡住 ——
     *       与 {@code /api/traffic/session} 被排除的理由相同，只是那一条已经写在
     *       {@code QuotaFilter} 的注释里。</li>
     *   <li>读接口一律不计费（含 {@code GET /api/quota} 自己），否则"看一眼还剩多少"
     *       会消耗额度，判据就没法观察自己。</li>
     * </ul>
     */
    public static final List<String> DEFAULT_PATHS = List.of(
            "/api/agent/ask",
            "/api/traffic/explain",
            "/api/decisions/explain",
            "/api/monitor/run-now",
            "/api/scenario/switch",
            "/api/traffic/weather/mode");

    public QuotaProperties {
        enabled = enabled == null || enabled;
        // 120 次/工作区/天：够一个演示者把每个点都点几遍，不够把 500 万 token 的额度烧穿。
        workspacePerDay = workspacePerDay == null || workspacePerDay <= 0 ? 120 : workspacePerDay;
        // 600 次/IP/天 = 5 个工作区的量。它是兜底不是主判据，宁可松、不可误伤共享出口。
        ipPerDay = ipPerDay == null || ipPerDay <= 0 ? 600 : ipPerDay;
        paths = paths == null || paths.isEmpty() ? DEFAULT_PATHS : List.copyOf(paths);
        // 「一天」按哪个时区切。不写成隐式的：服务器 TZ 一改，跨天点就静默平移，
        // 而"今天用完了"这件事看起来仍然正常。
        zone = zone == null || zone.isBlank() ? "Asia/Shanghai" : zone;
        keepDays = keepDays == null || keepDays <= 0 ? 7 : keepDays;
        cleanupCron = cleanupCron == null || cleanupCron.isBlank() ? "0 45 3 * * *" : cleanupCron;
    }
}
