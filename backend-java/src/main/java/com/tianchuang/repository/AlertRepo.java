package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.AlertEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AlertRepo extends JpaRepository<AlertEntity, Long> {
    List<AlertEntity> findTop20ByOrderByTsDesc();
    List<AlertEntity> findTop20ByRunIdInOrderByTsDesc(List<String> runIds);
    boolean existsByRunId(String runId);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from AlertEntity e where e.ts < :cutoff")
    int deleteByTsBefore(@Param("cutoff") java.time.LocalDateTime cutoff);

    org.springframework.data.domain.Page<AlertEntity> findAllByOrderByTsDesc(
            org.springframework.data.domain.Pageable pageable);
}
