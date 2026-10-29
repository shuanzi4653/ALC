package com.tianchuang.repository;

import com.tianchuang.entity.LlmQuotaEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

public interface LlmQuotaRepo extends JpaRepository<LlmQuotaEntity, String> {

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("update LlmQuotaEntity q set q.used = q.used + 1 where q.bucketKey = :key and q.used < :limit")
    int incrementWithinLimit(@Param("key") String key, @Param("limit") int limit);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("update LlmQuotaEntity q set q.used = q.used - 1 where q.bucketKey = :key and q.used > 0")
    int decrement(@Param("key") String key);

    @Modifying
    @Transactional
    @Query("delete from LlmQuotaEntity q where q.quotaDay < :cutoff")
    int deleteByDayLessThan(@Param("cutoff") String cutoff);
}
