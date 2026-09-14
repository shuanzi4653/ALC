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

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 历史保留策略（E02）。
 * 按 history.retention-days 回收超期历史；**未发送的 outbox 事件不随历史误删**
 * （只回收已处于终态的投递记录），保证预警不会因清理而丢失。
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

    public HistoryRetentionService(HistoryProperties history, MonitoringRunRepo runRepo,
                                   SfiRecordRepo sfiRepo, TrackResultRepo trackRepo,
                                   AlertRepo alertRepo, PushLogRepo pushLogRepo,
                                   AgentChatRepo chatRepo, OutboxEventRepo outboxRepo) {
        this.history = history;
        this.runRepo = runRepo;
        this.sfiRepo = sfiRepo;
        this.trackRepo = trackRepo;
        this.alertRepo = alertRepo;
        this.pushLogRepo = pushLogRepo;
        this.chatRepo = chatRepo;
        this.outboxRepo = outboxRepo;
    }

    @Scheduled(cron = "${history.cleanup-cron:0 30 3 * * *}")
    public void scheduledCleanup() {
        try {
            Map<String, Object> result = cleanup();
            log.info("历史清理完成：{}", result);
        } catch (Exception e) {
            log.warn("历史清理失败：{}", e.getMessage());
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
