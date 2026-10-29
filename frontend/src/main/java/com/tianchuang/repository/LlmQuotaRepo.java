package com.tianchuang.repository;

import com.tianchuang.entity.LlmQuotaEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

public interface LlmQuotaRepo extends JpaRepository<LlmQuotaEntity, String> {

    /**
     * 「在没到上限的前提下自增一格」，返回是否真的加上了（1 = 加上，0 = 已满）。
     *
     * <p>把判断并进 {@code WHERE} 而不是先读后写：先读后写在并发下会让两个请求
     * 都读到 {@code limit-1} 然后都放行，于是上限在并发下静默失效 —— 而单线程测试
     * 永远看不见它。数据库这一条 UPDATE 是原子的，条件与自增在同一次行锁里完成。</p>
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("update LlmQuotaEntity q set q.used = q.used + 1 where q.bucketKey = :key and q.used < :limit")
    int incrementWithinLimit(@Param("key") String key, @Param("limit") int limit);

    /**
     * 回退一格。用在「工作区那格已加、IP 那格才判满」的路径上：
     * 被 IP 挡下来的请求不该算在这个工作区头上 —— 否则同一个 NAT 里别人把 IP 用满时，
     * 会连带把这个工作区自己的额度也一起扣掉（看起来像"我没怎么用怎么就没了"）。
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Transactional
    @Query("update LlmQuotaEntity q set q.used = q.used - 1 where q.bucketKey = :key and q.used > 0")
    int decrement(@Param("key") String key);

    /** 清理保留期之外的日子。`yyyy-MM-dd` 的字典序等于时间序，所以可以直接比。 */
    @Modifying
    @Transactional
    @Query("delete from LlmQuotaEntity q where q.quotaDay < :cutoff")
    int deleteByDayLessThan(@Param("cutoff") String cutoff);
}
