package com.tianchuang.repository;

import com.tianchuang.entity.MlInferenceEntity;
import com.tianchuang.service.MlInferenceRecorder;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * V7 的**真库**判据：Flyway 建表 → Hibernate {@code validate} 校验实体映射 → 真读真写。
 *
 * <p>为什么必须有这一条，而不是"迁移脚本跑过了"就够了：
 * {@code tools/maintenance/_verify_migrations.py} 验的是 <b>SQL 能不能执行</b>，
 * 它对"列名对不对得上实体"完全无话可说 —— 一个 {@code @Column(name="agree")}
 * 对着 {@code agreed} 列，SQL 照样建表成功，而第一次查询才炸。
 * 这里用 {@code ddl-auto=validate} 让 Hibernate 在启动时逐列核对，
 * 于是"实体内存模型"与"库结构"之间那道缝在测试阶段就暴露，而不是等部署。</p>
 *
 * <p>用独立的<b>内存</b>库（{@code jdbc:h2:mem:}）而不是 {@code ./data/tianchuang}：
 * 测试若写进真实库，跑一次测试就会在演示数据里留下几行没有来路的留痕，
 * 而那种污染在界面上看起来跟正常记录一模一样。</p>
 */
@DataJpaTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:mlinfer;MODE=MySQL;DB_CLOSE_DELAY=-1",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.jpa.hibernate.ddl-auto=validate",
        "spring.flyway.enabled=true",
        "spring.flyway.locations=classpath:db/migration"
})
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(MlInferenceRecorder.class)
class MlInferencePersistenceTest {

    @Autowired
    MlInferenceRepo repo;

    @Autowired
    MlInferenceRecorder recorder;

    /** 实体逐列与 V7 建出来的表对齐（校验失败会在上下文启动时抛，测试根本进不来）。 */
    @Test
    void 实体字段与迁移建出的表一致() {
        MlInferenceEntity e = new MlInferenceEntity();
        e.level = "CAUTION";
        e.available = true;
        e.confidence = new BigDecimal("0.8123");
        e.margin = new BigDecimal("0.3011");
        e.lowConfidence = false;
        e.degraded = true;
        e.missingCount = 3;
        e.top3 = "[{\"feature\":\"windSpeed\"}]";
        e.ruleLevel = "DANGER";
        e.agree = false;
        e.modelVersion = "ml-v1";
        e.labelsVersion = "v1";
        e.inputsSha256 = "a".repeat(64);
        e.sampleKey = "SHE-2026-07-06T0400";
        e.sessionId = "sess-test";
        e.workspaceId = null;
        e.createdAt = LocalDateTime.now();

        MlInferenceEntity saved = repo.saveAndFlush(e);
        assertThat(saved.id).isNotNull();

        MlInferenceEntity back = repo.findById(saved.id).orElseThrow();
        assertThat(back.level).isEqualTo("CAUTION");
        assertThat(back.degraded).isTrue();
        assertThat(back.missingCount).isEqualTo(3);
        assertThat(back.agree).isFalse();
        assertThat(back.confidence).isEqualByComparingTo(new BigDecimal("0.8123"));
        assertThat(back.top3).contains("windSpeed");
    }

    /** 三态必须真的存成三态：一致 / 不一致 / 不可比（null）。 */
    @Test
    void 一致性三态都能落库且查得回来() {
        for (Boolean flag : new Boolean[]{Boolean.TRUE, Boolean.FALSE, null}) {
            MlInferenceEntity e = new MlInferenceEntity();
            e.level = "FIT";
            e.available = true;
            e.ruleLevel = flag == null ? null : "FIT";
            e.agree = flag;
            e.modelVersion = "ml-v1";
            repo.saveAndFlush(e);
        }
        long total = repo.countByCreatedAtGreaterThanEqual(LocalDateTime.now().minusHours(1));
        assertThat(total).isEqualTo(3);

        var rows = repo.countByAgreeSince(LocalDateTime.now().minusHours(1));
        // 三行三组：true / false / null 各 1。若"不可比"被压进 false，这里只会有两行。
        assertThat(rows).hasSize(3);
        long sum = rows.stream().mapToLong(r -> ((Number) r[1]).longValue()).sum();
        assertThat(sum).isEqualTo(3);
    }

    /** 留痕写入失败不能冒泡 —— 这一条用"写非法值"制造失败，验证调用方仍能继续。 */
    @Test
    void 留痕失败不影响调用方() {
        // level 超长会被截断到 16 而不是抛错（recorder 里主动截断），所以这里用 null 响应体
        // 制造一条"无法留痕"的路径：record 内部应当吞掉并返回。
        recorder.record(Map.of("snapshot", Map.of("windSpeed", 5.0)), null);
        // 没有断言异常 —— 走到这一行就是通过：record 契约是"永不抛出"。
        assertThat(true).isTrue();
    }

    /** 汇总：窗口里没有记录时必须给 empty 标记，而不是给一堆 0 装作"有数据但都是 0"。 */
    @Test
    void 空窗口给出empty而不是全零() {
        Map<String, Object> s = recorder.summary(24);
        assertThat(s.get("available")).isEqualTo(true);
        assertThat(s.get("total")).isEqualTo(0L);
        assertThat(s.get("empty")).isEqualTo(true);
        // 分母为 0 的比例必须是 null，不是 0 —— "没有"与"是 0"在界面上要长得不一样。
        assertThat(s.get("availability")).isNull();
    }
}
