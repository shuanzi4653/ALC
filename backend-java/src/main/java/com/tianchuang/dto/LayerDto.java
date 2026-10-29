package com.tianchuang.dto;

import java.util.List;
import java.util.Map;

public record LayerDto(
        String id,
        String kind,
        String regionId,
        String runId,
        int revision,
        String source,
        boolean isSimulated,
        String validTime,
        String expiresAt,
        String crs,
        String units,
        List<Double> bbox,
        Map<String, Object> geometry,
        Map<String, Object> data,
        Map<String, Object> quality,
        String status,
        String errorCode) {
}
