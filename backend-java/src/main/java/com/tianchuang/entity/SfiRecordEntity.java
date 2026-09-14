package com.tianchuang.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/** 每轮监测记录：SFI + 观测快照 */
@Entity
@Table(name = "sfi_record")
public class SfiRecordEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    public LocalDateTime ts = LocalDateTime.now();
    public String runId;
    public String regionId;
    public String configuredMode;
    public String effectiveSource;
    public boolean degraded;
    public String degradeReason;
    public String obsTime;
    public LocalDateTime ingestedAt;
    public LocalDateTime evaluatedAt;
    public String source;        // live | sim
    public String scenario;      // 模拟剧本（sim 模式）
    public int sfi;
    public int rawSfi;
    public String level;         // FIT/CAUTION/DANGER/BAN
    public boolean hardBan;
    public String ruleVersion;
    public Double lat;
    public Double lon;
    public String conditionText;
    public double windSpeed;
    public double windGust;
    public Integer windDeg;
    public double precipMmh;
    public double visibilityM;
    public double thunderProb;
    public double tempC;
    public double humidity;      // 相对湿度 0-1
    public double pressureHpa;
    public double cloudCover;
    @Lob
    public String checksJson;    // 轨1 逐要素明细 JSON
}
