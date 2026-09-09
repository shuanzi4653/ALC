package com.tianchuang.service;

import com.tianchuang.model.FlightLevel;

import org.springframework.stereotype.Service;

/**
 * 双轨融合引擎（对应计划书 5.5 节：一致性加权 + 冲突仲裁 + 安全优先）
 */
@Service
public class FusionService {

    public enum Agreement { CONSISTENT, WEIGHTED, SAFETY_FIRST }

    public record FusionResult(FlightLevel fused, Agreement agreement, double fusedProb) {
    }

    /**
     * @param sfi        轨1 适飞指数（0-100）
     * @param track1     轨1 等级
     * @param track2     轨2（LLM）等级
     * @param confidence 轨2 置信度 0-1
     */
    public FusionResult fuse(int sfi, FlightLevel track1, FlightLevel track2, double confidence) {
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
}
