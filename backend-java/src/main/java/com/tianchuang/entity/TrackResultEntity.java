package com.tianchuang.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

@Entity
@Table(name = "track_result")
public class TrackResultEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    public LocalDateTime ts = LocalDateTime.now();
    public String runId;
    public int revision = 1;
    public String status = "COMPLETE";
    public String track1Level;
    public int track1Sfi;
    @Lob
    public String track1Reason;
    public String track2Level;
    public double track2Confidence;
    public String track2Source;
    @Lob
    public String track2Factors;
    @Lob
    public String track2Advice;
    public String fusedLevel;
    public String agreement;
    public int fusedSfi;
}
