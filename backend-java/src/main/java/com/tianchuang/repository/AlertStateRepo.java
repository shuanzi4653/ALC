package com.tianchuang.repository;

import com.tianchuang.entity.AlertStateEntity;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AlertStateRepo extends JpaRepository<AlertStateEntity, Long> {
    Optional<AlertStateEntity> findByStateKey(String stateKey);
}
