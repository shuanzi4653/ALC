package com.tianchuang.service;

import com.tianchuang.model.FlightLevel;

import org.springframework.stereotype.Service;

/**
 * 双轨融合引擎（对应计划书 5.5 节：一致性加权 + 冲突仲裁 + 安全优先）
 */
@Service
public class FusionService {

    public enum Agreement { CONSISTENT, WEIGHTED, SAFETY_FIRST, TRACK1_ONLY }

    public record FusionResult(FlightLevel fused, Agreement agreement, double fusedProb) {
    }

    /**
     * @param sfi        轨1 适飞指数（0-100）
     * @param track1     轨1 等级
     * @param track2     轨2（LLM）等级
     * @param confidence 轨2 置信度 0-1
     */
    public FusionResult fuse(int sfi, FlightLevel track1, FlightLevel track2, double confidence) {
        if (track2 == null) {
            return new FusionResult(track1, Agreement.TRACK1_ONLY, track1.riskProb());
        }
        // 1. 两轨一致：置信度提升，直接采用
        if (track1 == track2) {
            return new FusionResult(track1, Agreement.CONSISTENT, track1.riskProb());
        }
        // 2. 轨1 输出极端风险而轨2 未识别：安全优先，升级风险等级
        if (track1.ordinal() > track2.ordinal() && track1.ordinal() >= FlightLevel.DANGER.ordinal()) {
            return new FusionResult(track1, Agreement.SAFETY_FIRST, track1.riskProb());
        }
        // 3. 常规分歧：一致性加权（w2 由 LLM 置信度决定，上限 0.4）
        double w2 = 0.4 * Math.max(0, Math.min(1, confidence));
        double w1 = 1.0 - w2;
        double p1 = 1.0 - sfi / 100.0;               // 轨1 客观风险概率
        double p2 = track2.riskProb();
        double pFinal = w1 * p1 + w2 * p2;
        FlightLevel mapped = fromProb(pFinal);
        // 融合结果不低于两轨中较乐观一方（向保守侧修正）
        FlightLevel floor = track1.ordinal() <= track2.ordinal() ? track1 : track2;
        FlightLevel fused = mapped.ordinal() >= floor.ordinal() ? mapped : floor;
        return new FusionResult(fused, Agreement.WEIGHTED, pFinal);
    }

    private FlightLevel fromProb(double p) {
        if (p >= 0.8) return FlightLevel.BAN;
        if (p >= 0.55) return FlightLevel.DANGER;
        if (p >= 0.3) return FlightLevel.CAUTION;
        return FlightLevel.FIT;
    }

    // ======================================================================
    // 轨1 内部裁决：规则档位（硬底线）× 模型档位（能力增量）
    // ======================================================================
    //
    // 与上面的 fuse() 回答的**不是同一个问题**，所以不复用它的加权逻辑：
    //   fuse()                 —— 规则轨 vs 大模型轨，两个"说人话"的判断
    //   arbitrateTrack1()      —— 规则 vs 统计模型，后者是从前者学出来的
    //
    // 后者不能加权：模型的标签本来就来自一份判据（config/labels-v1.json），
    // 它与运行规则的分歧，两个方向的含义完全不对称 ——
    //   模型更**保守** ⇒ 多知道了一点（比如能见度与阵风因子的组合），采纳；
    //   模型更**乐观** ⇒ 它只是没学会那条硬线，**不采纳**，只记分歧。
    // 把它做成 0.4/0.6 的加权，等于允许一个 97% 准确的模型把"禁飞"稀释成"危险"，
    // 而这条项目红线（模型不把禁飞改可飞）就是靠这个不对称守住的。

    public enum Track1Arbitration {
        /** 规则与模型同档。 */
        CONSISTENT,
        /** 模型更保守：采纳模型档。 */
        MODEL_STICTER,
        /** 模型更乐观：**不改档**，记分歧。 */
        RULE_OVERRIDES_MODEL,
        /** 模型未参与：回落纯规则。 */
        MODEL_UNAVAILABLE
    }

    /**
     * @param ruleLevel       规则档位（永不为 null —— 规则拒判时调用方根本不该走到这里）
     * @param modelLevel      模型档位；null 表示模型不可用或本轮未参与
     * @param modelConfidence 模型置信度 0–1，仅用于把"分歧有多强"带到界面，不参与定档
     */
    public Track1Result arbitrateTrack1(FlightLevel ruleLevel, FlightLevel modelLevel, Double modelConfidence) {
        if (ruleLevel == null) {
            throw new IllegalArgumentException("规则档位不能为空：模型不能在没有规则底线时独自定档");
        }
        if (modelLevel == null) {
            return new Track1Result(ruleLevel, Track1Arbitration.MODEL_UNAVAILABLE, null);
        }
        if (modelLevel == ruleLevel) {
            return new Track1Result(ruleLevel, Track1Arbitration.CONSISTENT, modelConfidence);
        }
        if (modelLevel.ordinal() > ruleLevel.ordinal()) {
            // 更保守 —— 只升不降，且升到模型档为止（不让模型越级把它推到 BAN，
            // 除非模型自己就在 BAN；这一步不是多余的：它把"升档"限制在模型档位上）。
            return new Track1Result(modelLevel, Track1Arbitration.MODEL_STICTER, modelConfidence);
        }
        return new Track1Result(ruleLevel, Track1Arbitration.RULE_OVERRIDES_MODEL, modelConfidence);
    }

    /**
     * 轨1 裁决结果。
     *
     * @param level      最终档位
     * @param decision   哪种情形
     * @param confidence 模型置信度；{@code MODEL_UNAVAILABLE} 时为 null ——
     *                   给它填 0 会让界面显示"置信度 0%"，而真相是"没有模型"。
     */
    public record Track1Result(FlightLevel level, Track1Arbitration decision, Double confidence) {
        public String decisionLabel() {
            return switch (decision) {
                case CONSISTENT -> "规则与模型同档";
                case MODEL_STICTER -> "模型更保守，已采纳";
                case RULE_OVERRIDES_MODEL -> "规则否决模型（模型更乐观，不改档）";
                case MODEL_UNAVAILABLE -> "模型未参与";
            };
        }
    }
}
