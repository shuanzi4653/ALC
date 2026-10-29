package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.LocalDateTime;

/** 每个区域、来源、规则和触发类型的预警 episode 状态。 */
@Entity
@Table(name = "alert_state")
public class AlertStateEntity {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;
    @Column(nullable = false, unique = true, length = 300)
    public String stateKey;
    public String episodeId;
    public String state = "INACTIVE";
    public String level;
    public int transitionVersion;
    public int recoveryCount;
    /** 同一运行的规则阶段与轨2补全只计作一轮恢复观察。 */
    public Long lastEvaluatedRunSequence;
    public LocalDateTime lastSeenAt;
    public LocalDateTime updatedAt = LocalDateTime.now();
}
