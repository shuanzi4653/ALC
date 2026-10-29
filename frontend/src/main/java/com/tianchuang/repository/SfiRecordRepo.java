package com.tianchuang.repository;

import java.util.List;
import java.util.Optional;

import com.tianchuang.entity.SfiRecordEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface SfiRecordRepo extends JpaRepository<SfiRecordEntity, Long> {
    List<SfiRecordEntity> findTop48ByOrderByTsDesc();
    List<SfiRecordEntity> findTop48ByRegionIdAndEffectiveSourceAndRuleVersionAndScenarioOrderByTsDesc(
            String regionId, String effectiveSource, String ruleVersion, String scenario);

    Optional<SfiRecordEntity> findFirstByOrderByTsDesc();

    Optional<SfiRecordEntity> findFirstByRunId(String runId);

    Optional<SfiRecordEntity> findFirstByRegionIdAndEffectiveSourceAndRuleVersionAndScenarioAndTsBeforeOrderByTsDesc(
            String regionId, String effectiveSource, String ruleVersion, String scenario, java.time.LocalDateTime ts);

    List<SfiRecordEntity> findTop10ByRegionIdAndEffectiveSourceAndRuleVersionAndScenarioOrderByTsDesc(
            String regionId, String effectiveSource, String ruleVersion, String scenario);

    /** 保留策略（E02）：删除早于截止时间的观测记录 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from SfiRecordEntity e where e.ts < :cutoff")
    int deleteByTsBefore(@Param("cutoff") java.time.LocalDateTime cutoff);

    org.springframework.data.domain.Page<SfiRecordEntity> findByRegionIdOrderByTsDesc(
            String regionId, org.springframework.data.domain.Pageable pageable);

    org.springframework.data.domain.Page<SfiRecordEntity> findAllByOrderByTsDesc(
            org.springframework.data.domain.Pageable pageable);
}
