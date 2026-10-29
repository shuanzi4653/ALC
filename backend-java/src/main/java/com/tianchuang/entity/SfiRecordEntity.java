package com.tianchuang.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

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
    public String source;
    public String scenario;
    public int sfi;
    public int rawSfi;
    public String level;
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
    public double humidity;
    public double pressureHpa;
    public double cloudCover;
    @Lob
    public String checksJson;
}
