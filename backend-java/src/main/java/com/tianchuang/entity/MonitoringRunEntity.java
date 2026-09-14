package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;
import java.time.LocalDateTime;

/** 一轮监测的归属、来源、状态与时间边界。数据库主键同时作为可排序序号。 */
@Entity
@Table(name = "monitoring_run")
public class MonitoringRunEntity {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    @Column(nullable = false, unique = true, length = 36)
    public String runId;
    public int revision = 1;
    public String regionId;
    public String scenario;
    public String configuredMode;
    public String effectiveSource;
    public boolean degraded;
    public String degradeReason;
    public String status;
    public String errorCode;
    public String errorMessage;
    public String obsTime;
    public LocalDateTime startedAt;
    public LocalDateTime ingestedAt;
    public LocalDateTime evaluatedAt;
    public LocalDateTime updatedAt;
    @Lob
    public String snapshotJson;
    @Lob
    public String forecastJson;
}
