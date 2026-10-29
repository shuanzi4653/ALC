package com.tianchuang.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.tianchuang.model.FlightLevel;
import org.junit.jupiter.api.Test;

class FusionServiceTest {
    private final FusionService fusion = new FusionService();

    @Test
    void missingTrack2UsesTrack1WithoutInventingFit() {
        var result = fusion.fuse(62, FlightLevel.CAUTION, null, 0);
        assertThat(result.fused()).isEqualTo(FlightLevel.CAUTION);
        assertThat(result.agreement()).isEqualTo(FusionService.Agreement.TRACK1_ONLY);
    }

    @Test
    void ruleBanCannotBeDowngradedByModel() {
        var result = fusion.fuse(39, FlightLevel.BAN, FlightLevel.FIT, 1);
        assertThat(result.fused()).isEqualTo(FlightLevel.BAN);
        assertThat(result.agreement()).isEqualTo(FusionService.Agreement.SAFETY_FIRST);
    }
}
