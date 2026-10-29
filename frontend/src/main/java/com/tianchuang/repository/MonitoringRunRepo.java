package com.tianchuang.repository;

import com.tianchuang.entity.MonitoringRunEntity;
import java.time.LocalDateTime;
import java.util.Optional;
import java.util.Collection;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface MonitoringRunRepo extends JpaRepository<MonitoringRunEntity, Long> {
    Optional<MonitoringRunEntity> findFirstByStatusOrderByIdDesc(String status);
    Optional<MonitoringRunEntity> findFirstByStatusInOrderByIdDesc(Collection<String> statuses);
    Optional<MonitoringRunEntity> findFirstByOrderByIdDesc();
    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeAndStatusInOrderByIdDesc(String regionId, String configuredMode, Collection<String> statuses);
    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeOrderByIdDesc(String regionId, String configuredMode);

    // ---------------- 按运行口径取数（匿名工作区，2026-10-14） ----------------
    // 采集本身是全机一次（对同一个世界的测量），但**看哪一轮**是每个人的选择：A 切到
    // clear 之后，B 的屏幕不该跟着换一套预报。所以大屏的取数按调用方自己的工作区口径
    // 过滤，而不是取"最新一轮"（那正是 A 的选择泄漏到 B 屏幕上的路径）。

    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeAndScenarioAndStatusInOrderByIdDesc(
            String regionId, String configuredMode, String scenario, Collection<String> statuses);

    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeAndScenarioOrderByIdDesc(
            String regionId, String configuredMode, String scenario);

    Optional<MonitoringRunEntity> findByRunId(String runId);

    // ---------------- 历史分页（E02） ----------------
    // 按 id 倒序等价于运行先后；配合 Pageable 限制单页大小，避免一次拉全表。

    Page<MonitoringRunEntity> findAllByOrderByIdDesc(Pageable pageable);

    Page<MonitoringRunEntity> findByRegionIdOrderByIdDesc(String regionId, Pageable pageable);

    Page<MonitoringRunEntity> findByStartedAtAfterOrderByIdDesc(LocalDateTime since, Pageable pageable);

    Page<MonitoringRunEntity> findByRegionIdAndStartedAtAfterOrderByIdDesc(
            String regionId, LocalDateTime since, Pageable pageable);

    /** 保留策略：删除早于截止时间的运行记录 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from MonitoringRunEntity e where e.startedAt < :cutoff")
    int deleteByStartedAtBefore(@Param("cutoff") LocalDateTime cutoff);
}
