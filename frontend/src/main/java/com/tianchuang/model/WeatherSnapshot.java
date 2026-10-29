package com.tianchuang.model;

/**
 * 标准化实时观测快照（内部统一格式，和风数据与模拟数据均转换为此结构）
 *
 * <p>{@code timeBasis} 是 2026-10-16 新增的一维，来源是一次「问对象自己」的线上取证：
 * 和风 API v1 的 {@code /weather/v1/current/{lat}/{lon}} <b>整份响应里没有任何时间字段</b> ——
 * 顶层键实测只有 {@code metadata / condition / temperature / feelsLike / humidity / wind /
 * windGust / precipitation / pressure / visibility / dewPoint / cloudCover / uvIndex}，
 * 而 {@code metadata} 只有 {@code tag} 与 {@code attributions}。旧代码把
 * {@code metadata.obsTime} 列为<b>必需字段</b>，于是首选源每一次都抛「和风字段缺失」、
 * 静默降级到公共源并标 {@code degraded:true} —— 首选源从未真正生效。</p>
 *
 * <p>修法不是「缺了就补一个本机时刻」：那会把「无法判断这条读数有多新」变成
 * 「它刚刚观测过」，而 {@code MonitorService.freshness()} 正是拿这个时间算年龄的。
 * 所以缺席被做成一个<b>说出口的状态</b>（{@link #TIME_BASIS_NOT_PROVIDED}），
 * 由 {@code ObservationValidator} 两侧同时把关：声明了「来源不提供观测时刻」就不许
 * 同时给出观测时间，反之亦然。</p>
 */
public record WeatherSnapshot(
        String time,           // ISO-8601 观测时间；来源不提供时为 null
        String source,         // live | sim
        Double lat,
        Double lon,
        String conditionText,
        Double tempC,
        Double humidity,       // 0-1
        Double windSpeed,      // m/s 平均风速
        Double windGust,       // m/s 阵风
        Integer windDeg,       // 风向角度；null 表示未知，0 是有效北风
        Double precipMmh,      // 降水强度 mm/h
        Double visibilityM,    // 能见度（米）
        Double pressureHpa,    // 海平面气压
        Double cloudCover,     // 云量 0-1
        Double thunderProb,    // 雷暴概率 0-1
        String timeBasis) {    // time 的来源，见下方三个常量；null 视同 UNSPECIFIED

    /**
     * {@code time} 是**来源自己声明**的时刻（观测时刻，或预报序列里那条预报的有效时刻）。
     * 和风、公共源、以及由预报点构造的合成快照都会走到这一支。
     */
    public static final String TIME_BASIS_OBSERVED = "OBSERVED";

    /**
     * 来源**不提供**观测时刻（和风 v1 的实测形状）。此时 {@code time} 必须为 {@code null}
     * —— 补一个本机时刻会让新鲜度判据失去对象。
     */
    public static final String TIME_BASIS_NOT_PROVIDED = "NOT_PROVIDED_BY_PROVIDER";

    /**
     * 既没声明观测时刻、也没声明「不提供」：构造方没有表态。这一支**保持旧契约**
     * （{@code time} 为空即拒绝），所以「放宽」只对<b>明确表态</b>的那一种情形生效 ——
     * 一个挂在单一入口上的守卫，从别的入口绕过去时会静默失效（M87）。
     */
    public static final String TIME_BASIS_UNSPECIFIED = "UNSPECIFIED";
}
