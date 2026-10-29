package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;
import java.time.LocalDateTime;

/** 预警外部投递任务；eventKey 保证同一预警与渠道只入队一次。 */
@Entity
@Table(name = "outbox_event")
public class OutboxEventEntity {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;
    @Column(nullable = false, unique = true)
    public String eventKey;
    public Long alertId;
    public String channel;
    public String status = "PENDING";
    public int attempts;
    public LocalDateTime dueAt = LocalDateTime.now();
    public LocalDateTime createdAt = LocalDateTime.now();
    public LocalDateTime updatedAt = LocalDateTime.now();
    public LocalDateTime claimedAt;
    @Lob public String payload;
    public String detail;
}
