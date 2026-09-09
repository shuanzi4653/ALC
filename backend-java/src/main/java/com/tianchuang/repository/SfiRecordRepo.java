package com.tianchuang.repository;

import java.util.List;
import java.util.Optional;

import com.tianchuang.entity.SfiRecordEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface SfiRecordRepo extends JpaRepository<SfiRecordEntity, Long> {
    List<SfiRecordEntity> findTop48ByOrderByTsDesc();

    Optional<SfiRecordEntity> findFirstByOrderByTsDesc();
}
