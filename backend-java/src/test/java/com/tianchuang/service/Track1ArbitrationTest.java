package com.tianchuang.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.tianchuang.model.FlightLevel;
import org.junit.jupiter.api.Test;

/**
 * 轨1 内部裁决（规则 × 模型）的四支与两条不可越过的线。
 *
 * <p>这组用例真正在守的是<b>不对称</b>：模型更保守可以升档，模型更乐观不许降档。
 * 若哪天有人把它改成"按置信度加权"（看起来更科学），下面
 * {@code 模型更乐观时规则否决} 这一条会立刻变红 —— 它就是为此留的。</p>
 */
class Track1ArbitrationTest {
    private final FusionService fusion = new FusionService();

    @Test
    void 同档时记为一致() {
        var r = fusion.arbitrateTrack1(FlightLevel.CAUTION, FlightLevel.CAUTION, 0.81);
        assertThat(r.level()).isEqualTo(FlightLevel.CAUTION);
        assertThat(r.decision()).isEqualTo(FusionService.Track1Arbitration.CONSISTENT);
        assertThat(r.confidence()).isEqualTo(0.81);
    }

    @Test
    void 模型更保守时采纳模型() {
        var r = fusion.arbitrateTrack1(FlightLevel.CAUTION, FlightLevel.BAN, 0.93);
        assertThat(r.level()).isEqualTo(FlightLevel.BAN);
        assertThat(r.decision()).isEqualTo(FusionService.Track1Arbitration.MODEL_STICTER);
    }

    /** 这条是本轮的硬红线：模型说 FIT，规则说 BAN ⇒ 仍然是 BAN。 */
    @Test
    void 模型更乐观时规则否决() {
        var r = fusion.arbitrateTrack1(FlightLevel.BAN, FlightLevel.FIT, 0.99);
        assertThat(r.level()).isEqualTo(FlightLevel.BAN);
        assertThat(r.decision()).isEqualTo(FusionService.Track1Arbitration.RULE_OVERRIDES_MODEL);
        // 置信度很高也不能翻案 —— 这是"不改档"，不是"按置信度权衡"。
        assertThat(r.confidence()).isEqualTo(0.99);
    }

    @Test
    void 模型不可用时不编造档位也不编造置信度() {
        var r = fusion.arbitrateTrack1(FlightLevel.DANGER, null, null);
        assertThat(r.level()).isEqualTo(FlightLevel.DANGER);
        assertThat(r.decision()).isEqualTo(FusionService.Track1Arbitration.MODEL_UNAVAILABLE);
        // null 而不是 0：界面上"置信度 0%"与"没有模型"必须是两句话。
        assertThat(r.confidence()).isNull();
        assertThat(r.decisionLabel()).isEqualTo("模型未参与");
    }

    @Test
    void 没有规则档位时拒绝裁决() {
        assertThatThrownBy(() -> fusion.arbitrateTrack1(null, FlightLevel.FIT, 0.9))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("规则档位");
    }

    /** 跨两档的乐观分歧（BAN → CAUTION）同样不许降，防止"只防一档"的实现蒙混过关。 */
    @Test
    void 乐观分歧跨两档也不降档() {
        var r = fusion.arbitrateTrack1(FlightLevel.BAN, FlightLevel.CAUTION, 0.6);
        assertThat(r.level()).isEqualTo(FlightLevel.BAN);
        assertThat(r.decision()).isEqualTo(FusionService.Track1Arbitration.RULE_OVERRIDES_MODEL);
    }
}
