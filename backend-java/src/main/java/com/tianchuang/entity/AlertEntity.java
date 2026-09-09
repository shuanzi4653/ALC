package com.tianchuang.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/** 预警记录 */
@Entity
@Table(name = "alert")
public class AlertEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    public LocalDateTime ts = LocalDateTime.now();
    public String level;         // DANGER | BAN（或骤变骤升的级别）
    public String triggerType;   // LEVEL_REACH | SFI_DROP
    public String region;
    @Lob
    public String factors;
    @Lob
    public String advice;
    @Lob
    public String text;          // 最终发布文本
    public String status;        // PUBLISHED | WITHDRAWN
}
