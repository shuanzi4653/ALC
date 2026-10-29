package com.tianchuang.repository;

import com.tianchuang.entity.Track2JobEntity;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface Track2JobRepo extends JpaRepository<Track2JobEntity, Long> {

    Optional<Track2JobEntity> findFirstByJobKey(String jobKey);

    /** 启动恢复：找出上次进程退出时未收敛的任务 */
    List<Track2JobEntity> findByStatusIn(Collection<String> statuses);

    List<Track2JobEntity> findTop50ByOrderByCreatedAtDesc();
}
