package com.tianchuang.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.tianchuang.config.HistoryProperties;
import com.tianchuang.entity.SfiRecordEntity;
import com.tianchuang.repository.SfiRecordRepo;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 历史保留策略的**真库**判据（E02）。
 *
 * <h2>这条测试为什么必须存在</h2>
 * 2026-10-18 至 10-24 连续 7 天，生产上 {@code HistoryRetentionService} 每天
 * 3:30 都在报同一句 WARN 后放弃：
 * <pre>
 * 历史清理失败：Null return value from advice does not match primitive return type for:
 * public abstract long com.tianchuang.repository.SfiRecordRepo.deleteByTsBefore(LocalDateTime)
 * </pre>
 * 也就是说**七张历史表一行都没删过**，数据只增不减。而全量单元测试一直全绿 ——
 * 因为那些测试全用 Mockito 假仓库，`deleteByTsBefore` 永远返回你想要的那个数字，
 * **这个失败在结构上就不在它们射程里**。
 *
 * <h2>为什么必须 {@code NOT_SUPPORTED}</h2>
 * {@code @DataJpaTest} 默认把测试方法包在事务里。而生产上的失败恰恰发生在
 * **没有外层事务**的时候（{@code scheduledCleanup()} 直接调 {@code cleanup()}，
 * 同类自调用不走 Spring 代理，方法上的 {@code @Transactional} 不生效）。
 * 用默认事务跑这条测试，等于把要复现的前提改掉了 —— 它会绿，而线上仍是红的。
 *
 * <h2>判据为什么是「行真的没了」而不是「没有 WARN」</h2>
 * 日志不报错只说明没抛异常。真正的缺陷是**数据没被删**，所以断言落在
 * 「超期行消失 + 未超期行留下」这一对上 —— 少任何一半都测不出「删过头」或「没删」。
 */
@DataJpaTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:historyretention;MODE=MySQL;DB_CLOSE_DELAY=-1",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.jpa.hibernate.ddl-auto=validate",
        "spring.flyway.enabled=true",
        "spring.flyway.locations=classpath:db/migration",
        "history.retention-days=30"
})
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@EnableConfigurationProperties(HistoryProperties.class)
@Import(HistoryRetentionService.class)
@Transactional(propagation = Propagation.NOT_SUPPORTED)
class HistoryRetentionTest {

    @Autowired
    HistoryRetentionService service;

    @Autowired
    SfiRecordRepo sfiRepo;

    /**
     * 超期（40 天前）的必须被删，未超期（今天）的必须留下。
     *
     * <p>断言按 {@code runId} 查、不按 {@code count()} 比 —— 两个测试共用同一个
     * 内存库（{@code DB_CLOSE_DELAY=-1}，这是有意的：建库迁移只跑一次），
     * 于是绝对行数会随测试执行顺序变，而"这一行在不在"不会。</p>
     */
    @Test
    void 清理必须真删掉超期行且不碰未超期行() {
        LocalDateTime now = LocalDateTime.now();
        sfiRepo.saveAndFlush(sfi(now.minusDays(40), "stale-run"));
        sfiRepo.saveAndFlush(sfi(now, "fresh-run"));

        assertThat(sfiRepo.findFirstByRunId("stale-run")).as("前置：超期行已写入").isPresent();
        assertThat(sfiRepo.findFirstByRunId("fresh-run")).as("前置：未超期行已写入").isPresent();

        // 走与生产完全同一条路径：scheduledCleanup → 同类自调用 cleanup()
        service.scheduledCleanup();

        assertThat(sfiRepo.findFirstByRunId("stale-run"))
                .as("超期行必须真的消失（不是只打一条 WARN 就算过）")
                .isEmpty();
        assertThat(sfiRepo.findFirstByRunId("fresh-run"))
                .as("未超期行不许被删")
                .isPresent();
    }

    /**
     * 清理必须**幂等**：没有超期行时再跑一次，不许抛异常、不许删任何东西。
     *
     * <p>生产上这个任务每天无条件跑一次，库很可能是空的（刚部署、或已清过）。
     * 如果空表时抛异常，那就算上一次修好了，只要某天没有超期数据，第二天又会开始失败。</p>
     */
    @Test
    void 没有超期行时再清理一次必须安全() {
        sfiRepo.saveAndFlush(sfi(LocalDateTime.now(), "only-fresh"));

        service.scheduledCleanup();
        service.scheduledCleanup();

        assertThat(sfiRepo.findFirstByRunId("only-fresh")).as("两轮清理后未超期行仍在").isPresent();
    }

    private static SfiRecordEntity sfi(LocalDateTime ts, String runId) {
        SfiRecordEntity e = new SfiRecordEntity();
        e.ts = ts;
        e.runId = runId;
        e.regionId = "SHE";
        e.configuredMode = "LIVE";
        e.effectiveSource = "METAR";
        e.source = "live";
        e.scenario = "live";
        e.level = "FIT";
        e.ruleVersion = "rules-v1";
        e.conditionText = "test";
        e.ingestedAt = ts;
        e.evaluatedAt = ts;
        return e;
    }
}
