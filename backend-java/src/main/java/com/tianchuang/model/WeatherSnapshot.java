package com.tianchuang.model;

/**
 * 标准化实时观测快照（内部统一格式，和风数据与模拟数据均转换为此结构）
 */
public record WeatherSnapshot(
        String time,           // ISO-8601 观测时间
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
        Double thunderProb) {  // 雷暴概率 0-1
}
