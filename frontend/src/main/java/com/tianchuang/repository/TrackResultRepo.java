package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.TrackResultEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface TrackResultRepo extends JpaRepository<TrackResultEntity, Long> {
    List<TrackResultEntity> findTop48ByOrderByTsDesc();
    List<TrackResultEntity> findTop48ByRunIdInOrderByTsDesc(List<String> runIds);
    java.util.Optional<TrackResultEntity> findFirstByRunIdOrderByRevisionDesc(String runId);

    /** 保留策略（E02）：删除早于截止时间的推演记录 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from TrackResultEntity e where e.ts < :cutoff")
    int deleteByTsBefore(@Param("cutoff") java.time.LocalDateTime cutoff);
}
