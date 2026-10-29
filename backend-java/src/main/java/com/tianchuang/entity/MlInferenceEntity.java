package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "ml_inference")
public class MlInferenceEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    @Column(name = "session_id", length = 80)
    public String sessionId;

    @Column(name = "sample_key", length = 64)
    public String sampleKey;

    @Column(name = "workspace_id", length = 64)
    public String workspaceId;

    @Column(nullable = false)
    public boolean available = true;

    @Column(length = 48)
    public String reason;

    @Column(nullable = false, length = 16)
    public String level;

    @Column(precision = 5, scale = 4)
    public BigDecimal confidence;

    @Column(precision = 5, scale = 4)
    public BigDecimal margin;

    @Column(name = "low_confidence", nullable = false)
    public boolean lowConfidence;

    @Column(nullable = false)
    public boolean degraded;

    @Column(name = "missing_count", nullable = false)
    public int missingCount;

    @Column(columnDefinition = "CLOB")
    public String top3;

    @Column(name = "rule_level", length = 16)
    public String ruleLevel;

    public Boolean agree;

    @Column(name = "model_version", nullable = false, length = 32)
    public String modelVersion;

    @Column(name = "labels_version", length = 32)
    public String labelsVersion;

    @Column(name = "inputs_sha256", length = 64)
    public String inputsSha256;

    @Column(name = "created_at", nullable = false)
    public LocalDateTime createdAt = LocalDateTime.now();

    public MlInferenceEntity() {
    }
}
