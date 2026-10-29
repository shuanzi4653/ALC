package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/**
 * 每日配额的一格。一行 = (哪一天, 哪个维度, 哪个键)。
 *
 * <p>主键刻意做成<b>拼出来的一个字符串</b>而不是 (day, dimension, key) 三列复合键：
 * 每次计费都要对它做一次「行在不在 → 不在就插 → 插完再条件自增」，
 * 单列主键让这三步都退化成一次 {@code findById} / 一次 {@code UPDATE ... WHERE}，
 * 不需要在 JPQL 里写复合键比较，也不需要 {@code @IdClass}。三列仍然各自留了列，
 * 是为了运维能直接 {@code SELECT day, dimension, sum(used) ... GROUP BY} 看台账。</p>
 *
 * <p><b>为什么落库而不是放内存里数：</b>配额的意义是"一天内总量有上限"。放在
 * 内存里的话，一次重启就把它清零了 —— 于是一条「重启即重置」的旁路就存在了。
 * 它虽然要碰到服务进程（外人碰不到），但那种"判据在单进程内全绿、在真实运维
 * 动作下失效"的缺口，正是这个项目一直在防的形态。落库之后重启不影响配额，
 * 代价是每次大模型调用多一次两行的读写 —— 相对于一次几秒的大模型调用可以忽略。</p>
 */
@Entity
@Table(name = "llm_quota")
public class LlmQuotaEntity {

    /** {@code day|dimension|key} 拼装后的桶键，长度上限 10+1+12+1+64 = 88。 */
    @Id
    @Column(name = "bucket_key", length = 160)
    public String bucketKey;

    /**
     * 本地日 `yyyy-MM-dd`（时区见 {@code quota.zone}）。
     *
     * <p>列名是 {@code quota_day} 而<b>不是</b> {@code day}：H2 把 {@code DAY} 当保留字
     * （INTERVAL 字面量的单位），{@code day VARCHAR(10)} 会在建表时直接报
     * {@code Syntax error ... expected "identifier"}。这条是 2026-10-14 拿真实 H2 跑
     * 迁移脚本才发现的 —— 在那之前，所有 Java 单测（用 Mockito 假仓库）都看不见它，
     * 因为假仓库里没有 SQL。详见 {@code V6__llm_quota.sql} 的抬头注释。</p>
     */
    @Column(name = "quota_day", nullable = false, length = 10)
    public String quotaDay;

    /** {@code workspace} 或 {@code ip}。 */
    @Column(nullable = false, length = 12)
    public String dimension;

    /** 工作区 id 或客户端地址。 */
    @Column(name = "quota_key", nullable = false, length = 64)
    public String quotaKey;

    @Column(nullable = false)
    public int used;

    @Column(name = "created_at", nullable = false)
    public LocalDateTime createdAt = LocalDateTime.now();

    public LlmQuotaEntity() {
    }

    public LlmQuotaEntity(String bucketKey, String quotaDay, String dimension, String quotaKey) {
        this.bucketKey = bucketKey;
        this.quotaDay = quotaDay;
        this.dimension = dimension;
        this.quotaKey = quotaKey;
    }
}
