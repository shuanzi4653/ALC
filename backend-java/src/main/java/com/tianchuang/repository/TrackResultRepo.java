package com.tianchuang.repository;

import java.util.List;

import com.tianchuang.entity.TrackResultEntity;

import org.springframework.data.jpa.repository.JpaRepository;

public interface TrackResultRepo extends JpaRepository<TrackResultEntity, Long> {
    List<TrackResultEntity> findTop48ByOrderByTsDesc();
}
