package com.tianchuang.service;

import com.tianchuang.config.QuotaProperties;
import com.tianchuang.entity.LlmQuotaEntity;
import com.tianchuang.repository.LlmQuotaRepo;

import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.LinkedHashMap;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * 每日配额：把"一天之内最多能烧多少次大模型 / 能改几次全机状态"钉住。
 *
 * <p>判据形状是「<b>先判后加</b>」：任一维度已达上限就直接拒、且不加；两维都能加才加。
 * 这样 {@code used} 永远 {@code <= limit}，{@code status()} 报出来的余量不会出现负数或者
 * "limit+1"这种读起来像 bug 的数。</p>
 *
 * <p>「两维都要加」是刻意的：工作区标识由客户端生成，所以只按工作区计数等于把上限交给
 * 调用方决定（换一个字符串就是一格新配额）；而只按 IP 计数会把同一个 NAT 下的真实用户
 * 连坐。两个都算，任一超限即拒 —— 前者挡住"同一个人刷"，后者挡住"同一个人换身份刷"。
 * IP 那格拒绝时会把刚加在工作区上的那一格<b>减回去</b>：那格不是他用的，不该记他账上。</p>
 *
 * <p><b>本方法刻意不加 {@code @Transactional}：</b>两维的两次自增各自是一个独立事务
 * （见 {@link LlmQuotaRepo} 上的 {@code @Transactional}）。合并成一个事务看起来更"原子"，
 * 但会把"插行时撞并发"这种正常情况变成"整个事务回滚"，反而让配额在并发下少记。
 * 代价是两维之间不是原子的 —— 用上面那次补偿式回退补上，语义上够用（漏记一格不是漏洞，
 * 多记一格才会误伤用户）。</p>
 */
@Service
public class QuotaService {

    private static final Logger log = LoggerFactory.getLogger(QuotaService.class);

    public static final String DIM_WORKSPACE = "workspace";
    public static final String DIM_IP = "ip";

    /**
     * 地址取不到时的落点。**不留"两个维度都没有 ⇒ 不计数"这条路**：那会变成一个
     * 无需任何伪造就能绕开配额的缺口（只要让地址解析失败）。地址是 HTTP 请求里
     * 一定存在的东西，真取不到也要记进同一个兜底桶里。
     */
    public static final String UNKNOWN_ADDRESS = "unknown";

    /** {@code allowed=false} 时 {@code dimension} 说明是哪一格满了。 */
    public record Verdict(boolean allowed, String dimension, long used, long limit) {
    }

    private final QuotaProperties props;
    private final LlmQuotaRepo repo;
    private final Clock clock;

    @Autowired
    public QuotaService(QuotaProperties props, LlmQuotaRepo repo) {
        this(props, repo, Clock.system(ZoneId.of(props.zone())));
    }

    /**
     * 注入时钟。生产走上面那个两参构造（时区取 {@code quota.zone}）；测试注入固定时钟，
     * 否则"跨天会重置"这条判据没法在一天之内量出来 —— 而它正是这个类最容易写错的地方
     * （键里漏掉日期，每天重置就永远不发生，而所有单日用例仍然全绿）。
     */
    public QuotaService(QuotaProperties props, LlmQuotaRepo repo, Clock clock) {
        this.props = props;
        this.repo = repo;
        this.clock = clock;
    }

    /** 计入一格。放行返回 {@code allowed=true}；某一维已满则返回该维的名字与用量。 */
    public Verdict charge(String workspace, String clientAddress) {
        String day = today();
        Integer wsLimit = props.workspacePerDay();
        String ws = identified(workspace) ? workspace : null;

        if (ws != null && bump(day, DIM_WORKSPACE, ws, wsLimit) == 0) {
            return new Verdict(false, DIM_WORKSPACE, usedOf(day, DIM_WORKSPACE, ws), wsLimit);
        }

        // 地址兜底成 "unknown"：见 UNKNOWN_ADDRESS 的注释。
        String ip = blank(clientAddress) ? UNKNOWN_ADDRESS : clientAddress;
        Integer ipLimit = props.ipPerDay();
        if (bump(day, DIM_IP, ip, ipLimit) == 0) {
            if (ws != null) {
                repo.decrement(bucket(day, DIM_WORKSPACE, ws));
            }
            return new Verdict(false, DIM_IP, usedOf(day, DIM_IP, ip), ipLimit);
        }
        return new Verdict(true, "", 0L, 0L);
    }

    /**
     * 调用方自己的今日用量。只暴露"你自己"这两格，不返回任何别人或全机汇总的用量。
     *
     * <p>未标识的工作区返回 {@code present=false} 而<b>不是</b> {@code used=0}：
     * 「这个维度不适用于你」与「这一维今天用了 0 次」是两件事，前者渲染成 0 会让人
     * 以为配额在保护他 —— 而他其实只被 IP 那格保护着。</p>
     */
    public Map<String, Object> status(String workspace, String clientAddress) {
        String day = today();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("enabled", props.enabled());
        out.put("day", day);
        out.put("zone", props.zone());
        out.put("workspace", usage(day, DIM_WORKSPACE, identified(workspace) ? workspace : null,
                props.workspacePerDay()));
        out.put("ip", usage(day, DIM_IP, blank(clientAddress) ? UNKNOWN_ADDRESS : clientAddress,
                props.ipPerDay()));
        return out;
    }

    @Scheduled(cron = "${quota.cleanup-cron:0 45 3 * * *}")
    public void scheduledCleanup() {
        try {
            log.info("配额台账清理完成：{}", cleanup());
        } catch (Exception e) {
            // 必须带异常栈：HistoryRetentionService 就是只留一句 message，
            // 结果「原始类型返回告警」被当成无害噪音、一个多月没人查（2026-10-24）。
            log.error("配额台账清理失败（保留期外台账未回收）", e);
        }
    }

    /** 删掉保留期之外的日子。返回删了几行，便于人工核对与测试断言。 */
    public Map<String, Object> cleanup() {
        String cutoff = LocalDate.now(clock).minusDays(props.keepDays()).toString();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("cutoff", cutoff);
        out.put("removed", repo.deleteByDayLessThan(cutoff));
        return out;
    }

    String today() {
        return LocalDate.now(clock).toString();
    }

    public static boolean identified(String workspace) {
        return !blank(workspace);
    }

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private int bump(String day, String dimension, String key, int limit) {
        String bucket = bucket(day, dimension, key);
        if (!repo.existsById(bucket)) {
            try {
                repo.saveAndFlush(new LlmQuotaEntity(bucket, day, dimension, key));
            } catch (DataIntegrityViolationException race) {
                // 并发下另一个线程刚好也插了同一格。这不是错：行已经在了，继续走 UPDATE。
                log.debug("配额桶 {} 已被并发创建", bucket);
            }
        }
        return repo.incrementWithinLimit(bucket, limit);
    }

    private long usedOf(String day, String dimension, String key) {
        return repo.findById(bucket(day, dimension, key)).map(row -> (long) row.used).orElse(0L);
    }

    private Map<String, Object> usage(String day, String dimension, String key, int limit) {
        if (key == null) {
            return Map.of("present", false);
        }
        long used = usedOf(day, dimension, key);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("present", true);
        out.put("used", used);
        out.put("limit", (long) limit);
        out.put("remaining", Math.max(0L, limit - used));
        return out;
    }

    private static String bucket(String day, String dimension, String key) {
        return day + "|" + dimension + "|" + key;
    }
}
