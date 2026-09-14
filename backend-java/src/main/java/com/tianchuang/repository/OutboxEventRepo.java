package com.tianchuang.repository;

import com.tianchuang.entity.OutboxEventEntity;
import java.time.LocalDateTime;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface OutboxEventRepo extends JpaRepository<OutboxEventEntity, Long> {
    List<OutboxEventEntity> findTop20ByStatusAndDueAtBeforeOrderByIdAsc(String status, LocalDateTime dueAt);
    List<OutboxEventEntity> findByStatusAndClaimedAtBefore(String status, LocalDateTime claimedAt);
    boolean existsByEventKey(String eventKey);

    /** 保留策略（E02）：仅回收已终态的投递记录，未发送事件不随历史误删 */
    long deleteByStatusInAndCreatedAtBefore(List<String> statuses, LocalDateTime cutoff);
}
