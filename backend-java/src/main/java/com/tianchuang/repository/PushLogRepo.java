package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.PushLogEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface PushLogRepo extends JpaRepository<PushLogEntity, Long> {
    boolean existsByAlertIdAndChannelAndTargetAndStatus(Long alertId, String channel, String target, String status);
    List<PushLogEntity> findTop50ByOrderByTsDesc();

    /** 保留策略（E02）：删除早于截止时间的推送日志 */
    long deleteByTsBefore(java.time.LocalDateTime cutoff);
}
