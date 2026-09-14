package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.TrackResultEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface TrackResultRepo extends JpaRepository<TrackResultEntity, Long> {
    List<TrackResultEntity> findTop48ByOrderByTsDesc();
    List<TrackResultEntity> findTop48ByRunIdInOrderByTsDesc(List<String> runIds);
    java.util.Optional<TrackResultEntity> findFirstByRunIdOrderByRevisionDesc(String runId);

    /** 保留策略（E02）：删除早于截止时间的推演记录 */
    long deleteByTsBefore(java.time.LocalDateTime cutoff);
}
