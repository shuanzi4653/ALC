package com.tianchuang.repository;

import com.tianchuang.entity.MonitoringRunEntity;
import java.time.LocalDateTime;
import java.util.Optional;
import java.util.Collection;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MonitoringRunRepo extends JpaRepository<MonitoringRunEntity, Long> {
    Optional<MonitoringRunEntity> findFirstByStatusOrderByIdDesc(String status);
    Optional<MonitoringRunEntity> findFirstByStatusInOrderByIdDesc(Collection<String> statuses);
    Optional<MonitoringRunEntity> findFirstByOrderByIdDesc();
    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeAndStatusInOrderByIdDesc(String regionId, String configuredMode, Collection<String> statuses);
    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeOrderByIdDesc(String regionId, String configuredMode);
    Optional<MonitoringRunEntity> findByRunId(String runId);

    // ---------------- 历史分页（E02） ----------------
    // 按 id 倒序等价于运行先后；配合 Pageable 限制单页大小，避免一次拉全表。

    Page<MonitoringRunEntity> findAllByOrderByIdDesc(Pageable pageable);

    Page<MonitoringRunEntity> findByRegionIdOrderByIdDesc(String regionId, Pageable pageable);

    Page<MonitoringRunEntity> findByStartedAtAfterOrderByIdDesc(LocalDateTime since, Pageable pageable);

    Page<MonitoringRunEntity> findByRegionIdAndStartedAtAfterOrderByIdDesc(
            String regionId, LocalDateTime since, Pageable pageable);

    /** 保留策略：删除早于截止时间的运行记录 */
    long deleteByStartedAtBefore(LocalDateTime cutoff);
}
