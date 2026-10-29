package com.tianchuang.repository;

import com.tianchuang.entity.MlInferenceEntity;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface MlInferenceRepo extends JpaRepository<MlInferenceEntity, Long> {

    List<MlInferenceEntity> findByCreatedAtGreaterThanEqualOrderByCreatedAtDesc(LocalDateTime since);

    @Query("select m.level, count(m) from MlInferenceEntity m where m.createdAt >= :since group by m.level")
    List<Object[]> countByLevelSince(@Param("since") LocalDateTime since);

    @Query("select m.agree, count(m) from MlInferenceEntity m where m.createdAt >= :since group by m.agree")
    List<Object[]> countByAgreeSince(@Param("since") LocalDateTime since);

    @Query("select m from MlInferenceEntity m where m.agree = false order by m.createdAt desc")
    List<MlInferenceEntity> recentDisagreements(Pageable page);

    long countByCreatedAtGreaterThanEqual(LocalDateTime since);

    long countByAvailableTrueAndCreatedAtGreaterThanEqual(LocalDateTime since);
}
