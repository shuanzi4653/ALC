package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.AgentChatEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface AgentChatRepo extends JpaRepository<AgentChatEntity, Long> {
    List<AgentChatEntity> findTop20ByOrderByTsDesc();

    /** 保留策略（E02）：删除早于截止时间的问答记录 */
    long deleteByTsBefore(java.time.LocalDateTime cutoff);
}
