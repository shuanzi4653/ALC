package com.tianchuang.service;

import com.tianchuang.entity.AlertStateEntity;
import com.tianchuang.model.FlightLevel;
import com.tianchuang.repository.AlertStateRepo;
import java.time.LocalDateTime;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AlertStateService {
    private final AlertStateRepo repo;

    public AlertStateService(AlertStateRepo repo) { this.repo = repo; }

    public enum Action { NONE, TRIGGER, ESCALATE, RESOLVE }
    public record Decision(Action action, String episodeId, int transitionVersion, FlightLevel level) {}

    @Transactional
    public synchronized Decision evaluate(String key, long runSequence, boolean active, FlightLevel level) {
        AlertStateEntity state = repo.findByStateKey(key).orElseGet(() -> {
            AlertStateEntity value = new AlertStateEntity();
            value.stateKey = key;
            return value;
        });
        state.updatedAt = LocalDateTime.now();
        boolean sameRun = state.lastEvaluatedRunSequence != null
                && state.lastEvaluatedRunSequence == runSequence;
        state.lastEvaluatedRunSequence = runSequence;
        if (active) {
            state.lastSeenAt = state.updatedAt;
            state.recoveryCount = 0;
            if (!"ACTIVE".equals(state.state)) {
                state.state = "ACTIVE";
                state.episodeId = UUID.randomUUID().toString();
                state.level = level.name();
                state.transitionVersion += 1;
                repo.save(state);
                return new Decision(Action.TRIGGER, state.episodeId, state.transitionVersion, level);
            }
            FlightLevel previous = FlightLevel.valueOf(state.level);
            if (level.ordinal() > previous.ordinal()) {
                state.level = level.name();
                state.transitionVersion += 1;
                repo.save(state);
                return new Decision(Action.ESCALATE, state.episodeId, state.transitionVersion, level);
            }
            repo.save(state);
            return new Decision(Action.NONE, state.episodeId, state.transitionVersion, previous);
        }
        if ("ACTIVE".equals(state.state) && !sameRun) {
            state.recoveryCount += 1;
            if (state.recoveryCount >= 2) {
                FlightLevel previous = FlightLevel.valueOf(state.level);
                state.state = "RESOLVED";
                state.transitionVersion += 1;
                repo.save(state);
                return new Decision(Action.RESOLVE, state.episodeId, state.transitionVersion, previous);
            }
        }
        repo.save(state);
        return new Decision(Action.NONE, state.episodeId, state.transitionVersion,
                state.level == null ? level : FlightLevel.valueOf(state.level));
    }
}
