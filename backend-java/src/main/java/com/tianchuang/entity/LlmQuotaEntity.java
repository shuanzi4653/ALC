package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

@Entity
@Table(name = "llm_quota")
public class LlmQuotaEntity {

    @Id
    @Column(name = "bucket_key", length = 160)
    public String bucketKey;

    @Column(name = "quota_day", nullable = false, length = 10)
    public String quotaDay;

    @Column(nullable = false, length = 12)
    public String dimension;

    @Column(name = "quota_key", nullable = false, length = 64)
    public String quotaKey;

    @Column(nullable = false)
    public int used;

    @Column(name = "created_at", nullable = false)
    public LocalDateTime createdAt = LocalDateTime.now();

    public LlmQuotaEntity() {
    }

    public LlmQuotaEntity(String bucketKey, String quotaDay, String dimension, String quotaKey) {
        this.bucketKey = bucketKey;
        this.quotaDay = quotaDay;
        this.dimension = dimension;
        this.quotaKey = quotaKey;
    }
}
