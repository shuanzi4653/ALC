package com.tianchuang.service;

import com.tianchuang.model.FlightLevel;

import org.springframework.stereotype.Service;

@Service
public class FusionService {

    public enum Agreement { CONSISTENT, WEIGHTED, SAFETY_FIRST, TRACK1_ONLY }

    public record FusionResult(FlightLevel fused, Agreement agreement, double fusedProb) {
    }

    public FusionResult fuse(int sfi, FlightLevel track1, FlightLevel track2, double confidence) {
        if (track2 == null) {
            return new FusionResult(track1, Agreement.TRACK1_ONLY, track1.riskProb());
        }
        if (track1 == track2) {
            return new FusionResult(track1, Agreement.CONSISTENT, track1.riskProb());
        }
        if (track1.ordinal() > track2.ordinal() && track1.ordinal() >= FlightLevel.DANGER.ordinal()) {
            return new FusionResult(track1, Agreement.SAFETY_FIRST, track1.riskProb());
        }
        double w2 = 0.4 * Math.max(0, Math.min(1, confidence));
        double w1 = 1.0 - w2;
        double p1 = 1.0 - sfi / 100.0;
        double p2 = track2.riskProb();
        double pFinal = w1 * p1 + w2 * p2;
        FlightLevel mapped = fromProb(pFinal);
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

    public enum Track1Arbitration {
        CONSISTENT,
        MODEL_STICTER,
        RULE_OVERRIDES_MODEL,
        MODEL_UNAVAILABLE
    }

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
            return new Track1Result(modelLevel, Track1Arbitration.MODEL_STICTER, modelConfidence);
        }
        return new Track1Result(ruleLevel, Track1Arbitration.RULE_OVERRIDES_MODEL, modelConfidence);
    }

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
