package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.AgentChatEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface AgentChatRepo extends JpaRepository<AgentChatEntity, Long> {
    List<AgentChatEntity> findTop20ByOrderByTsDesc();
}
