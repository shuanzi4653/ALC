package com.tianchuang.repository;

import com.tianchuang.entity.MlInferenceEntity;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface MlInferenceRepo extends JpaRepository<MlInferenceEntity, Long> {

    /** 最近的若干条留痕（成效页与研判卡都按时间倒序读）。 */
    List<MlInferenceEntity> findByCreatedAtGreaterThanEqualOrderByCreatedAtDesc(LocalDateTime since);

    /**
     * 按档位计数：{@code [level, count]}。
     *
     * <p>用聚合查询而不是把最近的记录全捞出来在内存里数 —— 后者在表长起来之后
     * 会先把整个会话读进堆再丢掉 99%，而这正是"演示时好好的、跑一周后开始卡"的形状。</p>
     */
    @Query("select m.level, count(m) from MlInferenceEntity m where m.createdAt >= :since group by m.level")
    List<Object[]> countByLevelSince(@Param("since") LocalDateTime since);

    /**
     * 一致性三态计数：{@code [agree, count]}，其中 {@code agree} 可能是 {@code null}。
     *
     * <p>刻意<b>不</b>用 {@code count(*) where agree = true} 两次查询：那样"不可比"那一档
     * 永远不会出现在结果里，而界面上少一档的表现就是"一致 + 不一致 = 总数"永远差几个数，
     * 差的那部分谁也说不清去哪了。</p>
     */
    @Query("select m.agree, count(m) from MlInferenceEntity m where m.createdAt >= :since group by m.agree")
    List<Object[]> countByAgreeSince(@Param("since") LocalDateTime since);

    /** 最近若干条的分歧样本（研判卡「规则否决」那张小表用）。 */
    @Query("select m from MlInferenceEntity m where m.agree = false order by m.createdAt desc")
    List<MlInferenceEntity> recentDisagreements(Pageable page);

    /** 模型档位分布的分母：指定时间窗内的总条数。 */
    long countByCreatedAtGreaterThanEqual(LocalDateTime since);

    /** 指定时间窗内模型真正参与了的有几条（可用率 = 它 / 总数）。 */
    long countByAvailableTrueAndCreatedAtGreaterThanEqual(LocalDateTime since);
}
