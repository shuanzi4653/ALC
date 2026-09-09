package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.PushLogEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface PushLogRepo extends JpaRepository<PushLogEntity, Long> {
    List<PushLogEntity> findTop50ByOrderByTsDesc();
}
