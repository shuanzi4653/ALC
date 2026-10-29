package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 一次轨1 模型推理的留痕。一行 = 一次 {@code POST /track1/ml}。
 *
 * <p><b>为什么这张表存在：</b>0.10.1 之前 {@code /track1/ml} 是 stub，所以"模型表现如何"
 * 从来没有过一次可查的答案。接上真模型之后如果没有留痕，"模型和规则吵过几次架"就只存在
 * 于日志里，而日志会轮转 —— 成效页那张三列表格最后会变成手写数字。</p>
 *
 * <p><b>不存原始气象快照</b>：快照由 {@code (城市, 时间, 数据源)} 唯一确定，
 * {@code inputsSha256} 足够定位争议；把外部数据抄进自家库只会让"为什么我们的库里
 * 有一份别人家的气象数据"变成新问题。同理不放凭据。</p>
 *
 * <p><b>不可变</b>：本表语义是历史记录。纠正一条错误记录的正确做法是再写一行让它成为最新，
 * 而不是 UPDATE 旧行 —— 否则"当时模型说了什么"就永久丢失，而那个问题恰恰是本表要回答的。</p>
 */
@Entity
@Table(name = "ml_inference")
public class MlInferenceEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    /** 同一次运行台的轮次（{@code /traffic/session} 的 sessionId）。空 = 独立试算，不是缺失。 */
    @Column(name = "session_id", length = 80)
    public String sessionId;

    /** {@code <城市>-<YYYY-MM-DDTHHMM>}，与训练样本同一套命名，便于线上样本直接回查训练集。 */
    @Column(name = "sample_key", length = 64)
    public String sampleKey;

    /** 匿名工作区。空值 = <b>未标识</b>，不等于"默认工作区"。 */
    @Column(name = "workspace_id", length = 64)
    public String workspaceId;

    /**
     * 这一轮模型到底参与了没有。
     *
     * <p>单独一列而不用 {@code level='UNAVAILABLE'} 凑：那样会让档位分布里多出一个
     * 不存在的档，统计端就得靠一句隐性约定把它过滤掉 —— 而隐性约定会在下一个人
     * 改统计时失效，表现是"四档占比加起来不到 100%"，看不出是谁吃了。</p>
     */
    @Column(nullable = false)
    public boolean available = true;

    /** 不可用原因。{@code available=true} 时必须为空。 */
    @Column(length = 48)
    public String reason;

    @Column(nullable = false, length = 16)
    public String level;

    @Column(precision = 5, scale = 4)
    public BigDecimal confidence;

    /**
     * top1 − top2 的概率差。
     *
     * <p>单独立一列是因为"置信度 0.45、次高 0.44"和"置信度 0.45、次高 0.05"在界面上
     * 必须长得不一样，而只存 confidence 永远分不出这两种。</p>
     */
    @Column(precision = 5, scale = 4)
    public BigDecimal margin;

    @Column(name = "low_confidence", nullable = false)
    public boolean lowConfidence;

    /** 关键要素缺测 ≥3 个：档位建立在训练中位数填充上，不是看过天气给的。 */
    @Column(nullable = false)
    public boolean degraded;

    @Column(name = "missing_count", nullable = false)
    public int missingCount;

    /** top3 近似归因（JSON 数组）。字段名刻意不叫 {@code shap} —— 它不是 SHAP。 */
    @Column(columnDefinition = "CLOB")
    public String top3;

    /** 同轮规则档位。空 = 该轮没有规则结果（不可比）。 */
    @Column(name = "rule_level", length = 16)
    public String ruleLevel;

    /**
     * 模型档位与规则档位是否一致。<b>必须可空</b>。
     *
     * <p>把"不可比"写成 {@code false} 会被统计成"吵了一架" —— 于是成效页的一致率
     * 会因为"模型没参与的那几轮"而被拉低，看起来像模型变差了。三态（一致/不一致/不可比）
     * 在数据库里就是三态，不要压成两态。</p>
     */
    public Boolean agree;

    @Column(name = "model_version", nullable = false, length = 32)
    public String modelVersion;

    @Column(name = "labels_version", length = 32)
    public String labelsVersion;

    @Column(name = "inputs_sha256", length = 64)
    public String inputsSha256;

    @Column(name = "created_at", nullable = false)
    public LocalDateTime createdAt = LocalDateTime.now();

    public MlInferenceEntity() {
    }
}
