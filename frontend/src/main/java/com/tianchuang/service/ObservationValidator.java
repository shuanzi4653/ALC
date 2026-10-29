package com.tianchuang.service;

import com.tianchuang.model.WeatherSnapshot;
import org.springframework.stereotype.Component;

/**
 * 在规则计算前拒绝非有限值及明显错误的单位/范围。
 *
 * <p>本类只负责**结构完整性**与**值合法性**：位置、时间、以及「一旦给出就必须在物理上站得住」。
 * 它**不**判断哪个要素是「本轮必需」——那由规则配置的 {@code required} 决定，
 * 并由 {@link SfiEngine} 在计分前统一执行。两处各管一件事，避免同一条判据有两个来源。
 *
 * <p>注意 {@code windDeg} 显式为可选：{@code null} 即「风向未知」，而 {@code 0} 是有效的北风，
 * 不能用真假值判断。
 */
@Component
public class ObservationValidator {

    public void validate(WeatherSnapshot s) {
        if (s == null) throw new IllegalArgumentException("气象快照不能为空");
        bounded("纬度", s.lat(), -90, 90);
        bounded("经度", s.lon(), -180, 180);
        bounded("温度", s.tempC(), -100, 70);
        bounded("湿度", s.humidity(), 0, 1);
        bounded("平均风速", s.windSpeed(), 0, 150);
        bounded("阵风", s.windGust(), 0, 200);
        bounded("降水强度", s.precipMmh(), 0, 500);
        bounded("能见度", s.visibilityM(), 0, 100_000);
        bounded("气压", s.pressureHpa(), 800, 1_100);
        bounded("云量", s.cloudCover(), 0, 1);
        bounded("雷暴概率", s.thunderProb(), 0, 1);
        // 风向是**闭区间** [0, 360]：气象口径里 0 与 360 是同一个方向（正北）。
        // 原判据写的是 `> 359`，等于把"正北"整条射掉，而这不是理论情形 ——
        // 上游 open-meteo 对正北返回的就是 360。2026-10-15 在服务器上直接问过源站
        // （站点 43.90/125.32，Asia/Shanghai）：
        //     "current":{"time":"2026-10-15T19:00","interval":900,
        //                "wind_direction_10m":360,"wind_speed_10m":4.0,...}
        // 后果不是"某条记录被跳过"，而是**整轮定时监测 FAILED** —— MonitorService 记
        // 一条 `INVALID_INPUT`、不落库，于是数据长期 STALE、`/api/health/ready`
        // 永远是 NOT_READY。而日志里只有一句"风向必须在 0–359 度之间"，
        // 读起来像上游给了脏数据，于是排查方向全错（同 M19：错误信息把人引偏，
        // 比没有错误信息更贵）。
        //
        // 这里只放宽**合法性域**，不做归一化（不把 360 改写成 0）：本类的职责是
        // 判"这个值站不站得住"，不是改写调用方的数据。而且下游是**原样透传**
        // （MonitorService:416 → SfiRecordEntity.windDeg → MonitorService:602 回吐），
        // Java 与 Python 侧都不拿它做算术或扇区判断，两种写法因此等价 ——
        // 那就选不伪造来源的那一种。
        if (s.windDeg() != null && (s.windDeg() < 0 || s.windDeg() > 360)) {
            throw new IllegalArgumentException("风向必须在 0–360 度之间");
        }
        // 观测时间这一维**两侧都判**（2026-10-16 起）。
        //
        // 背景：和风 API v1 的实时响应里没有时间字段（线上取证见 WeatherSnapshot 的类注释），
        // 于是「没有观测时刻」是一种**真实且常态**的状态，不能再与「构造方忘了填」共用同一条
        // 判据。但也不能把这条检查删掉：删掉之后，从别的入口（例如 Python 公共源那条
        // `convertSnapshot`）构造出来的无时间快照会一起被放行，而那种缺席是**没有表态的**，
        // 两者在屏幕上长得一样、在日志里也长得一样（M87）。
        //
        // 所以放宽只对**明确表态**的那一种生效，并且反向也判：声明了「来源不提供观测时刻」
        // 就不许同时给出观测时间 —— 否则一次代码改动就能让两条互相矛盾的声明同时成立，
        // 而下游 freshness() 会挑其中一条当真。
        boolean declaresNoObservationTime = WeatherSnapshot.TIME_BASIS_NOT_PROVIDED.equals(s.timeBasis());
        boolean hasTime = s.time() != null && !s.time().isBlank();
        if (declaresNoObservationTime && hasTime) {
            throw new IllegalArgumentException(
                    "声明了「来源不提供观测时刻」，却同时给出了观测时间：" + s.time());
        }
        if (!declaresNoObservationTime && !hasTime) {
            throw new IllegalArgumentException("观测时间不能为空");
        }
    }

    /**
     * 值一旦存在就必须有限且落在范围内；{@code null} 在此不判——缺席的处置权归规则层
     * （{@code required} 要素缺席由 {@link SfiEngine} 拒绝，可选要素缺席则弃权）。
     * 但 {@code NaN}/{@code Inf} 永远非法：那是一个声称了的、站不住脚的值。
     */
    private void bounded(String name, Double value, double min, double max) {
        if (value == null) return;
        if (!Double.isFinite(value)) {
            throw new IllegalArgumentException(name + "不是有限数值");
        }
        if (value < min || value > max) {
            throw new IllegalArgumentException(name + "超出有效范围");
        }
    }
}
