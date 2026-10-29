package com.tianchuang.service;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.tianchuang.config.HistoryProperties;
import com.tianchuang.repository.AgentChatRepo;
import com.tianchuang.repository.AlertRepo;
import com.tianchuang.repository.MonitoringRunRepo;
import com.tianchuang.repository.OutboxEventRepo;
import com.tianchuang.repository.PushLogRepo;
import com.tianchuang.repository.SfiRecordRepo;
import com.tianchuang.repository.TrackResultRepo;

import org.springframework.beans.factory.ObjectProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 历史保留策略（E02）。
 * 按 history.retention-days 回收超期历史；**未发送的 outbox 事件不随历史误删**
 * （只回收已处于终态的投递记录），保证预警不会因清理而丢失。
 *
 * <h2>2026-10-24：这个任务连续 7 天每天失败，七张表一行都没删</h2>
 * 生产日志（10-18 至 10-24）每天 3:30 都是同一句：
 * <pre>
 * 历史清理失败：Null return value from advice does not match primitive return type for:
 * public abstract long com.tianchuang.repository.SfiRecordRepo.deleteByTsBefore(LocalDateTime)
 * </pre>
 * 两个原因叠在一起，缺一个都不会出事：
 * <ol>
 *   <li><b>调用方是同类内部自调用。</b> {@code scheduledCleanup()} 直接调 {@code cleanup()}，
 *       不走 Spring 代理 ⇒ 方法上的 {@code @Transactional} <b>完全不生效</b>。</li>
 *   <li><b>被调的是 Spring Data 派生 delete。</b> 派生 {@code deleteByXxx} 分两步执行：
 *       先 {@code select} 全部命中行加载进持久化上下文，再逐条 {@code em.remove()}。
 *       在无事务上下文里第二步不生效、方法返回 {@code null}，而接口声明是原始类型
 *       {@code long} ⇒ AOP 抛「Null return value does not match primitive」。
 *       实测日志里只出现 {@code select ... where ts<?}、<b>没有任何 delete 语句</b>。</li>
 * </ol>
 * 两个都修了：仓库侧改成 {@code @Modifying @Query} 的 bulk delete（不加载实体 ⇒
 * 内存 O(1)，返回 {@code int} 行数）；这里改成经 {@link ObjectProvider} 取自身代理后
 * 再调 {@code cleanup()}，让事务真的生效（{@code @Modifying} 必须在事务里执行）。
 *
 * <p>判据：{@code HistoryRetentionTest}（真 H2 + {@code NOT_SUPPORTED} 事务，与生产同构）。
 * 没有它的时候全量单测一直绿 —— 因为它们用 Mockito 假仓库，
 * {@code deleteByTsBefore} 永远返回你想看到的数字，这个失败在结构上不在它们射程里。</p>
 */
@Service
public class HistoryRetentionService {

    private static final Logger log = LoggerFactory.getLogger(HistoryRetentionService.class);

    /** 已收敛的投递状态，可安全回收 */
    private static final List<String> OUTBOX_TERMINAL = List.of("SENT", "FAILED", "DEAD", "SKIPPED");

    private final HistoryProperties history;
    private final MonitoringRunRepo runRepo;
    private final SfiRecordRepo sfiRepo;
    private final TrackResultRepo trackRepo;
    private final AlertRepo alertRepo;
    private final PushLogRepo pushLogRepo;
    private final AgentChatRepo chatRepo;
    private final OutboxEventRepo outboxRepo;
    /**
     * 自身代理。用它而不是 {@code this}：{@code @Transactional} 只对经代理的调用生效，
     * 而定时任务必须从本类内部发起 —— 直接 {@code cleanup()} 等于把注解写在注释里。
     */
    private final ObjectProvider<HistoryRetentionService> self;

    public HistoryRetentionService(HistoryProperties history, MonitoringRunRepo runRepo,
                                   SfiRecordRepo sfiRepo, TrackResultRepo trackRepo,
                                   AlertRepo alertRepo, PushLogRepo pushLogRepo,
                                   AgentChatRepo chatRepo, OutboxEventRepo outboxRepo,
                                   ObjectProvider<HistoryRetentionService> self) {
        this.history = history;
        this.runRepo = runRepo;
        this.sfiRepo = sfiRepo;
        this.trackRepo = trackRepo;
        this.alertRepo = alertRepo;
        this.pushLogRepo = pushLogRepo;
        this.chatRepo = chatRepo;
        this.outboxRepo = outboxRepo;
        this.self = self;
    }

    @Scheduled(cron = "${history.cleanup-cron:0 30 3 * * *}")
    public void scheduledCleanup() {
        try {
            // 经代理调用，让 cleanup() 上的 @Transactional 真正生效。
            Map<String, Object> result = self.getObject().cleanup();
            log.info("历史清理完成：{}", result);
        } catch (Exception e) {
            // 这里必须带异常栈：2026-09 那次就是只留下一句 message，
            // 于是「原始类型返回告警」被当成无害噪音，问题活了一个多月。
            log.error("历史清理失败（本轮一行未删，历史会继续累积）", e);
        }
    }

    /** 执行一次清理，返回各表删除条数（便于人工核对与测试断言）。 */
    @Transactional
    public Map<String, Object> cleanup() {
        LocalDateTime cutoff = LocalDateTime.now().minusDays(history.retentionDays());

        Map<String, Object> deleted = new LinkedHashMap<>();
        deleted.put("cutoff", cutoff.toString());
        deleted.put("retentionDays", history.retentionDays());
        deleted.put("sfiRecord", sfiRepo.deleteByTsBefore(cutoff));
        deleted.put("trackResult", trackRepo.deleteByTsBefore(cutoff));
        deleted.put("alert", alertRepo.deleteByTsBefore(cutoff));
        deleted.put("pushLog", pushLogRepo.deleteByTsBefore(cutoff));
        deleted.put("agentChat", chatRepo.deleteByTsBefore(cutoff));
        deleted.put("monitoringRun", runRepo.deleteByStartedAtBefore(cutoff));
        // outbox：仅回收已终态记录，未发送的保留
        deleted.put("outboxTerminal", outboxRepo.deleteByStatusInAndCreatedAtBefore(OUTBOX_TERMINAL, cutoff));
        return deleted;
    }

    /** 保留天数（供健康/运维展示） */
    public int retentionDays() {
        return history.retentionDays();
    }
}
