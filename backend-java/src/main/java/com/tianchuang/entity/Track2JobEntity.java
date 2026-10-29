package com.tianchuang.entity;

import java.time.LocalDateTime;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "track2_job")
public class Track2JobEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    public String jobKey;
    public String runId;
    public String regionId;
    public String jobKind = "TRACK2";

    public String status;
    public int attempts;
    public LocalDateTime dueAt;
    public LocalDateTime createdAt;
    public LocalDateTime updatedAt;
    public String errorCode;
}
