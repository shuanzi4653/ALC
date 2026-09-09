package com.tianchuang.model;

/**
 * 标准化实时观测快照（内部统一格式，和风数据与模拟数据均转换为此结构）
 */
public record WeatherSnapshot(
        String time,           // ISO-8601 观测时间
        String source,         // live | sim
        double lat,
        double lon,
        String conditionText,
        double tempC,
        double humidity,       // 0-1
        double windSpeed,      // m/s 平均风速
        double windGust,       // m/s 阵风
        int windDeg,           // 风向角度
        double precipMmh,      // 降水强度 mm/h
        double visibilityM,    // 能见度（米）
        double pressureHpa,    // 海平面气压
        double cloudCover,     // 云量 0-1
        double thunderProb) {  // 雷暴概率 0-1
}
