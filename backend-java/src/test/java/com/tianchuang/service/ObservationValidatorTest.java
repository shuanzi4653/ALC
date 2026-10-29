package com.tianchuang.service;

import static org.assertj.core.api.Assertions.*;

import com.tianchuang.model.WeatherSnapshot;
import org.junit.jupiter.api.Test;

/**
 * 风向边界的判据。**这个类在 0.9.32 之前根本不存在，而缺失本身就是那个缺陷**：
 * `ObservationValidator` 要求 `0–359`，上游 open-meteo 对正北返回 `360`，
 * 于是正北一来整轮定时监测就 FAILED（`INVALID_INPUT`、不落库）→ 数据长期
 * `STALE`、`/api/health/ready` 永远 `NOT_READY`。这个错误的边界从写下那天起
 * 就没有任何判据覆盖，所以它在两个版本里都没被发现 —— 加这个类不只是补一次
 * 回归，是补上那条**一直缺着的对照**。
 *
 * 判据分两半，缺一不可（M29：只证"它能过"的判据没有牙齿）：
 *   · 该收的收 —— 0 / 359 / 360 / null 都必须通过；
 *   · 该拒的拒 —— -1 / 361 必须被拒。
 * 只写前一半天平会朝"什么都放行"漂移，只写后一半会朝"越收越紧"漂移 ——
 * 而上下两处漂移的症状都是"某天的观测忽然进不来"，读起来像上游坏了。
 */
class ObservationValidatorTest {

    private final ObservationValidator validator = new ObservationValidator();

    /** 除风向以外全部合法的最小快照。 */
    private static WeatherSnapshot withWind(Integer windDeg) {
        return new WeatherSnapshot(
                "2026-10-15T19:00:00+08:00", "live",
                43.90, 125.32, "晴",
                8.0, 0.55, 4.0, 12.2,
                windDeg,
                0.0, 20000.0, 1012.0, 0.2, 0.0,
                WeatherSnapshot.TIME_BASIS_OBSERVED);
    }

    private static WeatherSnapshot withTime(String time, String basis) {
        return new WeatherSnapshot(
                time, "live", 43.90, 125.32, "晴",
                8.0, 0.55, 4.0, 12.2, 180,
                0.0, 20000.0, 1012.0, 0.2, 0.0, basis);
    }

    /**
     * `windDeg` 是 `Integer`，所以"非整数风向"构造不出来 —— 这不是漏了一个用例，
     * 是类型上就不存在。写在这里是为了让下一个人不用再想一遍这件事。
     */
    private void assertAccepted(Integer windDeg) {
        try {
            validator.validate(withWind(windDeg));
        } catch (RuntimeException failure) {
            throw new AssertionError("风向 " + windDeg + " 应当被接受，却抛了："
                    + failure.getMessage(), failure);
        }
    }

    private void assertRejected(int windDeg) {
        assertThatThrownBy(() -> validator.validate(withWind(windDeg)))
                .as("风向 %s 应当被拒绝", windDeg)
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("风向");
    }

    @Test
    void dueNorthIsValidAtBothEndsOfTheClosedInterval() {
        // 0 与 360 是同一个方向。上游在两处都会给出它 —— open-meteo 对正北实测
        // 返回 360（2026-10-15 直接问过源站），而 0 是老代码一直放行的那个。
        assertAccepted(0);
        assertAccepted(360);
    }

    @Test
    void theOldUpperBoundIsTheRegressionThisPins() {
        // 360 正是 0.9.32 修掉的那一格。若有人把上界改回 359，这一条当场变红。
        assertAccepted(360);
        assertRejected(361);
    }

    @Test
    void acceptsTheWholeDeclaredRange() {
        assertAccepted(1);
        assertAccepted(90);
        assertAccepted(180);
        assertAccepted(270);
        assertAccepted(359);
    }

    @Test
    void rejectsBearingsOutsideTheRange() {
        assertRejected(-1);
        assertRejected(361);
        assertRejected(720);
    }

    @Test
    void nullWindIsUnknownNotZero() {
        // `null` 是"风向未知"，0 是"正北风"，两者不能互相顶替（本类的类注释
        // 与 WeatherSnapshot 的字段注释都写了这一条）。
        assertAccepted(null);
    }

    @Test
    void nonFiniteValuesAreAlwaysRejected() {
        // 「声称了的值必须站得住」：NaN 不是一个缺席，它是一个说了话的值。
        // 这条同时钉住校验顺序 —— 纬度先于风向，所以报的是纬度。
        assertThatThrownBy(() -> validator.validate(new WeatherSnapshot(
                "2026-10-15T19:00:00+08:00", "live", Double.NaN, 125.32, "晴",
                8.0, 0.55, 4.0, 12.2, 90, 0.0, 20000.0, 1012.0, 0.2, 0.0,
                WeatherSnapshot.TIME_BASIS_OBSERVED)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("纬度");
    }

    /**
     * 观测时刻的两侧判据（2026-10-16）。和风 API v1 的实时响应里没有时间字段
     * （线上取证见 {@code WeatherSnapshot} 的类注释），所以「没有观测时刻」是一个
     * **真实状态**；但「忘填」与「来源不提供」必须能被分开。
     *
     * <p>四条缺一不可，而且**后两条是前两条的对照**：只证"声明了就不报错"，天平会朝
     * "什么都放行"漂移（于是 Python 那条 convertSnapshot 路径上的无时间快照也一起过）；
     * 只证"没时间就报错"，首选源又会退回 0.9.33 之前的「每轮降级」。</p>
     */
    @Test
    void observationTimeIsCheckedFromBothSides() {
        // ① 表态了「来源不提供」+ 时间缺席 → 收
        validator.validate(withTime(null, WeatherSnapshot.TIME_BASIS_NOT_PROVIDED));
        // ② 有来源给的时间 → 收（旧行为，不能被这次放宽碰掉）
        validator.validate(withTime("2026-10-15T19:00:00+08:00", WeatherSnapshot.TIME_BASIS_OBSERVED));
        // ③ 没表态、时间又缺席 → 拒（旧契约原样保留：别的入口绕不进来）
        assertThatThrownBy(() -> validator.validate(withTime(null, WeatherSnapshot.TIME_BASIS_UNSPECIFIED)))
                .as("没有表态的缺席必须仍然被拒")
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("观测时间");
        // ④ 同时声称「不提供」和给了一个时间 → 拒（两条互相矛盾的声明）
        assertThatThrownBy(() -> validator.validate(
                withTime("2026-10-15T19:00:00+08:00", WeatherSnapshot.TIME_BASIS_NOT_PROVIDED)))
                .as("自相矛盾的声明必须被拒，否则下游会挑一条当真")
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("不提供");
    }
}
