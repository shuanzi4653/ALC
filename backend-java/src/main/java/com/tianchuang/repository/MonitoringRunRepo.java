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

    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeAndScenarioAndStatusInOrderByIdDesc(
            String regionId, String configuredMode, String scenario, Collection<String> statuses);

    Optional<MonitoringRunEntity> findFirstByRegionIdAndConfiguredModeAndScenarioOrderByIdDesc(
            String regionId, String configuredMode, String scenario);

    Optional<MonitoringRunEntity> findByRunId(String runId);

    Page<MonitoringRunEntity> findAllByOrderByIdDesc(Pageable pageable);

    Page<MonitoringRunEntity> findByRegionIdOrderByIdDesc(String regionId, Pageable pageable);

    Page<MonitoringRunEntity> findByStartedAtAfterOrderByIdDesc(LocalDateTime since, Pageable pageable);

    Page<MonitoringRunEntity> findByRegionIdAndStartedAtAfterOrderByIdDesc(
            String regionId, LocalDateTime since, Pageable pageable);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from MonitoringRunEntity e where e.startedAt < :cutoff")
    int deleteByStartedAtBefore(@Param("cutoff") LocalDateTime cutoff);
}
