package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.PushLogEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface PushLogRepo extends JpaRepository<PushLogEntity, Long> {
    boolean existsByAlertIdAndChannelAndTargetAndStatus(Long alertId, String channel, String target, String status);
    List<PushLogEntity> findTop50ByOrderByTsDesc();

    /** 保留策略（E02）：删除早于截止时间的推送日志 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from PushLogEntity e where e.ts < :cutoff")
    int deleteByTsBefore(@Param("cutoff") java.time.LocalDateTime cutoff);
}
