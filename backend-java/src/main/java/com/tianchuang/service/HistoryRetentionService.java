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

@Service
public class HistoryRetentionService {

    private static final Logger log = LoggerFactory.getLogger(HistoryRetentionService.class);

    private static final List<String> OUTBOX_TERMINAL = List.of("SENT", "FAILED", "DEAD", "SKIPPED");

    private final HistoryProperties history;
    private final MonitoringRunRepo runRepo;
    private final SfiRecordRepo sfiRepo;
    private final TrackResultRepo trackRepo;
    private final AlertRepo alertRepo;
    private final PushLogRepo pushLogRepo;
    private final AgentChatRepo chatRepo;
    private final OutboxEventRepo outboxRepo;
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
            Map<String, Object> result = self.getObject().cleanup();
            log.info("历史清理完成：{}", result);
        } catch (Exception e) {
            log.error("历史清理失败（本轮一行未删，历史会继续累积）", e);
        }
    }

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
        deleted.put("outboxTerminal", outboxRepo.deleteByStatusInAndCreatedAtBefore(OUTBOX_TERMINAL, cutoff));
        return deleted;
    }

    public int retentionDays() {
        return history.retentionDays();
    }
}
