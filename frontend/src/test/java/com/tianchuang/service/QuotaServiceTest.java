package com.tianchuang.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.tianchuang.config.QuotaProperties;
import com.tianchuang.entity.LlmQuotaEntity;
import com.tianchuang.repository.LlmQuotaRepo;
import com.tianchuang.support.QuotaTestSupport;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.Map;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * 每日配额的行为判据。
 *
 * <p>每一条都在回答「这条判据红了会是什么样子」：不是"函数返回了 true"，
 * 而是"如果我把那个机制去掉，这条会变红"。</p>
 */
class QuotaServiceTest {

    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    /** 2026-10-15 10:00（+08）。 */
    private static final Instant DAY_1 = Instant.parse("2026-10-15T02:00:00Z");
    /** 2026-10-16 10:00（+08）—— 跨过本地日的零点。 */
    private static final Instant DAY_2 = Instant.parse("2026-10-16T02:00:00Z");

    private static final String WS_A = "ws-aaaaaa";
    private static final String WS_B = "ws-bbbbbb";
    private static final String WS_C = "ws-cccccc";
    private static final String IP = "1.2.3.4";

    private Map<String, LlmQuotaEntity> rows;
    private LlmQuotaRepo repo;

    @BeforeEach
    void setUp() {
        rows = new HashMap<>();
        repo = QuotaTestSupport.inMemoryRepo(rows);
    }

    private QuotaService service(Instant now, int workspacePerDay, int ipPerDay) {
        return new QuotaService(
                new QuotaProperties(true, workspacePerDay, ipPerDay, null, "Asia/Shanghai", 7, null),
                repo, Clock.fixed(now, ZONE));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> dimension(Map<String, Object> status, String name) {
        return (Map<String, Object>) status.get(name);
    }

    /** 恰好放行 limit 次，第 limit+1 次才拒。差一位（多放一次）就说明条件写成了 > 而不是 >=。 */
    @Test
    void allowsExactlyLimitCallsThenRejects() {
        QuotaService quota = service(DAY_1, 3, 600);

        for (int i = 1; i <= 3; i++) {
            assertThat(quota.charge(WS_A, IP).allowed())
                    .as("第 %d 次应当放行", i).isTrue();
        }

        QuotaService.Verdict rejected = quota.charge(WS_A, IP);
        assertThat(rejected.allowed()).isFalse();
        assertThat(rejected.dimension()).isEqualTo(QuotaService.DIM_WORKSPACE);
        assertThat(rejected.used()).isEqualTo(3L);
        assertThat(rejected.limit()).isEqualTo(3L);
    }

    /**
     * 核心一条：<b>换了工作区也躲不掉</b>。
     *
     * <p>工作区标识是客户端自己生成的，所以只按工作区计数等于把上限交给调用方决定。
     * 这条判据先让每个工作区都只用 1 次（都没到自己的工作区上限），第三次换了一个
     * <b>全新</b>工作区 —— 只有 IP 那一格在管，它必须把这次挡下来。</p>
     */
    @Test
    void ipDimensionCatchesWorkspaceRotation() {
        QuotaService quota = service(DAY_1, 1, 2);

        assertThat(quota.charge(WS_A, IP).allowed()).isTrue();
        assertThat(quota.charge(WS_B, IP).allowed()).isTrue();

        QuotaService.Verdict rejected = quota.charge(WS_C, IP);
        assertThat(rejected.allowed())
                .as("全新工作区的工作区配额没用过，只有 IP 那一格能拦住它").isFalse();
        assertThat(rejected.dimension()).isEqualTo(QuotaService.DIM_IP);
    }

    /**
     * 被 IP 那一格挡下来时，刚记在工作区上的那一次要退回。
     *
     * <p>不退的后果是：同一个 NAT 里别人把 IP 用满时，会连带把这个工作区自己的额度
     * 也扣掉 —— 用户看到的是"我才点了几下怎么就没了"。断言用 2 而不是 1 来让它有牙齿：
     * 去掉补偿式回退，这个数会变成 2。</p>
     */
    @Test
    void ipRejectionRefundsTheWorkspaceSlot() {
        QuotaService quota = service(DAY_1, 5, 1);

        assertThat(quota.charge(WS_A, IP).allowed()).isTrue();
        assertThat(quota.charge(WS_A, IP).allowed()).isFalse();

        Map<String, Object> workspace = dimension(quota.status(WS_A, IP), "workspace");
        assertThat(workspace)
                .containsEntry("present", true)
                .containsEntry("used", 1L)
                .as("只有第一次算它的账；第二次是被 IP 挡下的，不该记在这个工作区头上");
    }

    /** 配额按工作区分桶：A 用光了不该影响 B。 */
    @Test
    void quotaIsPerWorkspace() {
        QuotaService quota = service(DAY_1, 1, 600);

        assertThat(quota.charge(WS_A, IP).allowed()).isTrue();
        assertThat(quota.charge(WS_A, IP).allowed()).isFalse();
        assertThat(quota.charge(WS_B, IP).allowed())
                .as("B 是另一个工作区，它自己的那一格还是空的").isTrue();
    }

    /** 未标识的调用方只被 IP 那一格保护。 */
    @Test
    void unidentifiedWorkspaceIsCountedByIpOnly() {
        QuotaService quota = service(DAY_1, 5, 2);

        assertThat(quota.charge("", IP).allowed()).isTrue();
        assertThat(quota.charge(null, IP).allowed()).isTrue();
        assertThat(quota.charge("", IP).allowed()).isFalse();
    }

    /**
     * 「这个维度不适用于你」与「这一维今天用了 0 次」必须是两种渲染。
     *
     * <p>把前者渲染成 0，界面上会显示"工作区配额 0/120 已用 0 次" —— 读起来像配额
     * 正在保护他，而他其实只被 IP 那格保护着。所以未标识时**不能有 used 这个键**，
     * 而不是 used=0。</p>
     */
    @Test
    void unidentifiedWorkspaceReportsAbsentRatherThanZero() {
        QuotaService quota = service(DAY_1, 5, 600);

        Map<String, Object> workspace = dimension(quota.status("", IP), "workspace");
        assertThat(workspace).containsEntry("present", false);
        assertThat(workspace)
                .as("没这个维度 ≠ 这个维度用了 0 次")
                .doesNotContainKey("used")
                .doesNotContainKey("remaining");
    }

    /** 已标识的工作区：三项都在，remaining 随用量减少。 */
    @Test
    void identifiedWorkspaceReportsUsageAndRemaining() {
        QuotaService quota = service(DAY_1, 4, 600);
        quota.charge(WS_A, IP);
        quota.charge(WS_A, IP);

        Map<String, Object> workspace = dimension(quota.status(WS_A, IP), "workspace");
        assertThat(workspace)
                .containsEntry("present", true)
                .containsEntry("used", 2L)
                .containsEntry("limit", 4L)
                .containsEntry("remaining", 2L);
    }

    /** 跨过本地日零点即重置。键里漏掉日期的话这条会红。 */
    @Test
    void quotaResetsOnTheNextLocalDay() {
        QuotaService today = service(DAY_1, 1, 600);
        assertThat(today.charge(WS_A, IP).allowed()).isTrue();
        assertThat(today.charge(WS_A, IP).allowed()).isFalse();

        // 同一个仓库（同一张表），只是"现在"前进了一天。
        QuotaService tomorrow = service(DAY_2, 1, 600);
        assertThat(tomorrow.charge(WS_A, IP).allowed())
                .as("新的一天是新的一格").isTrue();
    }

    /**
     * 地址取不到时也不能"不计数"。
     *
     * <p>若在地址为空时直接放行，就出现了一条无需伪造即可绕开配额的路径：让地址解析
     * 失败即可。这里断言空地址落进同一个兜底桶，所以第二发同样会被挡。</p>
     */
    @Test
    void blankAddressStillCountsAgainstTheFallbackBucket() {
        QuotaService quota = service(DAY_1, 5, 1);

        assertThat(quota.charge("", null).allowed()).isTrue();
        assertThat(quota.charge("", "   ").allowed())
                .as("空地址落进 unknown 兜底桶，与上一发是同一格").isFalse();
    }

    /** 清理按保留天数删旧日，不碰保留期内的行。 */
    @Test
    void cleanupRemovesOnlyExpiredDays() {
        QuotaService quota = service(DAY_2, 5, 600);
        quota.charge(WS_A, IP);
        // 保留 7 天 ⇒ 今天是 2026-10-16，cutoff = 2026-10-09。塞一行更早的进去。
        rows.put("2026-10-01|ip|9.9.9.9",
                new LlmQuotaEntity("2026-10-01|ip|9.9.9.9", "2026-10-01", "ip", "9.9.9.9"));

        Map<String, Object> report = quota.cleanup();

        assertThat(report).containsEntry("cutoff", "2026-10-09").containsEntry("removed", 1);
        assertThat(rows).doesNotContainKey("2026-10-01|ip|9.9.9.9");
        assertThat(dimension(quota.status(WS_A, IP), "workspace"))
                .as("保留期内的行不能被清理带走").containsEntry("used", 1L);
    }
}
