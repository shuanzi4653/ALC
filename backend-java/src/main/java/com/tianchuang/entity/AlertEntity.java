package com.tianchuang.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

@Entity
@Table(name = "alert")
public class AlertEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    public LocalDateTime ts = LocalDateTime.now();
    public String runId;
    public String episodeId;
    public int transitionVersion;
    public String level;
    public String triggerType;
    public String region;
    @Lob
    public String factors;
    @Lob
    public String advice;
    @Lob
    public String text;
    public String status;
}
