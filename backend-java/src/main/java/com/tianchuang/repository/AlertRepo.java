package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.AlertEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface AlertRepo extends JpaRepository<AlertEntity, Long> {
    List<AlertEntity> findTop20ByOrderByTsDesc();
    List<AlertEntity> findTop20ByRunIdInOrderByTsDesc(List<String> runIds);
    boolean existsByRunId(String runId);

    /** 保留策略（E02）：删除早于截止时间的预警记录 */
    long deleteByTsBefore(java.time.LocalDateTime cutoff);

    org.springframework.data.domain.Page<AlertEntity> findAllByOrderByTsDesc(
            org.springframework.data.domain.Pageable pageable);
}
