package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.AgentChatEntity;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface AgentChatRepo extends JpaRepository<AgentChatEntity, Long> {
    List<AgentChatEntity> findTop20ByOrderByTsDesc();

    /**
     * 某个工作区自己的最近问答。
     *
     * <p>目前没有读出口（问答历史只在写入侧留痕），这个方法是为「日后要展示
     * 历史」时准备的 —— 到时**必须**用这一条而不是上面那条全局的：全局那条会
     * 把别人问过的原话显示在你的界面上。</p>
     */
    List<AgentChatEntity> findTop20ByWorkspaceOrderByTsDesc(String workspace);

    /** 保留策略（E02）：删除早于截止时间的问答记录 */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("delete from AgentChatEntity e where e.ts < :cutoff")
    int deleteByTsBefore(@Param("cutoff") java.time.LocalDateTime cutoff);
}
