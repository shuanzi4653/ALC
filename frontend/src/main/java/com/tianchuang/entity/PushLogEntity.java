package com.tianchuang.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/** 推送日志 */
@Entity
@Table(name = "push_log")
public class PushLogEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    public LocalDateTime ts = LocalDateTime.now();
    public Long alertId;
    public String channel;       // DINGTALK | FEISHU | WECOM | MAIL | SCREEN
    public String target;
    public String status;        // SENT | DISPLAYED | FAILED | SKIPPED
    public int latencyMs;
    public String detail;
}
