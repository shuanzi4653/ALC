package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.AlertEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface AlertRepo extends JpaRepository<AlertEntity, Long> {
    List<AlertEntity> findTop20ByOrderByTsDesc();
}
