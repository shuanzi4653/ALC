package com.tianchuang.entity;

import java.time.LocalDateTime;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * 轨2（LLM 研判）异步任务。
 * 任务先持久化再由有界 worker 领取，避免「提交后 JVM 崩溃导致任务永远遗失」。
 * jobKey = runId + ":TRACK2"，唯一索引保证幂等，重复提交不会产生重复任务。
 */
@Entity
@Table(name = "track2_job")
public class Track2JobEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    /** 幂等键：runId:jobKind */
    public String jobKey;
    public String runId;
    public String regionId;
    public String jobKind = "TRACK2";

    /** PENDING / RUNNING / SUCCEEDED / FAILED / TIMEOUT / INVALID / UNAVAILABLE */
    public String status;
    public int attempts;
    /** 总期限（超预算直接收敛为 TIMEOUT，不再重试） */
    public LocalDateTime dueAt;
    public LocalDateTime createdAt;
    public LocalDateTime updatedAt;
    public String errorCode;
}
