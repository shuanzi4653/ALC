package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.AgentChatEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AgentChatRepo extends JpaRepository<AgentChatEntity, Long> {
    List<AgentChatEntity> findTop20ByOrderByTsDesc();

    List<AgentChatEntity> findTop20ByWorkspaceOrderByTsDesc(String workspace);

    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from AgentChatEntity e where e.ts < :cutoff")
    int deleteByTsBefore(@Param("cutoff") java.time.LocalDateTime cutoff);
}
